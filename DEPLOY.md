# Deploy e-bank-api (ebank.kalke.dev)

**DEMO ONLY** — virtual portfolio bank on the **same AWS EC2** as `kalke-auth`
and PDE (Neon Postgres + Upstash Redis + Caddy).

Push to `main` runs **Lint → Tests → Docker build/push (GHCR) → Deploy**.

## 1. Neon (free)

1. Create database `e_bank` in your Neon project.
2. Copy the connection string and convert for asyncpg:

```text
# Neon
postgresql://user:pass@ep-xxx.region.aws.neon.tech/e_bank?sslmode=require

# App DATABASE_URL
postgresql+asyncpg://user:pass@ep-xxx.region.aws.neon.tech/e_bank?sslmode=require
```

## 2. Upstash Redis (free)

1. Create a Redis database.
2. Copy the `rediss://…` URL → `REDIS_URL`.

## 3. OIDC + BFF forward

Issuer: `https://auth.kalke.dev/realms/kalke`  
Audience: `e-bank-api`

Deploy [kalke-auth](https://github.com/kalke/kalke-auth) first. Share
`M2M_USER_FORWARD_SECRET` with Auth `EBANK_USER_FORWARD_SECRET`.

## 4. GitHub secrets (`kalke/e-bank-api`)

| Secret | Value |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://…` |
| `REDIS_URL` | `rediss://…` |
| `OIDC_ISSUER` | `https://auth.kalke.dev/realms/kalke` |
| `OIDC_AUDIENCE` | `e-bank-api` |
| `M2M_USER_FORWARD_SECRET` | shared with kalke-auth |
| `CLOUDFLARE_API_TOKEN` | DNS upsert only (`dns-ebank` workflow) |

## 5. DNS

Grey-cloud A record (Caddy terminates TLS on EC2):

```text
A  ebank.kalke.dev  →  54.234.95.66  proxied:false
```

Run the `dns-ebank` workflow, or upsert manually. Auth Caddy must proxy
`ebank.kalke.dev` → `ebank-api:8000` (see kalke-auth `Caddyfile.aws`).

## 6. EC2

Same host as auth/PDE. Deploy job uses the `pde-ec2` self-hosted runner label,
checks out `/home/ubuntu/e-bank-api`, syncs `prod.env`, pulls GHCR, `make aws-up`.

Container: `ebank-api`, network `kalke-auth_default`, `mem_limit: 256m`, 1 uvicorn worker.

Migrations run on container start via `docker-entrypoint.sh` (`alembic upgrade head`).

## 7. Capacity

Auth + PDE + e-bank soft-limit ~1.5–1.7 GB. Prefer **t3.small (2 GB)** + 2G swap.
On a micro, watch `free -h` / OOM and scale if auth or PDE becomes unstable.

## 8. Branch protection

See [kalke BRANCH_PROTECTION.md](https://github.com/kalke/kalke/blob/main/BRANCH_PROTECTION.md).
Required checks: `Lint`, `Tests`, `Docker build`. Restrict push to `kalke` only.
