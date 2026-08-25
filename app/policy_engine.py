"""
Deterministic policy logic.

Why this exists as code and not a prompt: the assignment explicitly warns against
"no invented policy" and "no hallucinations." Eligibility, refund timelines, and
delay credits are rule-based facts, not language-generation tasks -- so they are
computed here in plain Python against orders.json + the rules in trendly_policy.md,
and the LLM's job is only to call these functions and explain the result in plain
language. The LLM never decides eligibility itself.
"""
from datetime import date, datetime, timedelta
from typing import Optional

NON_RETURNABLE_CATEGORIES = {"innerwear", "jewellery", "beauty", "face_masks", "gift_cards"}

REFUND_TIMELINE_BY_PAYMENT = {
    "credit_card": "5-7 business days to the original card after inspection",
    "debit_card": "5-7 business days to the original card after inspection",
    "prepaid_card": "5-7 business days to the original card after inspection",
    "upi": "3-5 business days to the original UPI ID after inspection",
    "cash_on_delivery": (
        "7-10 business days via bank transfer or store credit after inspection "
        "(bank details are collected securely by a human agent, never in chat)"
    ),
    "store_credit": "issued immediately as store credit",
}


def _parse_date(value: Optional[str]):
    if not value:
        return None
    # Accept both date-only and full ISO datetime strings.
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return date.fromisoformat(value[:10])


def business_days_between(start: date, end: date) -> int:
    """Count weekdays strictly between two dates (simple Mon-Fri business-day model;
    Trendly-specific public holidays are out of scope for this assignment)."""
    if end <= start:
        return 0
    days = 0
    cur = start
    while cur < end:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            days += 1
    return days


def evaluate_return_eligibility(order: dict, item: Optional[dict], today: date) -> dict:
    """Implements policy sections 2 (Returns) and 4 (Exchanges)."""
    if item is None:
        return {
            "eligible": False,
            "resolution": None,
            "escalate": False,
            "reason": "No matching item/SKU was found on this order.",
        }

    if order["status"] == "cancelled":
        return {
            "eligible": False,
            "resolution": None,
            "escalate": False,
            "reason": (
                "This order was already cancelled and refunded "
                f"({order.get('refund_status', 'refund status unknown')}). "
                "Per policy 2.6, no return can be raised against a cancelled order."
            ),
        }

    if order["status"] == "lost_in_transit":
        return {
            "eligible": False,
            "resolution": None,
            "escalate": True,
            "escalate_reason": "lost_parcel",
            "reason": (
                "This order is marked lost in transit. Per policy 1.6, this is a "
                "lost-parcel claim, not a return, and must be resolved by a human "
                "agent (free replacement or full refund, customer's choice)."
            ),
        }

    if not order.get("delivered_at"):
        return {
            "eligible": False,
            "resolution": None,
            "escalate": False,
            "reason": "This order has not been delivered yet, so there is nothing to return yet.",
        }

    delivered = _parse_date(order["delivered_at"])
    days_since = (today - delivered).days

    category = item.get("category", "")
    if category in NON_RETURNABLE_CATEGORIES:
        return {
            "eligible": False,
            "resolution": None,
            "escalate": False,
            "days_since_delivery": days_since,
            "reason": (
                f"'{item['name']}' is in a non-returnable category ('{category}') "
                "per policy 2.3 (hygiene/safety exclusion), regardless of the return window."
            ),
        }

    if days_since > 30:
        return {
            "eligible": False,
            "resolution": None,
            "escalate": False,
            "days_since_delivery": days_since,
            "reason": (
                f"Delivered {days_since} days ago. Per policy 2.1, the 30-day return "
                "window (counted from delivery) has expired, so this is not eligible "
                "under any circumstance."
            ),
        }

    notes = []
    if category == "footwear":
        notes.append(
            "Footwear must be returned in its original shoe box; a ₹300 deduction "
            "applies if the box is missing (policy 2.5)."
        )

    if item.get("final_sale"):
        return {
            "eligible": True,
            "resolution": "exchange_only",
            "escalate": False,
            "days_since_delivery": days_since,
            "notes": notes,
            "reason": (
                "Item is marked final sale: eligible for a size exchange only, "
                "no refund or store credit (policy 2.4). The 30-day window still applies "
                "and has not expired."
            ),
        }

    refund_timeline = REFUND_TIMELINE_BY_PAYMENT.get(
        order.get("payment_method", ""), "per policy 3.1, based on original payment method"
    )
    return {
        "eligible": True,
        "resolution": "refund_or_exchange",
        "escalate": False,
        "days_since_delivery": days_since,
        "refund_timeline": refund_timeline,
        "shipping_fee_refundable": False,
        "notes": notes,
        "reason": (
            "Within the 30-day return window (policy 2.1) and in a returnable "
            "category (policy 2.3). Eligible for a refund or a size exchange (policy 4.1)."
        ),
    }


def evaluate_delay_credit(order: dict, today: date) -> dict:
    """Implements policy 1.5 (delayed orders -> ₹250 store credit on request)."""
    if order["status"] == "delivered":
        return {
            "eligible": False,
            "reason": "This order has already been delivered, so it does not qualify as delayed.",
        }
    if order["status"] == "lost_in_transit":
        return {
            "eligible": False,
            "escalate": True,
            "escalate_reason": "lost_parcel",
            "reason": (
                "This order is marked lost in transit, which is handled as a "
                "lost-parcel claim (policy 1.6) by a human agent, not a delay credit."
            ),
        }
    if order["status"] == "cancelled":
        return {"eligible": False, "reason": "This order was cancelled, so delay credit does not apply."}

    expected = _parse_date(order.get("expected_delivery"))
    if not expected:
        return {"eligible": False, "reason": "No expected delivery date is on file for this order."}

    days_late = business_days_between(expected, today)
    if days_late > 3:
        return {
            "eligible": True,
            "days_late_business_days": days_late,
            "credit_amount": 250,
            "reason": (
                f"Order is {days_late} business days past its expected delivery date "
                f"({expected.isoformat()}), which is more than the 3-business-day threshold "
                "in policy 1.5. Qualifies for a ₹250 store credit on request; the customer "
                "does not need to cancel to receive it."
            ),
        }
    return {
        "eligible": False,
        "days_late_business_days": days_late,
        "reason": (
            f"Order is {days_late} business day(s) past its expected delivery date, which is "
            "not yet more than the 3-business-day threshold in policy 1.5."
        ),
    }
