# E-Bank API

**DEMO ONLY** — FastAPI virtual bank for [kalke.dev](https://kalke.dev).
Postgres ledger, Redis, OIDC via [`kalke-auth`](https://github.com/kalke/kalke-auth).

Signed-in users bootstrap once and get **USD 10,000** play money. Onboarding is
optional/skippable (PDE metadata only — no raw files here).

Hosted: [ebank.kalke.dev](https://ebank.kalke.dev) (browser via auth BFF `/v1/bank/*`).

## Local

```bash
make setup && make setup-oidc
make up-all          # needs sibling ../kalke-auth
make smoke-oidc      # expect HTTP 422 (auth OK)
make test && make lint
```

API `http://localhost:8000` · IdP `http://localhost:8443`  
Docker JWKS: `OIDC_DISCOVERY_URL=http://caddy:8443/...` while JWT `iss` stays host issuer.

| Target | What |
|---|---|
| `make up` / `up-all` | API stack (+ auth) |
| `make auth-token` | Demo user JWT |
| `make aws-up` | Prod: Docker Postgres + pull GHCR on EC2 |

## Auth

| | |
|---|---|
| AuthN | Bearer JWT or BFF M2M + `X-Kalke-Forward-*` |
| Issuer / audience | `OIDC_ISSUER` / `e-bank-api` |
| AuthZ | `bank:write`, `bank:demo`, or `admin` |
| Public | `/health`, `/ready`, `/v1/demo/meta` |

Config: [`.env.example`](.env.example), [`prod.env.example`](prod.env.example).

Production Postgres is Docker on the same EC2 (`ebank-db` on `kalke-auth_default`). It is not published on `:5432`. `make aws-up` starts Postgres, then the API (Alembic on container start). Prefer **t3.small (2 GB)** + swap; a 1 GB `t3.micro` will OOM with Keycloak + two Postgres containers. Optional later: cron `pg_dump` to S3.

## Demo routes

| Method | Path |
|---|---|
| `POST` | `/v1/demo/bootstrap` |
| `GET` | `/v1/me/account`, `/v1/me/transactions` |
| `POST` | `/v1/me/transfer`, `/v1/me/withdraw` |
| `POST` | `/v1/onboarding/skip` |
