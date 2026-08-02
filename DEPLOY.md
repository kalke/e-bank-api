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

## 3. Auth (OIDC + PAT)

Issuer: `https://auth.kalke.dev/realms/kalke`  
Audience: `e-bank-api`

All mutating/read API routes require `Authorization: Bearer <jwt|kalke_…>` with
permission `admin` **and** an email in `ADMIN_EMAILS` (default owner email).
PATs are validated via kalke-auth introspect (same `INTROSPECT_SECRET` as auth).
Public surface is `GET /health` only.

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
| `INTROSPECT_SECRET` | same value as kalke-auth |

## 5. Deploy

Push to `main` after PR merge. Manual:

```bash
npm ci
npx wrangler secret put DATABASE_URL
npx wrangler secret put REDIS_URL
npx wrangler secret put OIDC_ISSUER
npx wrangler secret put OIDC_AUDIENCE
npx wrangler secret put INTROSPECT_SECRET
npx wrangler deploy
```

## 6. Branch protection

See [kalke BRANCH_PROTECTION.md](https://github.com/kalke/kalke/blob/main/BRANCH_PROTECTION.md). Required checks: `Lint`, `Tests`, `Docker build`. Restrict push to `kalke` only.
