# Sibling repo patches (demo bank)

This Cloud Agent only has write access to **`kalke/e-bank-api`**. The
`kalke-auth` and `kalke` changes are complete and exported here as patches
you can apply and push as yourself.

## Apply `kalke-auth`

```bash
cd ../kalke-auth
git checkout -b cursor/demo-bank-bff-1193
git am ../e-bank-api/sibling-patches/kalke-auth-demo-bank.patch
# or: git apply ../e-bank-api/sibling-patches/kalke-auth-demo-bank.patch && git add -A && git commit
git push -u origin cursor/demo-bank-bff-1193
```

What it adds:

- Cookie BFF routes `/v1/bank/*` → `https://ebank.kalke.dev` with M2M + user-forward
- `EBANK_*` config / `prod.env` sync on deploy (same pattern as PDE_*)
- Every signed-in user gets `bank:demo` for the playground

### GitHub secrets to set on `kalke-auth` (for deploy-on-main)

| Secret | Example |
|--------|---------|
| `EBANK_BASE_URL` | `https://ebank.kalke.dev` |
| `EBANK_M2M_CLIENT_ID` | `ebank-m2m` |
| `EBANK_M2M_CLIENT_SECRET` | from Keycloak `ebank-m2m` |
| `EBANK_USER_FORWARD_SECRET` | shared with e-bank `M2M_USER_FORWARD_SECRET` |

## Apply `kalke` (portfolio)

```bash
cd ../kalke
git checkout -b cursor/demo-bank-ui-1193
git am ../e-bank-api/sibling-patches/kalke-demo-bank-ui.patch
git push -u origin cursor/demo-bank-ui-1193
```

What it adds:

- `/playground/bank`, `/onboarding`, `/transfer`, `/activity`
- Skippable due diligence (optional PDE uploads)
- DEMO badge + `$10,000` welcome bootstrap via BFF

## Merge order (triggers existing CI/CD)

1. Merge **e-bank-api** `cursor/demo-bank-api-1193` → `main` (Cloudflare Containers)
2. Merge **kalke-auth** branch → `main` (EC2 self-hosted deploy)
3. Merge **kalke** branch → `main` (Workers deploy)

## One-time ops checklist

- [ ] Confirm Cloudflare custom domain `ebank.kalke.dev` (proxied)
- [ ] Set `M2M_USER_FORWARD_SECRET` on e-bank-api GitHub secrets / wrangler
- [ ] Set matching `EBANK_USER_FORWARD_SECRET` (+ other `EBANK_*`) on kalke-auth
- [ ] No EC2 resize required (bank stays on Cloudflare Containers)
- [ ] No new DNS for bank UI (lives under `kalke.dev/playground/bank`)

## DEMO reminder

Virtual funds only. Welcome grant is play money. Due diligence is optional.
