"""
The agent's tool surface. Six tools, each mapping to one required capability
from the assignment:

  lookup_order              -> order status in plain language + identity check
  search_policy              -> policy grounding (2, "no invented policy")
  check_return_eligibility   -> combines order data + policy rules
  raise_return_request       -> acts on an eligibility decision
  request_delay_credit       -> the other "act on a policy rule" path (1.5)
  escalate_to_human          -> clean handoff with a usable summary

Every function takes `session` first so state (verification, eligibility gate,
tickets) carries across turns. Functions return small JSON-serialisable dicts;
the LLM turns those into natural language, it does not invent facts on top of them.
"""
from app import config
from app.data_store import store
from app.policy_engine import evaluate_return_eligibility, evaluate_delay_credit
from app.sessions import Session


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def lookup_order(session: Session, order_id: str, contact: str = "") -> dict:
    order_id = (order_id or "").strip().upper()
    order = store.get_order(order_id)
    if order is None:
        return {"found": False, "error": f"No order found with ID '{order_id}'."}

    if order_id not in session.verified_orders:
        customer = store.get_customer(order["customer_id"])
        if not contact or not store.contact_matches(customer, contact):
            return {
                "found": True,
                "verified": False,
                "message": (
                    "Identity verification is required before order details can be "
                    "shared. Ask the customer for the email or phone number used on "
                    "this order, then call lookup_order again with that as 'contact'."
                ),
            }
        session.verified_orders[order_id] = order["customer_id"]

    customer = store.get_customer(order["customer_id"])
    return {
        "found": True,
        "verified": True,
        "order_id": order["order_id"],
        "status": order["status"],
        "placed_at": order["placed_at"],
        "delivered_at": order.get("delivered_at"),
        "expected_delivery": order.get("expected_delivery"),
        "carrier": order.get("carrier"),
        "tracking_number": order.get("tracking_number"),
        "payment_method": order.get("payment_method"),
        "shipping_city": order.get("shipping_city"),
        "items": order.get("items", []),
        "total": order.get("total"),
        "customer_name": customer.get("name") if customer else None,
        "cancelled_at": order.get("cancelled_at"),
        "refund_status": order.get("refund_status"),
    }


def search_policy(session: Session, query: str) -> dict:
    sections = store.search_policy(query, top_k=2)
    if not sections:
        return {
            "found": False,
            "message": (
                "No matching section in trendly_policy.md. This topic is not covered "
                "by policy -- do not guess or invent a rule. Tell the customer this "
                "isn't something you can confirm and offer to escalate to a human agent."
            ),
        }
    return {
        "found": True,
        "sections": [{"section": s.title, "text": s.text} for s in sections],
    }


def check_return_eligibility(session: Session, order_id: str, sku: str) -> dict:
    order_id = (order_id or "").strip().upper()
    if order_id not in session.verified_orders:
        return {
            "error": (
                "This order has not been verified in this conversation yet. "
                "Call lookup_order first to verify identity before checking eligibility."
            )
        }
    order = store.get_order(order_id)
    if order is None:
        return {"error": f"No order found with ID '{order_id}'."}
    item = store.find_item(order, sku)
    result = evaluate_return_eligibility(order, item, config.today())
    session.last_eligibility[(order_id, sku.strip().upper())] = result
    return result


def raise_return_request(
    session: Session,
    order_id: str,
    sku: str,
    resolution_type: str,
    new_size: str = "",
) -> dict:
    order_id = (order_id or "").strip().upper()
    sku_norm = (sku or "").strip().upper()
    key = (order_id, sku_norm)

    prior = session.last_eligibility.get(key)
    if not prior:
        return {
            "error": (
                "check_return_eligibility has not been run for this order/SKU in this "
                "conversation. Call it first -- never raise a return without a fresh "
                "eligibility check backing it."
            )
        }
    if not prior.get("eligible"):
        return {
            "error": (
                "The last eligibility check for this item was NOT eligible "
                f"({prior.get('reason')}). Do not raise a return against this result."
            )
        }
    if prior.get("resolution") == "exchange_only" and resolution_type != "exchange":
        return {
            "error": (
                "This item is final-sale and only eligible for a size exchange, "
                "not a refund. Use resolution_type='exchange'."
            )
        }
    if resolution_type == "exchange" and not new_size:
        return {"error": "new_size is required when resolution_type is 'exchange'."}

    order = store.get_order(order_id)
    item = store.find_item(order, sku_norm)
    ticket = session.add_ticket(
        "return",
        {
            "order_id": order_id,
            "sku": sku_norm,
            "item_name": item["name"] if item else sku_norm,
            "resolution_type": resolution_type,
            "new_size": new_size or None,
            "refund_timeline": prior.get("refund_timeline"),
            "status": "raised",
        },
    )
    return {"success": True, "ticket": ticket}


def request_delay_credit(session: Session, order_id: str) -> dict:
    order_id = (order_id or "").strip().upper()
    if order_id not in session.verified_orders:
        return {
            "error": (
                "This order has not been verified in this conversation yet. "
                "Call lookup_order first."
            )
        }
    order = store.get_order(order_id)
    if order is None:
        return {"error": f"No order found with ID '{order_id}'."}

    result = evaluate_delay_credit(order, config.today())
    if result.get("eligible"):
        ticket = session.add_ticket(
            "delay_credit",
            {
                "order_id": order_id,
                "amount": result["credit_amount"],
                "currency": "INR",
                "status": "issued",
            },
        )
        result = {**result, "ticket": ticket}
    return result


def escalate_to_human(
    session: Session, reason: str, summary: str, order_id: str = ""
) -> dict:
    ticket = session.add_ticket(
        "escalation",
        {
            "order_id": (order_id or "").strip().upper() or None,
            "reason": reason,
            "summary": summary,
            "status": "queued_for_human",
            "support_hours": "9:00 AM - 9:00 PM IST, seven days a week",
        },
    )
    return {"success": True, "ticket": ticket}


TOOL_FUNCS = {
    "lookup_order": lookup_order,
    "search_policy": search_policy,
    "check_return_eligibility": check_return_eligibility,
    "raise_return_request": raise_return_request,
    "request_delay_credit": request_delay_credit,
    "escalate_to_human": escalate_to_human,
}

# ---------------------------------------------------------------------------
# OpenAI-style function schemas (consumed directly by the Groq provider;
# converted to Gemini's FunctionDeclaration format by the Gemini provider)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_order",
            "description": (
                "Look up a Trendly order by ID: status, items, dates, carrier, and "
                "shipping info. If this order has not been verified yet in this "
                "conversation, also pass the customer's contact (their email or "
                "phone number) to verify identity. If verification fails or contact "
                "is missing, ask the customer for it before calling again. Never "
                "reuse a contact given for a different order."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "Trendly order ID, e.g. TR-4521."},
                    "contact": {
                        "type": "string",
                        "description": "Customer's email or phone, for one-time identity verification.",
                    },
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_policy",
            "description": (
                "Search trendly_policy.md for the section(s) relevant to a question. "
                "This is the ONLY source of policy truth. Always call this before "
                "stating any policy rule, deadline, fee, or eligibility criterion -- "
                "never answer a policy question from memory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords for the policy topic, e.g. 'return window', 'lost parcel'.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_return_eligibility",
            "description": (
                "Determine whether a specific item on a verified order is eligible "
                "for return or exchange, by applying policy rules to the order's "
                "actual data. Always call this before telling a customer whether "
                "they can return/exchange something, and before raise_return_request."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "Trendly order ID."},
                    "sku": {"type": "string", "description": "SKU of the item in question."},
                },
                "required": ["order_id", "sku"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "raise_return_request",
            "description": (
                "Officially raise a return or exchange, only after "
                "check_return_eligibility already returned eligible=true for the "
                "same order_id and sku in this conversation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "sku": {"type": "string"},
                    "resolution_type": {
                        "type": "string",
                        "enum": ["refund", "exchange"],
                        "description": "What the customer wants.",
                    },
                    "new_size": {
                        "type": "string",
                        "description": "Required if resolution_type is 'exchange'.",
                    },
                },
                "required": ["order_id", "sku", "resolution_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_delay_credit",
            "description": (
                "Check whether an undelivered, verified order is delayed (more than "
                "3 business days past expected delivery) and, if eligible, issue the "
                "₹250 store credit from policy 1.5. Use when a customer asks about a "
                "late order or requests the delay credit."
            ),
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": (
                "Hand off to a human agent: lost parcels, COD bank details, a second "
                "exchange on the same item, damaged/wrong items, or anything policy "
                "does not cover or you should not decide yourself. Produces a ticket "
                "summary a human can act on immediately."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": (
                            "Short category: lost_parcel, cod_refund_bank_details, "
                            "second_exchange, damaged_or_wrong_item, "
                            "uncovered_policy_question, discount_or_goodwill_request, other."
                        ),
                    },
                    "summary": {
                        "type": "string",
                        "description": "1-3 sentence summary a human agent can act on immediately.",
                    },
                    "order_id": {"type": "string", "description": "Optional related order ID."},
                },
                "required": ["reason", "summary"],
            },
        },
    },
]
