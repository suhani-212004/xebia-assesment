"""
Step 2 - Declarative tool contracts.

The language model never inspects tools.py; it only sees the JSON schemas
below. Each contract declares a semantic name and an unambiguous description
(so the model knows WHEN to call it), the input parameters with types and
descriptions, and which parameters are required before invocation.

The refund contract in particular states explicitly that it is used to issue
a financial refund only when a replacement is not possible.
"""

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_order",
            "description": (
                "Retrieve full order details for a given order id, including the customer "
                "name and email, the purchased item (item_id and item_name), the order "
                "status, the amount, the original payment method, and whether the order "
                "is eligible for exchange. Always call this first to identify the order."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order identifier provided by the customer, e.g. 'ORD-1001'.",
                    }
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_inventory",
            "description": (
                "Check real-time warehouse inventory for a specific item and return the "
                "number of replacement units in stock and whether any are available. "
                "Call this to decide whether a replacement unit can be shipped."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "The item identifier to check stock for, e.g. 'SKU-NH-01'.",
                    }
                },
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_exchange",
            "description": (
                "Confirm a replacement exchange for an order. Use this ONLY when the order "
                "is eligible for exchange AND the replacement item is in stock (stock > 0). "
                "Records an exchange reference number."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order id to exchange, e.g. 'ORD-1001'.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "A short reason for the exchange, e.g. 'item arrived damaged'.",
                    },
                },
                "required": ["order_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "process_refund",
            "description": (
                "Issue a financial refund to the customer's original payment method. Use this "
                "ONLY when an exchange is not possible: the order is NOT eligible for exchange, "
                "OR the replacement item is out of stock / unavailable. Records a refund "
                "reference number and the refunded amount."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order id to refund, e.g. 'ORD-1002'.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "A clear reason for the refund, e.g. 'replacement out of stock' or 'order not eligible for exchange'.",
                    },
                },
                "required": ["order_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notify_customer",
            "description": (
                "Dispatch an official confirmation email to the customer summarizing the "
                "resolution (exchange or refund, including any reference number). Call this "
                "after the resolution action succeeds."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_email": {
                        "type": "string",
                        "description": "The customer's email address to send the notification to.",
                    },
                    "message_body": {
                        "type": "string",
                        "description": "The full, polite email body summarizing the resolution and any reference number.",
                    },
                },
                "required": ["customer_email", "message_body"],
            },
        },
    },
]
