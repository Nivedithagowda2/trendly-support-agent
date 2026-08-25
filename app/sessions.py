"""
In-memory, per-session state. Good enough for a screening assignment / demo;
see SOLUTION.md for the production-persistence trade-off note.
"""
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Session:
    session_id: str
    created_at: float = field(default_factory=time.time)

    # Raw chat transcript, provider-agnostic: [{"role": "user"/"assistant", "content": str}]
    # Providers translate this into their own wire format as needed.
    messages: List[Dict[str, Any]] = field(default_factory=list)

    # Cached provider-native chat object (used by the Gemini provider, which is
    # stateful on its own). Left as None / unused by the Groq provider.
    provider_native_chat: Any = None

    # order_id -> customer_id, set once an order passes identity verification.
    # Gates lookup_order from re-asking for contact info every turn, and gates
    # check_return_eligibility / raise_return_request from running on an
    # unverified order at all.
    verified_orders: Dict[str, str] = field(default_factory=dict)

    # (order_id, sku) -> last eligibility result. raise_return_request refuses
    # to run unless check_return_eligibility already ran for the same pair in
    # this session and returned eligible=True -- this is what stops the model
    # from approving a return it never actually checked.
    last_eligibility: Dict[Tuple[str, str], dict] = field(default_factory=dict)

    # Everything "raised" or "escalated" during the conversation, for the
    # transcript / demo and for the chat UI's side panel.
    tickets: List[Dict[str, Any]] = field(default_factory=list)

    def add_ticket(self, kind: str, payload: dict) -> dict:
        ticket = {
            "ticket_id": f"{kind.upper()[:3]}-{uuid.uuid4().hex[:8].upper()}",
            "kind": kind,
            "created_at": time.time(),
            **payload,
        }
        self.tickets.append(ticket)
        return ticket


class SessionStore:
    def __init__(self):
        self._sessions: Dict[str, Session] = {}

    def get_or_create(self, session_id: Optional[str]) -> Session:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        sid = session_id or str(uuid.uuid4())
        session = Session(session_id=sid)
        self._sessions[sid] = session
        return session

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


session_store = SessionStore()
