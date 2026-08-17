#!/usr/bin/env bash
# Dump Neon (or any source URL) into Docker Postgres on this EC2 (ebank-db).
#
# Usage:
#   bash scripts/migrate-from-neon.sh
#   bash scripts/migrate-from-neon.sh --if-empty
#   bash scripts/migrate-from-neon.sh --force
#   bash scripts/migrate-from-neon.sh --ensure-password
set -euo pipefail

IF_EMPTY=0
FORCE=0
ENSURE_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --if-empty) IF_EMPTY=1 ;;
    --force) FORCE=1 ;;
    --ensure-password) ENSURE_ONLY=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f prod.env ]]; then
  echo "prod.env missing in ${ROOT}" >&2
  exit 1
fi

ensure_postgres_password() {
  if grep -qE '^POSTGRES_PASSWORD=' prod.env; then
    return 0
  fi
  local pw
  pw="$(openssl rand -hex 16)"
  printf "\nPOSTGRES_PASSWORD='%s'\n" "$pw" >> prod.env
  echo "generated POSTGRES_PASSWORD and appended to prod.env"
}

ensure_postgres_password
if [[ "$ENSURE_ONLY" == 1 ]]; then
  exit 0
fi

COMPOSE=(docker compose -f docker-compose.aws.yml --env-file prod.env)
PG_USER="$(awk -F= '/^POSTGRES_USER=/{sub(/^[^=]*=/,""); gsub(/^['\''"]+|['\''"]+$/,""); print; exit}' prod.env)"
PG_DB="$(awk -F= '/^POSTGRES_DB=/{sub(/^[^=]*=/,""); gsub(/^['\''"]+|['\''"]+$/,""); print; exit}' prod.env)"
PG_USER="${PG_USER:-ebank}"
PG_DB="${PG_DB:-ebank}"

echo "==> Starting local ebank-db"
"${COMPOSE[@]}" up -d ebank-db --wait

local_table_count() {
  "${COMPOSE[@]}" exec -T ebank-db \
    psql -U "$PG_USER" -d "$PG_DB" -Atc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'"
}

count="$(local_table_count)"
if [[ "$count" -gt 0 && "$FORCE" != 1 ]]; then
  if [[ "$IF_EMPTY" == 1 ]]; then
    echo "local postgres already has ${count} public tables; skip migrate"
    exit 0
  fi
  echo "refusing to overwrite local postgres (${count} tables). Pass --force to replace." >&2
  exit 1
fi

REGION="${AWS_REGION:-us-east-1}"
SECRET_ID="${EBANK_SECRET_ID:-kalke/e-bank-api/prod}"
if grep -qE '^AWS_REGION=' prod.env; then
  REGION="$(awk -F= '/^AWS_REGION=/{sub(/^[^=]*=/,""); gsub(/^['\''"]+|['\''"]+$/,""); print; exit}' prod.env)"
  REGION="${REGION:-us-east-1}"
fi
if grep -qE '^SECRET_ID=' prod.env; then
  SECRET_ID="$(awk -F= '/^SECRET_ID=/{sub(/^[^=]*=/,""); gsub(/^['\''"]+|['\''"]+$/,""); print; exit}' prod.env)"
fi

DUMP_DIR="$(mktemp -d /tmp/ebank-neon-migrate.XXXXXX)"
chmod 700 "$DUMP_DIR"
cleanup() { rm -rf "$DUMP_DIR"; }
trap cleanup EXIT

echo "==> Resolving Neon source URL"
export AWS_REGION="$REGION"
export SECRET_ID
export DUMP_DIR
export IF_EMPTY
python3 - <<'PY'
import json, os, subprocess, sys
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

def parse_env_file(path):
    vals = {}
    try:
        text = open(path).read()
    except OSError:
        return vals
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        vals[k.strip()] = v.strip().strip("'").strip('"')
    return vals

def sm_blob():
    sid = os.environ.get("SECRET_ID") or ""
    region = os.environ.get("AWS_REGION") or "us-east-1"
    if not sid:
        return {}
    p = subprocess.run(
        [
            "aws", "secretsmanager", "get-secret-value",
            "--region", region, "--secret-id", sid,
            "--query", "SecretString", "--output", "text",
        ],
        capture_output=True, text=True,
    )
    if p.returncode != 0 or not p.stdout.strip():
        return {}
    try:
        data = json.loads(p.stdout)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}

def to_libpq(url: str) -> str:
    # SQLAlchemy async URL -> libpq
    u = url.replace("postgresql+asyncpg://", "postgres://", 1)
    u = u.replace("postgresql+psycopg://", "postgres://", 1)
    u = u.replace("postgresql://", "postgres://", 1)
    p = urlparse(u)
    host = (p.hostname or "").replace("-pooler", "")
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)]
    if host.endswith("neon.tech") and not any(k.lower() == "sslmode" for k, _ in q):
        q.append(("sslmode", "require"))
    auth = ""
    if p.username is not None:
        auth = p.username
        if p.password is not None:
            auth += ":" + p.password
        auth += "@"
    port = f":{p.port}" if p.port else ""
    netloc = f"{auth}{host}{port}"
    return urlunparse(("postgres", netloc, p.path, p.params, urlencode(q), p.fragment))

file_vals = parse_env_file("prod.env")
data = sm_blob()
candidates = [
    os.environ.get("NEON_DATABASE_URL") or "",
    data.get("NEON_DATABASE_URL") or "",
    os.environ.get("DATABASE_URL") or "",
    data.get("DATABASE_URL") or "",
    file_vals.get("NEON_DATABASE_URL") or "",
    file_vals.get("DATABASE_URL") or "",
]
url = ""
for c in candidates:
    c = (c or "").strip()
    if not c or "://ebank-db:5432" in c or "://postgres:5432" in c:
        continue
    if "neon.tech" in c or "postgres" in c.split("+")[0].split(":")[0]:
        url = c
        break

if not url:
    if os.environ.get("IF_EMPTY") == "1":
        print("no Neon source URL; skip (--if-empty)")
        sys.exit(0)
    print("no Neon/source DATABASE_URL found in env or Secrets Manager", file=sys.stderr)
    sys.exit(1)

direct = to_libpq(url)
if "://ebank-db:5432" in direct or "://postgres:5432" in direct:
    print("source URL already points at local Docker postgres; nothing to dump", file=sys.stderr)
    sys.exit(0)

open(os.path.join(os.environ["DUMP_DIR"], "source.url"), "w").write(direct)
print("resolved source host")
PY

if [[ ! -s "${DUMP_DIR}/source.url" ]]; then
  echo "no dump source (already on local Docker postgres, or URL unresolved)"
  exit 0
fi

echo "==> Dumping source database"
docker run --rm \
  -v "${DUMP_DIR}:/dump" \
  postgres:18-alpine \
  sh -c 'pg_dump --dbname="$(cat /dump/source.url)" --format=custom --no-owner --no-acl --file=/dump/neon.dump'

if [[ ! -s "${DUMP_DIR}/neon.dump" ]]; then
  echo "pg_dump produced an empty dump" >&2
  exit 1
fi

if [[ "$count" -gt 0 && "$FORCE" == 1 ]]; then
  echo "==> Dropping public schema (--force)"
  "${COMPOSE[@]}" exec -T ebank-db psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 <<SQL
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO CURRENT_USER;
GRANT ALL ON SCHEMA public TO public;
SQL
fi

echo "==> Restoring into local postgres"
docker run --rm \
  --network kalke-auth_default \
  -v "${DUMP_DIR}:/dump" \
  -e PGPASSWORD="$(awk -F= '/^POSTGRES_PASSWORD=/{sub(/^[^=]*=/,""); gsub(/^['\''"]+|['\''"]+$/,""); print; exit}' prod.env)" \
  postgres:18-alpine \
  pg_restore --host=ebank-db --username="$PG_USER" --dbname="$PG_DB" \
    --no-owner --no-acl --verbose /dump/neon.dump || true

after="$(local_table_count)"
if [[ "$after" -lt 1 ]]; then
  echo "restore produced no public tables" >&2
  exit 1
fi

echo "==> Verifying"
"${COMPOSE[@]}" exec -T ebank-db psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 <<'SQL'
SELECT to_regclass('public.accounts') AS accounts,
       to_regclass('public.alembic_version') AS alembic_version;
SELECT count(*) AS public_tables
FROM information_schema.tables
WHERE table_schema='public' AND table_type='BASE TABLE';
SQL

echo "migrated ${after} tables into local postgres"
