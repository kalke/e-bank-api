# E-Bank API

**DEMO ONLY** — FastAPI virtual bank for the [kalke.dev](https://kalke.dev) portfolio.
Postgres ledger, Redis idempotency/rate-limits, OIDC via sibling
[`kalke-auth`](https://github.com/kalke/kalke-auth).

Every signed-in demo user can bootstrap once and receive **USD 10,000.00** play
money. Due diligence onboarding is optional and skippable (PDE document extract
metadata only — no raw files stored here).

Interactive docs at **`/docs`** when the server is running (non-production).
Hosted API: [ebank.kalke.dev](https://ebank.kalke.dev) (login via auth BFF).

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
| `make auth-up` / `make auth-down` | Manage sibling kalke-auth |
| `make auth-token` / `make ebank-m2m-token` | Human / M2M JWT |
| `make smoke-oidc` | Token → `POST /event` (expect 422) |
| `make test` / `make lint` / `make ci` | Quality |
| `make migrate` | Apply Alembic migrations |

## Authentication and authorization

| Item | Value |
|---|---|
| AuthN | `Authorization: Bearer <JWT>` (OIDC / RS256) or BFF M2M + user-forward headers |
| Issuer | `OIDC_ISSUER` (must match JWT `iss`) |
| Audience | `e-bank-api` |
| AuthZ | access-token claim `permissions` must include `bank:write`, `bank:demo`, or `admin` |
| Public | `GET /health`, `GET /ready`, `GET /v1/demo/meta` |
| Demo | `/v1/demo/*`, `/v1/me/*`, `/v1/onboarding/*` (ownership-scoped) |
| Legacy | `/balance`, `/event`, `/reset` when `LEGACY_CHALLENGE_ROUTES=true` |

Set `OIDC_ENABLED=false` only for unit tests (CI already does this).

## Demo API

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/demo/meta` | Disclaimer + welcome amount |
| `POST` | `/v1/demo/bootstrap` | Create checking account + one-time $10,000 grant |
| `GET` | `/v1/me/account` | Owned account + balance |
| `GET` | `/v1/me/transactions` | Activity |
| `POST` | `/v1/me/transfer` | Transfer to another account id |
| `POST` | `/v1/me/withdraw` | Capped demo withdraw |
| `POST` | `/v1/onboarding/skip` | Skip due diligence and continue |

## Configuration

See [`.env.example`](.env.example). Important vars:

| Var | Purpose |
|---|---|
| `DATABASE_URL` | Async SQLAlchemy URL (`postgresql+asyncpg://…`) |
| `REDIS_URL` | Idempotency / rate-limit store |
| `OIDC_ISSUER` / `OIDC_AUDIENCE` | JWT validation |
| `OIDC_DISCOVERY_URL` | Reachable discovery/JWKS inside Docker |
| `M2M_USER_FORWARD_SECRET` | Trusted BFF user-forward |
| `CORS_ORIGINS` | Browser sandbox origins |
| `LEGACY_CHALLENGE_ROUTES` | Enable legacy `/event` routes (CI/dev) |

## Cloudflare deploy

Production target: **`ebank.kalke.dev`** (Workers + Containers) with Neon Postgres + Upstash Redis. See [DEPLOY.md](DEPLOY.md). Push to `main` runs CI then deploy.

## Layout

```text
e-bank-api/
├── app/
│   ├── api/            # FastAPI routers
│   ├── auth/           # OIDC JWT + BFF forward
│   ├── core/           # db, logging, middleware, rate limit
│   ├── domain/         # Money helpers
│   ├── middleware/     # idempotency
│   ├── models/
│   ├── repositories/
│   ├── schemas/
│   ├── services/
│   └── main.py
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
