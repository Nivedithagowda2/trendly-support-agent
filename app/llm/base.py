from abc import ABC, abstractmethod
from app.sessions import Session


class LLMProvider(ABC):
    """Common interface so main.py doesn't care whether Groq or Gemini is behind it."""

    @abstractmethod
    def chat(self, session: Session, user_message: str) -> str:
        """Send a user message (with full tool-calling orchestration handled
        internally) and return the assistant's final natural-language reply."""
        raise NotImplementedError
