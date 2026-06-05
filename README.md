# EBANX Bank API

In-memory bank account API for the EBANX technical challenge. It exposes three operations: reset state, query balance, and process financial events (deposit, withdraw, transfer).

With the server running, interactive documentation is available at **`/docs`** (Swagger UI), generated automatically by FastAPI.

## Requirements

- **Python 3.11+** (`python --version`)
- **pip** and **venv** (standard library)

## Setup (first time only)

From the project root:

```bash
cd e-bank-api
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

`requirements-dev.txt` includes runtime dependencies plus test tools (`pytest`, `httpx2`). For production or Docker, use `requirements.txt` only.

### Troubleshooting (Ubuntu / Debian / WSL)

On Debian/Ubuntu, APT package names use the `python3` prefix, but this project uses the **`python`** command in all examples.

If `python` is not found or `python -m venv .venv` fails with **ensurepip is not available**, run (adjust the venv package to your version, e.g. `python3.12-venv`):

```bash
sudo apt update
sudo apt install python-is-python3 python3.14-venv python3-pip
rm -rf .venv
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

- **`python-is-python3`** — makes `python` point to Python 3 (required on many Ubuntu/WSL installs).
- **`python3.14-venv`** — provides `venv` and `pip` for that Python version; use `python3.12-venv` or `python3.11-venv` if `python --version` differs.

## Run the project

**The API must be running before you call it.** `curl` or the test suite will fail with *Could not connect to server* if nothing is listening on port 3000.

### Step 1 — Start the server (keep this terminal open)

With the virtual environment activated:

```bash
cd e-bank-api
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload
```

`--reload` restarts the server when you change Python files (useful during development or a live interview).

You should see something like:

```text
INFO:     Uvicorn running on http://0.0.0.0:3000 (Press CTRL+C to quit)
```

Leave this process **running**. Do not close this terminal while you test the API.

**Interactive docs:** open **[http://localhost:3000/docs](http://localhost:3000/docs)** in your browser to list every endpoint, view request/response schemas, and send test calls without writing `curl` commands.

### Step 2 — Call the API

#### Option A — Swagger UI (`/docs`)

1. With the server running, go to [http://localhost:3000/docs](http://localhost:3000/docs).
2. Try **POST /reset**, then **POST /event** (deposit / withdraw / transfer), then **GET /balance**.
3. Request bodies and models match `app/schemas.py` (e.g. `EventIn`).

Alternative layouts: [http://localhost:3000/redoc](http://localhost:3000/redoc) (ReDoc), [http://localhost:3000/openapi.json](http://localhost:3000/openapi.json) (OpenAPI JSON).

#### Option B — `curl` (second terminal)

Open **another** terminal and run:

```bash
curl -X POST http://localhost:3000/reset
curl "http://localhost:3000/balance?account_id=100"
```

Expected:

- `POST /reset` → HTTP 200, body `OK`
- `GET /balance` for a missing account → HTTP 404, JSON `{"message": "Account 100 not found"}`

Example flow with a deposit:

```bash
curl -X POST http://localhost:3000/reset
curl -X POST http://localhost:3000/event \
  -H "Content-Type: application/json" \
  -d '{"type":"deposit","destination":"100","amount":10}'
curl "http://localhost:3000/balance?account_id=100"
```

Last line should return `10`.

### Step 3 — Stop the server

In the terminal where uvicorn is running, press **Ctrl+C**.

## Run with Docker

Requires [Docker](https://docs.docker.com/get-docker/) installed.

```bash
docker build -t e-bank-api .
docker run --rm -p 3000:3000 e-bank-api
```

The image installs only runtime dependencies from `requirements.txt` and starts uvicorn on port **3000**. Open [http://localhost:3000/docs](http://localhost:3000/docs) to try the API.

## Running tests

With the virtual environment activated and dev dependencies installed:

```bash
pip install -r requirements-dev.txt
pytest -v
```

Tests exercise real in-memory state (business logic is not mocked in integration tests).

## API reference

The tables below summarize behavior. For interactive exploration, use **[`/docs`](http://localhost:3000/docs)** while the server is running.

### `POST /reset`

Clears all accounts. Returns **200** with body **`OK`** (plain text).

### `GET /balance?account_id={id}`

| Condition | Status | Body |
|-----------|--------|------|
| Account exists | 200 | Plain text balance (e.g. `20`) |
| Account does not exist | 404 | `{"message": "Account {id} not found"}` |

Read-only: this endpoint does not modify state.

### `POST /event`

Request body is JSON. The `type` field determines required fields.

#### Deposit

```json
{"type": "deposit", "destination": "100", "amount": 10}
```

| Result | Status | Body |
|--------|--------|------|
| Success (creates account if needed) | 201 | `{"destination": {"id": "100", "balance": 10}}` |

#### Withdraw

```json
{"type": "withdraw", "origin": "100", "amount": 5}
```

| Result | Status | Body |
|--------|--------|------|
| Success | 201 | `{"origin": {"id": "100", "balance": 15}}` |
| Unknown account | 404 | `{"message": "Account {id} not found"}` |
| Insufficient funds | 400 | `{"message": "Account {id} has insufficient funds"}` |

#### Transfer

```json
{"type": "transfer", "origin": "100", "amount": 15, "destination": "300"}
```

| Result | Status | Body |
|--------|--------|------|
| Success (creates destination if needed) | 201 | `{"origin": {"id": "...", "balance": ...}, "destination": {"id": "...", "balance": ...}}` |
| Unknown origin | 404 | `{"message": "Account {id} not found"}` |
| Insufficient funds | 400 | `{"message": "Account {id} has insufficient funds"}` |

Transfers are atomic: origin and destination balances are updated together after validation; failed transfers leave state unchanged.

Account IDs are **strings** (e.g. `"100"`).

## Project structure

```
e-bank-api/
├── app/
│   ├── main.py       # HTTP routes (thin layer)
│   ├── services.py   # Business rules
│   ├── store.py      # In-memory persistence
│   ├── schemas.py    # Request validation (Pydantic)
│   └── errors.py     # Domain exceptions
├── tests/
│   ├── test_api.py       # HTTP integration tests
│   └── test_services.py  # Unit tests for business logic
├── requirements.txt      # Runtime (API + Docker)
├── requirements-dev.txt  # Runtime + test tools
├── Dockerfile
├── .dockerignore
└── pytest.ini
```

## Design decisions

### Layering

- **HTTP** (`main.py`): maps requests/responses and status codes only.
- **Business logic** (`services.py`): deposits, withdrawals, transfers, balance reads, reset.
- **Storage** (`store.py`): in-memory `dict` of account ID → balance.

This keeps rules testable without the web layer and makes persistence easy to swap later.

### In-memory store

Sufficient for the challenge scope. No database setup is required for reviewers or the test suite.

### `requirements.txt` instead of Poetry

This project uses **`requirements.txt`** / **`requirements-dev.txt`** rather than Poetry (or similar) because:

1. **Minimal setup** — reviewers and CI can run `pip install -r requirements-dev.txt` with no extra tooling.
2. **Challenge scope** — few dependencies; a lockfile and workspace tooling add little value here.
3. **Runtime vs dev split** — `requirements.txt` powers the API and Docker image; `requirements-dev.txt` adds `pytest` and `httpx2` for local development and CI.

For a larger production service or a team repo, **Poetry** or **uv** with a lockfile would be appropriate for reproducible installs and dev/prod dependency groups.

### Error responses

Business failures return JSON with a **`message`** field and the appropriate HTTP status:

- Missing account: **404** — e.g. `{"message": "Account 100 not found"}`
- Insufficient funds: **400** — e.g. `{"message": "Account 100 has insufficient funds"}`

Domain exceptions are mapped globally in `main.py` via a FastAPI exception handler.

### Other guarantees

- **`GET /balance`** never mutates state.
- **Transfers** validate funds before updating both accounts in one service method.
- **Payload validation** (required fields per event type, positive `amount`) happens in `schemas.py` before business logic runs.

## Dependencies

| Package | Purpose | File |
|---------|---------|------|
| fastapi | HTTP API | `requirements.txt` |
| uvicorn | ASGI server | `requirements.txt` |
| pydantic | Request schemas | `requirements.txt` |
| pytest | Tests | `requirements-dev.txt` |
| httpx2 | Test client | `requirements-dev.txt` |

See [requirements.txt](requirements.txt) and [requirements-dev.txt](requirements-dev.txt) for version constraints.
