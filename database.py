"""
Mock data store: the order database and the warehouse inventory.

In production these would be SQL tables and an inventory service. Here they
are in-memory dicts so the agent can be exercised end-to-end without external
infrastructure. State mutations (an accepted exchange, an issued refund) are
recorded on the order so the resolution is observable across tool calls and
across a demo run.

Four seed orders cover every acceptance scenario:
    ORD-1001  eligible, replacement IN stock       -> exchange branch
    ORD-1002  eligible, replacement OUT of stock    -> refund branch (no stock)
    ORD-1003  NOT eligible (exchange window expired) -> refund branch (ineligible)
    ORD-1004  eligible, replacement IN stock        -> exchange branch
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Order:
    order_id: str
    customer_name: str
    customer_email: str
    item_id: str
    item_name: str
    order_status: str            # e.g. "delivered", "shipped", "cancelled"
    amount: float
    currency: str
    payment_method: str          # original payment method, used for refunds
    exchange_eligible: bool      # policy eligibility flag
    policy_note: str             # human-readable eligibility reason
    resolution: Optional[str] = None        # "exchanged" / "refunded" once resolved
    refund_reference: Optional[str] = None
    exchange_reference: Optional[str] = None


@dataclass
class InventoryRecord:
    item_id: str
    item_name: str
    stock: int                    # available replacement units in the warehouse
    warehouse: str


def _seed_orders() -> dict:
    return {
        "ORD-1001": Order(
            order_id="ORD-1001",
            customer_name="Aarav Sharma",
            customer_email="aarav.sharma@example.com",
            item_id="SKU-NH-01",
            item_name="Noise-Cancelling Headphones",
            order_status="delivered",
            amount=199.00,
            currency="USD",
            payment_method="Visa ****4111",
            exchange_eligible=True,
            policy_note="Within 30-day exchange window; item delivered.",
        ),
        "ORD-1002": Order(
            order_id="ORD-1002",
            customer_name="Bianca Rossi",
            customer_email="bianca.rossi@example.com",
            item_id="SKU-WB-02",
            item_name="Wireless Blender",
            order_status="delivered",
            amount=89.50,
            currency="USD",
            payment_method="Mastercard ****5222",
            exchange_eligible=True,
            policy_note="Within 30-day exchange window; item delivered.",
        ),
        "ORD-1003": Order(
            order_id="ORD-1003",
            customer_name="Chen Wei",
            customer_email="chen.wei@example.com",
            item_id="SKU-SK-03",
            item_name="Stainless Steel Kettle",
            order_status="delivered",
            amount=45.00,
            currency="USD",
            payment_method="Visa ****4333",
            exchange_eligible=False,
            policy_note="Exchange window expired (purchased 95 days ago).",
        ),
        "ORD-1004": Order(
            order_id="ORD-1004",
            customer_name="Dana Okafor",
            customer_email="dana.okafor@example.com",
            item_id="SKU-CL-04",
            item_name="Ceramic Lamp",
            order_status="delivered",
            amount=60.00,
            currency="USD",
            payment_method="Amex ****3444",
            exchange_eligible=True,
            policy_note="Within 30-day exchange window; item delivered.",
        ),
    }


def _seed_inventory() -> dict:
    return {
        "SKU-NH-01": InventoryRecord("SKU-NH-01", "Noise-Cancelling Headphones", 5, "WH-East"),
        "SKU-WB-02": InventoryRecord("SKU-WB-02", "Wireless Blender", 0, "WH-East"),   # out of stock -> forces refund
        "SKU-SK-03": InventoryRecord("SKU-SK-03", "Stainless Steel Kettle", 8, "WH-West"),
        "SKU-CL-04": InventoryRecord("SKU-CL-04", "Ceramic Lamp", 3, "WH-West"),
    }


# Current mutable state.
ORDERS: dict = _seed_orders()
INVENTORY: dict = _seed_inventory()


def reset_state() -> None:
    """Re-seed orders and inventory. Call before each demo scenario so one
    resolution does not bleed into the next."""
    global ORDERS, INVENTORY
    ORDERS = _seed_orders()
    INVENTORY = _seed_inventory()


def get_order(order_id: str) -> Optional[Order]:
    key = str(order_id).strip().upper()
    return ORDERS.get(key)


def get_inventory(item_id: str) -> Optional[InventoryRecord]:
    key = str(item_id).strip().upper()
    return INVENTORY.get(key)


def set_resolution(order_id: str, resolution: str,
                   reference: Optional[str] = None) -> None:
    order = get_order(order_id)
    if order is None:
        return
    order.resolution = resolution
    if resolution == "refunded":
        order.refund_reference = reference
    elif resolution == "exchanged":
        order.exchange_reference = reference
