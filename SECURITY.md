# Security

## Reporting

Email security concerns to the repository owner. Do not open public issues for
active exploits or leaked credentials.

## Practices

- Secrets live only in gitignored env files and CI/host secret stores — never in the repo.
- Demo bank routes require a valid Bearer token (OIDC JWT) or a trusted BFF M2M
  forward (`X-Kalke-Forward-Secret` + `X-Kalke-User-Sub`).
- Account access is ownership-scoped (`owner_subject`). Cross-user access is denied.
- Mutating demo routes can be rate-limited per subject (Redis, fail-closed when enabled).
- Raw KYC/document uploads are **not** stored in this API — only PDE extraction
  references and redacted metadata.
- This API is a **DEMO**: virtual funds only. Welcome grant is play money.

## CI scanners

Pull requests and `main` runs include:

- `ruff` lint
- pytest
- `gitleaks` (secret scan)
- Docker build
- Deploy to Cloudflare Containers on `main` (after checks)

## Scope notes

`DATABASE_URL`, `REDIS_URL`, OIDC settings, and `M2M_USER_FORWARD_SECRET` must
never be committed.
