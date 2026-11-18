"""
Step 3 - Tool registration and safe dispatch.

Security is enforced by a whitelist: the model may only invoke tools that are
registered here. `dispatch()` is the execution gatekeeper - it authorizes the
tool against the registry, parses and validates the incoming arguments, runs
the function, and converts any failure into a structured error payload that
flows back into the conversation state so the model can self-correct.
"""

import json

from tools import (
    lookup_order,
    check_inventory,
    confirm_exchange,
    process_refund,
    notify_customer,
)

# Registry whitelist: the only tools the model is authorized to call.
REGISTRY = {
    "lookup_order": lookup_order,
    "check_inventory": check_inventory,
    "confirm_exchange": confirm_exchange,
    "process_refund": process_refund,
    "notify_customer": notify_customer,
}

# Required parameters per tool, used for argument validation.
REQUIRED_PARAMS = {
    "lookup_order": ["order_id"],
    "check_inventory": ["item_id"],
    "confirm_exchange": ["order_id", "reason"],
    "process_refund": ["order_id", "reason"],
    "notify_customer": ["customer_email", "message_body"],
}


def available_tools() -> list:
    """Return the list of authorized tool names (for use in error messages)."""
    return list(REGISTRY)


def dispatch(tool_name: str, raw_arguments: object) -> dict:
    """Safe dispatch of a model-requested tool call.

    Returns a structured dict with a `success` flag and either a result
    object or an `error` string. Never raises.
    """
    # 1. Authorization: the tool must be on the registry whitelist.
    if tool_name not in REGISTRY:
        return {
            "success": False,
            "error": (
                f"Unauthorized tool '{tool_name}'. The only tools you may call are: "
                f"{available_tools()}."
            ),
        }

    # 2. Argument parsing: the model sends arguments as a JSON string.
    if raw_arguments is None:
        args = {}
    elif isinstance(raw_arguments, str):
        s = raw_arguments.strip()
        if not s:
            args = {}
        else:
            try:
                args = json.loads(s)
            except json.JSONDecodeError as e:
                return {
                    "success": False,
                    "error": (
                        f"Malformed arguments for '{tool_name}' (invalid JSON): {e}. "
                        f"Resend the arguments as valid JSON."
                    ),
                }
    elif isinstance(raw_arguments, dict):
        args = raw_arguments
    else:
        return {
            "success": False,
            "error": (
                f"Unsupported argument type {type(raw_arguments).__name__} for "
                f"'{tool_name}'; expected a JSON object."
            ),
        }

    if not isinstance(args, dict):
        return {
            "success": False,
            "error": f"Arguments for '{tool_name}' must be a JSON object.",
        }

    # 3. Required-field validation: missing fields are fed back to the model.
    missing = [p for p in REQUIRED_PARAMS[tool_name] if p not in args]
    if missing:
        return {
            "success": False,
            "error": (
                f"Missing required argument(s) {missing} for tool '{tool_name}'. "
                f"Please supply them and call the tool again."
            ),
        }

    # 4. Execute. Any exception becomes a structured error, never a crash.
    try:
        return REGISTRY[tool_name](**args)
    except TypeError as e:
        return {"success": False, "error": f"Argument error calling '{tool_name}': {e}."}
    except Exception as e:  # noqa: BLE001 - last line of defense, reported to the loop
        return {"success": False, "error": f"Tool '{tool_name}' failed: {e}."}
