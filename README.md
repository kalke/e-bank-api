# E-Bank API

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

Small FastAPI bank API: reset state, query balance, and process deposit / withdraw / transfer events. Postgres for persistence, Redis for optional idempotency, OIDC via sibling [`kalke-auth`](https://github.com/kalke/kalke-auth).

Interactive docs at **`/docs`** when the server is running. Hosted sandbox: [kalke.dev](https://kalke.dev) (login required).

## Quick start (Docker)

Prerequisites: [Docker](https://docs.docker.com/get-docker/) with Compose v2, and [Make](https://www.gnu.org/software/make/).

Sibling IdP: [`kalke-auth`](https://github.com/kalke/kalke-auth) next to this repo (shared Docker network `kalke-auth`).

```bash
make setup                 # venv + .env (+ kalke-auth/.env if sibling exists)
make setup-oidc            # OIDC_ISSUER / OIDC_AUDIENCE=e-bank-api
make up-all                # Keycloak+Caddy + API+Postgres+Redis
make smoke-oidc            # expect HTTP 422 (auth OK, validation failed)
```

- API: `http://localhost:8000` (`/docs`)
- IdP (host): `http://localhost:8443`
- Inside Compose, the API reaches JWKS via `http://caddy:8443` (`OIDC_DISCOVERY_URL`) while JWT `iss` stays `http://localhost:8443/realms/kalke`.

```bash
make docker-down / make down-all
TOKEN=$(make -s auth-token)
curl -sS -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"type":"deposit","destination":"100","amount":10}' \
  http://localhost:8000/event
```

### Everyday Make targets

| Target | What it does |
|---|---|
| `make help` | List targets |
| `make setup` | Create venv + `.env` |
| `make setup-oidc` | Enable local OIDC_* pointing at kalke-auth |
| `make up-all` | `auth-up` + API stack |
| `make up` | API + Postgres + Redis (needs network `kalke-auth`) |
| `make auth-up` / `auth-down` | Manage sibling kalke-auth |
| `make auth-token` / `ebank-m2m-token` | Human / M2M JWT |
| `make smoke-oidc` | Token → `POST /event` (expect 422) |
| `make test` / `make lint` / `make ci` | Quality |
| `make migrate` | Apply Alembic migrations |

## Authentication and authorization

| Item | Value |
|---|---|
| AuthN | `Authorization: Bearer <JWT>` (OIDC / RS256) |
| Issuer | `OIDC_ISSUER` (must match JWT `iss`) |
| Audience | `e-bank-api` |
| AuthZ | access-token claim `permissions` must include `bank:write` or `admin` |
| Public | `GET /health` only |
| Protected | `GET /balance`, `POST /event`, `POST /reset` |

Local smoke clients: `kalke-cli` (password) and `ebank-m2m` (client credentials) from kalke-auth.

Set `OIDC_ENABLED=false` only for unit tests (CI already does this).

## API

| Method | Path | Notes |
|---|---|---|
| `GET` | `/health` | Liveness |
| `GET` | `/balance?account_id=` | Balance (404 if missing) |
| `POST` | `/event` | `{type, amount, origin?, destination?}` |
| `POST` | `/reset` | Wipe accounts |

## Configuration

See [`.env.example`](.env.example). Important vars:

| Var | Purpose |
|---|---|
| `DATABASE_URL` | Async SQLAlchemy URL (`postgresql+asyncpg://…`) |
| `REDIS_URL` | Idempotency store |
| `OIDC_ISSUER` / `OIDC_AUDIENCE` | JWT validation |
| `OIDC_DISCOVERY_URL` | Reachable discovery/JWKS inside Docker |
| `CORS_ORIGINS` | Browser sandbox origins |

## Cloudflare deploy

Production target: **`ebank.kalke.dev`** (Workers + Containers) with Neon Postgres + Upstash Redis. See [DEPLOY.md](DEPLOY.md). Push to `main` runs CI then deploy.

## Layout

```text
e-bank-api/
├── app/
│   ├── auth/           # OIDC JWT validation
│   ├── core/           # db, logging, middleware
│   ├── middleware/     # idempotency
│   ├── repositories/
│   ├── main.py
│   └── services.py
├── alembic/
├── tests/
├── src/                # Cloudflare Worker proxy
├── docker-compose.yml
└── wrangler.json
```

## Local development (optional)

```bash
make setup
# start Postgres/Redis (Compose) or point DATABASE_URL / REDIS_URL at local services
export OIDC_ENABLED=false   # or run kalke-auth and set OIDC_*
make run                    # http://localhost:3000
make test
```

## License

Apache-2.0 (if present) / see repository.
