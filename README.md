# Decision-Making Resolution Agent

An autonomous, tool-using agent that resolves customer order issues: it reads
order records, checks warehouse inventory, and either confirms an exchange or
issues a refund when a replacement is not possible, then notifies the customer.

Built with the OpenAI function-calling API. No external services required - the
order database and warehouse inventory are in-memory mocks.

## Files and how they map to the assignment

| File | Step | Responsibility |
|------|------|----------------|
| `database.py` | - | Mock order DB + warehouse inventory (4 seed orders covering every scenario) |
| `tools.py` | 1 | Four deterministic tools returning **structured** data (`success` flag + result/error) |
| `schemas.py` | 2 | Declarative tool contracts (name, description, typed params, required fields) the model sees |
| `dispatcher.py` | 3 | Registry whitelist + execution gatekeeper + authorization check + argument validation |
| `agent.py` | 4 & 5 | ReAct state loop + guardrails (max iterations, error recovery) + interactive console + demo runner |
| `mock_model.py` | - | Offline mock of the model's tool-calling decisions (run with `--mock`, no API key/credits) |

### Step 1 - Functional tools (`tools.py`)
- `lookup_order(order_id)` -> customer identity, item, status, exchange eligibility.
- `check_inventory(item_id)` -> real-time warehouse stock + availability.
- `confirm_exchange(order_id, reason)` -> records an exchange reference (only when eligible and stock > 0).
- `process_refund(order_id, reason)` -> issues a refund reference to the original payment method.
- `notify_customer(customer_email, message_body)` -> dispatches a confirmation email.
Every tool returns `{success, ...result}` or `{success: false, error}`, never unstructured prose.

### Step 2 - Declarative contracts (`schemas.py`)
Each schema states a semantic name, an unambiguous description (the refund schema
explicitly says it is for refunds when replacement is impossible), typed input
parameters, and required fields.

### Step 3 - Registration & safe dispatch (`dispatcher.py`)
`REGISTRY` is the whitelist. `dispatch()` authorizes the tool, parses the JSON
arguments (catching malformed JSON), validates required fields, runs the
function, and converts any exception into a structured error fed back to the
loop. Unauthorized tools are rejected.

### Step 4 - The ReAct state loop (`agent.py`)
Maintains an ordered message history. Each iteration: invoke the model with the
history + tool schemas; if it returns a final text answer, exit and deliver it;
if it returns tool calls, dispatch each one and append the structured result
(linked by `tool_call_id`), then re-invoke the model.

### Step 5 - Guardrails (`agent.py`)
- **Execution ceiling**: `MAX_ITERATIONS` (default 8; the happy path needs ~5).
  Exceeding it halts and flags the session for human escalation.
- **Graceful error recovery**: tool/dispatcher failures become structured errors
  in state; the model reads them and responds helpfully (e.g. order not found).
- **Argument validation**: the dispatcher catches malformed JSON and missing
  required fields and reports them back so the model can self-correct.

## Setup

```powershell
pip install -r requirements.txt
```

Create `.env` (gitignored) with your key - see `.env.example`:

```
OPENAI_API_KEY=sk-...
AGENT_MODEL=gpt-4o-mini
```

> The default path calls the real OpenAI API, which requires your account to
> have billing credits. If you see `RateLimitError: 429 - You have no credits
> remaining`, add credits in the OpenAI dashboard, or run the agent with
> `--mock` (below) to exercise the full loop offline with no API key.

## Run it

- **Interactive console (live API):** `python agent.py` - then type customer
  messages and press Enter. Type `demo` to run the scripted scenarios, `reset`
  to re-seed the data, or `exit` to quit.
- **Interactive console (offline, no key/credits):** `python agent.py --mock`
- **Scripted scenarios (live):** `python agent.py demo`
- **Scripted scenarios (offline):** `python agent.py --mock demo`
- **One customer message:** `python agent.py "My order ORD-1002 arrived broken"`

Scenarios (each exercises one acceptance criterion):
1. `ORD-1001` - eligible, in stock -> **exchange** confirmed.
2. `ORD-1002` - eligible, out of stock -> **refund** issued.
3. `ORD-1003` - ineligible (window expired), in stock -> **refund** issued.
4. `ORD-9999` - invalid id -> **graceful error**, no refund/exchange.

## Offline self-test (no API key)

```powershell
python verify_tools.py
```
Exercises every tool and the dispatcher guardrails (authorization, malformed
JSON, missing args, graceful not-found) against the four scenarios.

## Acceptance criteria coverage
- Autonomous investigation: the agent calls `lookup_order` then `check_inventory`
  on its own from the natural-language request.
- Correct branching: stock 0 (or ineligible) -> `process_refund`; stock > 0 and
  eligible -> `confirm_exchange`.
- Complete fulfillment: every successful resolution ends with `notify_customer`
  plus a final summary.
- Resilience: an invalid order id returns an error payload the agent reports to
  the customer, asking them to verify - no crash, no refund.
