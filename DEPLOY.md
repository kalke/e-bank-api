# Deploy e-bank-api (ebank.kalke.dev)

Cloudflare Containers + Neon Postgres + Upstash Redis (free data plane).

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

## 3. OIDC

Issuer: `https://auth.kalke.dev/realms/kalke`  
Audience: `e-bank-api`

Deploy [kalke-auth](https://github.com/kalke/kalke-auth) first.

## 4. GitHub secrets (`kalke/e-bank-api`)

| Secret | Value |
|---|---|
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account id |
| `DATABASE_URL` | `postgresql+asyncpg://…` |
| `REDIS_URL` | `rediss://…` |
| `OIDC_ISSUER` | `https://auth.kalke.dev/realms/kalke` |
| `OIDC_AUDIENCE` | `e-bank-api` |

## 5. Deploy

Push to `main` after PR merge. Manual:

```bash
cd worker && npm ci && cd ..
npx wrangler secret put DATABASE_URL
npx wrangler secret put REDIS_URL
npx wrangler secret put OIDC_ISSUER
npx wrangler secret put OIDC_AUDIENCE
npm --prefix worker run deploy
```

## 6. Branch protection

Settings → Branches → `main`:

- Require PR
- Require checks: `Lint`, `Tests`, `Docker build`
- Restrict pushes to `kalke` only
