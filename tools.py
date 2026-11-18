"""
Step 1 - Functional tools.

Each tool is an isolated, deterministic function that performs exactly one
action against the mock data store and returns STRUCTURED data: a dict with an
explicit `success` flag and either a result object (`order` / `inventory` /
`exchange` / `refund` / `notification`) or an `error` string. Tools never raise
on bad input and never return unstructured prose - the agent reasons over the
structured payload.
"""

import uuid

from database import get_order, get_inventory, set_resolution


def lookup_order(order_id: str) -> dict:
    """Retrieve customer identity, item, status and exchange eligibility for an order."""
    if not isinstance(order_id, str) or not order_id.strip():
        return {"success": False, "error": "order_id is required and must be a non-empty string."}

    order = get_order(order_id)
    if order is None:
        return {
            "success": False,
            "error": f"No order found with id '{order_id}'. Please verify the order identifier.",
        }

    return {
        "success": True,
        "order": {
            "order_id": order.order_id,
            "customer_name": order.customer_name,
            "customer_email": order.customer_email,
            "item_id": order.item_id,
            "item_name": order.item_name,
            "order_status": order.order_status,
            "amount": order.amount,
            "currency": order.currency,
            "payment_method": order.payment_method,
            "exchange_eligible": order.exchange_eligible,
            "policy_note": order.policy_note,
            "current_resolution": order.resolution,
        },
    }


def check_inventory(item_id: str) -> dict:
    """Return real-time warehouse stock and availability for an item."""
    if not isinstance(item_id, str) or not item_id.strip():
        return {"success": False, "error": "item_id is required and must be a non-empty string."}

    inv = get_inventory(item_id)
    if inv is None:
        return {
            "success": False,
            "error": f"No inventory record found for item '{item_id}'.",
        }

    return {
        "success": True,
        "inventory": {
            "item_id": inv.item_id,
            "item_name": inv.item_name,
            "stock": inv.stock,
            "available": inv.stock > 0,
            "warehouse": inv.warehouse,
        },
    }


def confirm_exchange(order_id: str, reason: str) -> dict:
    """Confirm a replacement exchange when the order is eligible and stock > 0."""
    if not isinstance(order_id, str) or not order_id.strip():
        return {"success": False, "error": "order_id is required and must be a non-empty string."}

    order = get_order(order_id)
    if order is None:
        return {"success": False, "error": f"Order '{order_id}' not found; cannot confirm an exchange."}
    if not order.exchange_eligible:
        return {
            "success": False,
            "error": f"Order '{order_id}' is not eligible for exchange: {order.policy_note}",
        }

    inv = get_inventory(order.item_id)
    if inv is None or inv.stock <= 0:
        return {
            "success": False,
            "error": f"No replacement stock for item '{order.item_id}' ({order.item_name}); an exchange is not possible.",
        }

    inv.stock -= 1
    reference = f"EXC-{uuid.uuid4().hex[:8].upper()}"
    set_resolution(order_id, "exchanged", reference)
    return {
        "success": True,
        "exchange": {
            "order_id": order.order_id,
            "exchange_reference": reference,
            "item_id": order.item_id,
            "item_name": order.item_name,
            "reason": reason or "customer-reported issue",
            "status": "exchange_confirmed",
            "remaining_stock": inv.stock,
        },
    }


def process_refund(order_id: str, reason: str) -> dict:
    """Issue a financial refund to the customer's original payment method."""
    if not isinstance(order_id, str) or not order_id.strip():
        return {"success": False, "error": "order_id is required and must be a non-empty string."}

    order = get_order(order_id)
    if order is None:
        return {"success": False, "error": f"Order '{order_id}' not found; cannot issue a refund."}
    if order.resolution == "refunded":
        return {
            "success": False,
            "error": f"Order '{order_id}' has already been refunded (reference {order.refund_reference}).",
        }

    reference = f"REF-{uuid.uuid4().hex[:8].upper()}"
    set_resolution(order_id, "refunded", reference)
    return {
        "success": True,
        "refund": {
            "order_id": order.order_id,
            "refund_reference": reference,
            "amount": order.amount,
            "currency": order.currency,
            "payment_method": order.payment_method,
            "reason": reason or "replacement unavailable",
            "status": "refunded",
        },
    }


def notify_customer(customer_email: str, message_body: str) -> dict:
    """Dispatch an official confirmation email to the customer."""
    if not isinstance(customer_email, str) or "@" not in customer_email or "." not in customer_email:
        return {"success": False, "error": "A valid customer_email address is required."}
    if not isinstance(message_body, str) or not message_body.strip():
        return {"success": False, "error": "message_body is required and must be non-empty."}

    message_id = f"MSG-{uuid.uuid4().hex[:8].upper()}"
    return {
        "success": True,
        "notification": {
            "to": customer_email,
            "message_id": message_id,
            "status": "sent",
        },
    }
