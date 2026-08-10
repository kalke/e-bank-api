# Deploy e-bank-api (ebank.kalke.dev)

**DEMO ONLY** — virtual portfolio bank (Cloudflare Containers + Neon Postgres + Upstash Redis).

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
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account id |
| `DATABASE_URL` | `postgresql+asyncpg://…` |
| `REDIS_URL` | `rediss://…` |
| `OIDC_ISSUER` | `https://auth.kalke.dev/realms/kalke` |
| `OIDC_AUDIENCE` | `e-bank-api` |
| `M2M_USER_FORWARD_SECRET` | shared with kalke-auth |

## 5. DNS

`ebank.kalke.dev` is declared as a Wrangler custom domain. Confirm it is attached
on the Worker in the Cloudflare dashboard (proxied / orange cloud). No separate
UI hostname is required — the playground lives on `kalke.dev`.

## 6. Deploy

Push/merge to `main` runs CI then deploy. Manual:

```bash
npm ci
npx wrangler secret put DATABASE_URL
npx wrangler secret put REDIS_URL
npx wrangler secret put OIDC_ISSUER
npx wrangler secret put OIDC_AUDIENCE
npx wrangler secret put M2M_USER_FORWARD_SECRET
npm run deploy
```

Migrations run on container start via `docker-entrypoint.sh` (`alembic upgrade head`).

## 7. EC2 note

Auth BFF and PDE stay on the existing EC2 micro. This API stays on Cloudflare
Containers — no EC2 resize required for the demo bank.

## 8. Branch protection

See [kalke BRANCH_PROTECTION.md](https://github.com/kalke/kalke/blob/main/BRANCH_PROTECTION.md).
Required checks: `Lint`, `Tests`, `Docker build`. Restrict push to `kalke` only.
