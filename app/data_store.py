"""
Loads the two fixed data sources for the assignment:
  - data/orders.json      -> orders + customers (do not mutate on disk; returns/tickets
                              raised by the agent are kept in-memory per session instead)
  - data/trendly_policy.md -> the only source of truth for policy questions

The policy doc is split into top-level ("## ") sections so the agent can retrieve
just the relevant chunk via the search_policy tool, rather than the whole document
being silently pasted into every prompt. This keeps grounding traceable: every
policy claim the model makes should trace back to a specific retrieved section.
"""
import json
import re
from dataclasses import dataclass
from typing import Optional

from app import config


@dataclass
class PolicySection:
    section_id: str      # e.g. "1"
    title: str           # e.g. "1. Shipping"
    text: str            # full markdown body of that section


class DataStore:
    def __init__(self, orders_path: str, policy_path: str):
        with open(orders_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        self.customers = {c["customer_id"]: c for c in raw["customers"]}
        self.orders = {o["order_id"]: o for o in raw["orders"]}

        with open(policy_path, "r", encoding="utf-8") as f:
            self.policy_raw = f.read()

        self.policy_sections = self._split_policy(self.policy_raw)

    @staticmethod
    def _split_policy(text: str) -> list:
        """Split the policy markdown on level-2 headers ('## N. Title')."""
        pattern = re.compile(r"^##\s+(\d+)\.\s+(.*)$", re.MULTILINE)
        matches = list(pattern.finditer(text))
        sections = []
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            section_id = m.group(1)
            title = f"{m.group(1)}. {m.group(2).strip()}"
            body = text[start:end].strip()
            sections.append(PolicySection(section_id=section_id, title=title, text=body))
        return sections

    # ---- Orders / customers -------------------------------------------------

    def get_order(self, order_id: str) -> Optional[dict]:
        return self.orders.get(order_id.strip().upper())

    def get_customer(self, customer_id: str) -> Optional[dict]:
        return self.customers.get(customer_id)

    def find_item(self, order: dict, sku: str) -> Optional[dict]:
        sku = sku.strip().upper()
        for item in order.get("items", []):
            if item["sku"].upper() == sku:
                return item
        return None

    def contact_matches(self, customer: dict, contact: str) -> bool:
        """Loose match against email or phone, for lightweight identity verification."""
        if not contact:
            return False
        contact_norm = re.sub(r"[\s\-()]", "", contact.strip().lower())
        email = (customer.get("email") or "").lower()
        phone = re.sub(r"[\s\-()]", "", (customer.get("phone") or "").lower())
        if contact_norm == email:
            return True
        if contact_norm and contact_norm in phone:
            return True
        # allow matching just the last 4-6 digits of a phone number
        digits = re.sub(r"\D", "", contact_norm)
        phone_digits = re.sub(r"\D", "", phone)
        if digits and len(digits) >= 4 and digits in phone_digits:
            return True
        return False

    # ---- Policy search --------------------------------------------------------

    def search_policy(self, query: str, top_k: int = 2) -> list:
        """Very small keyword-overlap scorer over policy sections. Deliberately
        simple (no embeddings) since the doc is short and this keeps retrieval
        fully deterministic and auditable for a support-policy use case."""
        tokens = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2]
        if not tokens:
            return []
        scored = []
        for sec in self.policy_sections:
            hay = (sec.title + " " + sec.text).lower()
            score = sum(hay.count(tok) for tok in tokens)
            if score > 0:
                scored.append((score, sec))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [sec for _, sec in scored[:top_k]]


store = DataStore(config.ORDERS_PATH, config.POLICY_PATH)
