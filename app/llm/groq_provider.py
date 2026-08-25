"""
Groq provider. Groq's chat.completions API is OpenAI-compatible, so tool
schemas from app.tools.TOOL_SCHEMAS are used as-is. Groq's Python SDK does not
loop tool calls automatically, so we manage that loop explicitly here:

  1. send messages + tools to the model
  2. if it responds with tool_calls, run each one locally and append the
     results as role="tool" messages
  3. send again; repeat until the model returns a plain text answer or we
     hit MAX_TOOL_ITERATIONS (a safety cap so a confused model can't loop forever)
"""
import json

from groq import Groq

from app import config
from app.llm.base import LLMProvider
from app.prompts import SYSTEM_PROMPT
from app.sessions import Session
from app.tools import TOOL_FUNCS, TOOL_SCHEMAS


class GroqProvider(LLMProvider):
    def __init__(self):
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set. Add it to your .env file.")
        self.client = Groq(api_key=config.GROQ_API_KEY)
        self.model = config.GROQ_MODEL

    def chat(self, session: Session, user_message: str) -> str:
        if not session.messages:
            session.messages.append({"role": "system", "content": SYSTEM_PROMPT})
        session.messages.append({"role": "user", "content": user_message})

        for _ in range(config.MAX_TOOL_ITERATIONS):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=session.messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=1024,
            )
            choice = response.choices[0]
            msg = choice.message

            assistant_entry = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                assistant_entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ]
            session.messages.append(assistant_entry)

            if not msg.tool_calls:
                return msg.content or ""

            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                func = TOOL_FUNCS.get(name)
                if func is None:
                    result = {"error": f"Unknown tool '{name}'."}
                else:
                    try:
                        result = func(session, **args)
                    except TypeError as e:
                        result = {"error": f"Bad arguments for {name}: {e}"}
                session.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": name,
                        "content": json.dumps(result, default=str),
                    }
                )

        return (
            "I'm having trouble finishing that request after several steps -- "
            "let me get a human agent to take it from here."
        )
