# Sibling repo patches (demo bank)

Apply these on **main** (or a short-lived `feat/...` branch you merge yourself).
This agent can only write **`kalke/e-bank-api`** — already on `main`.

## `kalke-auth` → push `main`

```bash
cd ../kalke-auth
git checkout main && git pull
git am ../e-bank-api/sibling-patches/kalke-auth-demo-bank.patch
# if am fails: git apply ... && git add -A && git commit -m "feat: proxy /v1/bank to e-bank-api"
git push origin main
```

GitHub secrets (deploy-on-main):

| Secret | Example |
|--------|---------|
| `EBANK_BASE_URL` | `https://ebank.kalke.dev` |
| `EBANK_M2M_CLIENT_ID` | `ebank-m2m` |
| `EBANK_M2M_CLIENT_SECRET` | Keycloak `ebank-m2m` secret |
| `EBANK_USER_FORWARD_SECRET` | same as e-bank `M2M_USER_FORWARD_SECRET` |

## `kalke` (portfolio) → push `main`

```bash
cd ../kalke
git checkout main && git pull
git am ../e-bank-api/sibling-patches/kalke-demo-bank-ui.patch
git push origin main
```

## Merge / deploy order

1. **e-bank-api** `main` — done (Cloudflare Containers)
2. **kalke-auth** `main` — you push (EC2)
3. **kalke** `main` — you push (Workers)

Branch naming: use `feat/...` or `fix/...` only if you need a temporary branch — not `cursor/`.
