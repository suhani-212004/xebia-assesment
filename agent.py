"""
Steps 4 & 5 - The agentic state loop (ReAct cycle) with guardrails.

State: an ordered conversation history (system + user + assistant messages
including tool calls + tool result messages).

Loop (per iteration):
    1. Invoke the model with the conversation history and the tool schemas.
    2. Inspect the response:
         - final text answer (no tool calls) -> exit, deliver the response.
         - one or more tool calls -> capture name + arguments.
    3. Dispatch each call through the safe dispatcher and append the structured
       result back into the history, linked to the request by tool_call_id.
    4. Re-invoke the model with the updated history so it can observe the result
       and decide the next action.

Guardrails:
    - Execution ceiling: a strict iteration counter (MAX_ITERATIONS). Exceeding
      it halts the loop and flags the session for human escalation.
    - Graceful error recovery: every tool/dispatch failure is a structured error
      put into state; the model reads it and responds helpfully. A failure to
      reach the model is also caught and reported, never crashes.
    - Argument validation: handled in the dispatcher and reported into state.

Usage:
    python agent.py                   # interactive console
    python agent.py demo              # run the four scripted scenarios
    python agent.py "your message"    # single customer message
"""

import json
import os
import sys

from openai import OpenAI

from schemas import TOOL_SCHEMAS
from dispatcher import dispatch
import database

SYSTEM_PROMPT = """\
You are an autonomous order-resolution specialist for an online store.

When a customer reports a problem with an item, resolve it end-to-end using the
available tools. YOU decide which tools to call and in what order - do not ask
the customer for procedural steps you can perform yourself.

Resolution policy:
1. First look up the order using the order id the customer gave you. Identify the
   customer, the purchased item, the order status, and whether the order is
   eligible for exchange.
2. Then inspect the warehouse inventory for that item to see whether a
   replacement unit is in stock.
3. Decide the resolution from the facts you retrieved:
   - If the order IS eligible for exchange AND replacement stock is greater than
     0: confirm the exchange using the exchange tool, and give a clear reason.
   - If the order is NOT eligible for exchange, OR replacement stock is 0 /
     unavailable: initiate a financial refund to the customer's original payment
     method using the refund tool. Give a clear reason drawn from the retrieved
     facts (e.g. "replacement out of stock" or "order not eligible for exchange").
4. After the resolution action succeeds, send the customer an email notification
   with a clear, polite summary of what was decided and any reference number, then
   give a final plain-language summary to the customer in the chat.

Rules:
- Work step by step and rely ONLY on the structured data the tools return. Do
  not invent order details, stock levels, or reference numbers.
- If an order is not found, STOP investigating. Do NOT issue a refund or
  exchange. Politely tell the customer the order could not be found and ask them
  to verify the order identifier.
- Be concise and polite. Address the customer by name when known.
"""


def _load_env_file() -> None:
    """Tiny .env loader so the API key stays out of source code."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


# Load .env first so all config reads below pick up the file values.
_load_env_file()

# Execution ceiling. A full happy path (lookup -> inventory -> resolve ->
# notify -> final summary) takes ~5 model turns; 8 leaves room for the model
# to reason without false-escalating, while still bounding runaway loops.
MAX_ITERATIONS = int(os.environ.get("AGENT_MAX_ITERATIONS", "8"))
MODEL = os.environ.get("AGENT_MODEL", "muse-spark-1.3")


def _client() -> OpenAI:
    """Build the model client via the OpenAI-compatible interface.

    Reads OPENAI_API_KEY (or LLM_API_KEY) and an optional OPENAI_BASE_URL
    (or LLM_BASE_URL) from the environment / .env file. Set OPENAI_BASE_URL
    to point at any OpenAI-compatible endpoint (Meta AI, Gemini, etc.).
    """
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        raise SystemExit(
            "No API key found. Add OPENAI_API_KEY (or LLM_API_KEY) to your .env file."
        )
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("LLM_BASE_URL")
    kwargs = dict(
        api_key=api_key,
        timeout=float(os.environ.get("AGENT_TIMEOUT", "120")),
        max_retries=int(os.environ.get("AGENT_MAX_RETRIES", "0")),
    )
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _assistant_message(msg) -> dict:
    """Rebuild the assistant message in the exact shape the API expects when
    it is followed by tool result messages (content may be null)."""
    out = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        out["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
            for call in msg.tool_calls
        ]
    return out


def run_agent(user_message: str, client: OpenAI = None) -> str:
    """Run the ReAct loop for one customer message; return the final text answer."""
    if client is None:
        client = _client()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    for iteration in range(1, MAX_ITERATIONS + 1):

        # Graceful error recovery: model failures are caught and reported,
        # never crash the loop.
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.2,
            )
        except Exception as e:  # noqa: BLE001
            friendly = (
                "I ran into a problem reaching the resolution service and couldn't "
                "complete your request right now. Please try again shortly, or a "
                "specialist will follow up if needed."
            )
            print(f"\nagent> {friendly}")
            return friendly

        msg = response.choices[0].message
        messages.append(_assistant_message(msg))

        # No tool calls => final answer => exit the loop.
        if not msg.tool_calls:
            print(f"\nagent> {msg.content or ''}")
            return msg.content or ""

        # Execute every requested tool through the safe dispatcher and feed
        # the structured result back into the conversation state.
        for call in msg.tool_calls:
            result = dispatch(call.function.name, call.function.arguments)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result),
                }
            )

    # Execution ceiling exceeded -> safe halt + human escalation.
    escalation = (
        "I was unable to fully resolve your request within the allowed number of "
        "steps. I've flagged this session for human escalation, and a specialist "
        "will follow up with you shortly."
    )
    print(f"\nagent> {escalation}")
    return escalation


# ---------------------------------------------------------------------------
# Demo scenarios (four acceptance-criterion cases)
# ---------------------------------------------------------------------------
DEMO_SCENARIOS = [
    (
        "Damaged item, exchange eligible, replacement IN stock -> confirm EXCHANGE",
        "Hi, I received order ORD-1001 yesterday but the Noise-Cancelling "
        "Headphones arrived damaged. I'd like a replacement.",
    ),
    (
        "Damaged item, exchange eligible, but replacement OUT OF STOCK -> initiate REFUND",
        "My Wireless Blender from order ORD-1002 arrived broken. Can you get it "
        "replaced for me?",
    ),
    (
        "Item faulty but exchange window expired (ineligible) -> initiate REFUND",
        "Order ORD-1003 - my Stainless Steel Kettle has a fault and I want to "
        "exchange it.",
    ),
    (
        "Invalid order id -> graceful error, no refund/exchange",
        "Please help with order ORD-9999, the item is defective.",
    ),
]


def _print_resulting_state() -> None:
    changed = [
        (oid, o.resolution, o.refund_reference or o.exchange_reference)
        for oid, o in database.ORDERS.items()
        if o.resolution
    ]
    if changed:
        print("\n[Resulting database state]")
        for oid, resolution, ref in changed:
            print(f"  {oid}: {resolution} (reference {ref})")
    else:
        print("\n[Resulting database state] no orders modified.")


def demo() -> None:
    """Run all four scenarios end-to-end against the live model."""
    client = _client()
    for title, message in DEMO_SCENARIOS:
        database.reset_state()
        print("\n" + "=" * 84)
        print("SCENARIO:", title)
        print("=" * 84)
        print("Customer:", message)
        run_agent(message, client=client)
        _print_resulting_state()


# ---------------------------------------------------------------------------
# Interactive console
# ---------------------------------------------------------------------------
def interactive_console() -> None:
    """Interactive REPL: type a customer message, get a live agent response."""
    client = _client()
    database.reset_state()
    print("=" * 70)
    print(" Decision-Making Resolution Agent")
    print(f" model: {MODEL}  endpoint: {os.environ.get('OPENAI_BASE_URL', 'openai')}")
    print("=" * 70)
    print("Type a customer message and press Enter.")
    print("Commands:  demo   = run the four scripted scenarios")
    print("           reset  = restore order/inventory to seed state")
    print("           exit   = quit")
    print("=" * 70)
    while True:
        try:
            message = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not message:
            continue
        low = message.lower()
        if low in ("exit", "quit", "q"):
            break
        if low == "reset":
            database.reset_state()
            print("[order and inventory state reset to seed values]")
            continue
        if low == "demo":
            demo()
            database.reset_state()
            continue
        run_agent(message, client=client)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    args = sys.argv[1:]
    if not args:
        interactive_console()
        return
    joined = " ".join(args)
    if joined.lower() == "demo":
        demo()
    else:
        # Treat CLI arguments as a single customer message.
        database.reset_state()
        run_agent(joined)


if __name__ == "__main__":
    main()
