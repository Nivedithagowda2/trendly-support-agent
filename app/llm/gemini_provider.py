"""
Gemini provider. Uses google-generativeai's automatic function calling: we hand
it plain Python functions (type-hinted, with Google-style docstrings) and the
SDK infers the tool schema, decides when to call them, executes them, and loops
until it has a final text answer -- so there's no manual tool-call loop here
(contrast with the Groq provider, which manages that loop by hand).

Because automatic-function-calling tools can't take a hidden extra argument,
each session gets its own tiny set of closures that capture that session, so
state (verification, eligibility gate, tickets) still carries across turns
exactly like the Groq provider.
"""
import google.generativeai as genai

from app import config
from app.llm.base import LLMProvider
from app.prompts import SYSTEM_PROMPT
from app.sessions import Session
from app import tools as tool_impl


def _build_session_tools(session: Session):
    """Return closures with explicit signatures + Google-style docstrings so the
    SDK can auto-infer a correct function-calling schema for each one."""

    def lookup_order(order_id: str, contact: str = "") -> dict:
        """Look up a Trendly order by ID and, if not already verified this
        conversation, verify identity against the customer's email or phone.

        Args:
            order_id: Trendly order ID, e.g. TR-4521.
            contact: Customer's email or phone number, for one-time identity
                verification. Omit once the order is already verified.
        """
        return tool_impl.lookup_order(session, order_id, contact)

    def search_policy(query: str) -> dict:
        """Search trendly_policy.md for the section(s) relevant to a question.
        This is the ONLY source of policy truth -- always call this before
        stating any policy rule, deadline, fee, or eligibility criterion.

        Args:
            query: Keywords for the policy topic, e.g. "return window".
        """
        return tool_impl.search_policy(session, query)

    def check_return_eligibility(order_id: str, sku: str) -> dict:
        """Determine whether an item on a verified order is eligible for
        return or exchange, applying policy rules to the order's actual data.

        Args:
            order_id: Trendly order ID.
            sku: SKU of the item in question.
        """
        return tool_impl.check_return_eligibility(session, order_id, sku)

    def raise_return_request(
        order_id: str, sku: str, resolution_type: str, new_size: str = ""
    ) -> dict:
        """Officially raise a return or exchange, only after
        check_return_eligibility already returned eligible=true for this
        exact order and SKU in this conversation.

        Args:
            order_id: Trendly order ID.
            sku: SKU of the item being returned or exchanged.
            resolution_type: Either "refund" or "exchange".
            new_size: Required if resolution_type is "exchange".
        """
        return tool_impl.raise_return_request(session, order_id, sku, resolution_type, new_size)

    def request_delay_credit(order_id: str) -> dict:
        """Check whether a verified, undelivered order is delayed (more than
        3 business days past expected delivery) and issue the ₹250 store
        credit if eligible.

        Args:
            order_id: Trendly order ID.
        """
        return tool_impl.request_delay_credit(session, order_id)

    def escalate_to_human(reason: str, summary: str, order_id: str = "") -> dict:
        """Hand off to a human agent for lost parcels, COD bank details, a
        second exchange on the same item, damaged/wrong items, or anything
        policy does not cover.

        Args:
            reason: Short category, e.g. lost_parcel, cod_refund_bank_details,
                second_exchange, damaged_or_wrong_item, uncovered_policy_question.
            summary: 1-3 sentence summary a human agent can act on immediately.
            order_id: Optional related order ID.
        """
        return tool_impl.escalate_to_human(session, reason, summary, order_id)

    return [
        lookup_order,
        search_policy,
        check_return_eligibility,
        raise_return_request,
        request_delay_credit,
        escalate_to_human,
    ]


class GeminiProvider(LLMProvider):
    def __init__(self):
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set. Add it to your .env file.")
        genai.configure(api_key=config.GEMINI_API_KEY)
        self.model_name = config.GEMINI_MODEL

    def chat(self, session: Session, user_message: str) -> str:
        if session.provider_native_chat is None:
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=SYSTEM_PROMPT,
                tools=_build_session_tools(session),
            )
            session.provider_native_chat = model.start_chat(
                enable_automatic_function_calling=True
            )

        response = session.provider_native_chat.send_message(user_message)
        try:
            return response.text
        except ValueError:
            # No plain-text part (e.g. model stopped mid tool-call chain).
            return (
                "I'm having trouble finishing that request -- let me get a human "
                "agent to take it from here."
            )
