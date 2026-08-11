"""Load application secrets from AWS Secrets Manager into the process env."""

from __future__ import annotations

import json
import os

_LOADED_FLAG = "KALKE_SECRETS_LOADED"


def load_secrets_into_env(
    *, secret_id: str | None = None, region: str | None = None
) -> bool:
    """
    If SECRET_ID (or secret_id) is set, fetch a JSON secret and merge keys into
    os.environ without overwriting non-empty values already present.
    No-op when SECRET_ID is unset or KALKE_SECRETS_LOADED is set.
    Returns True when a secret was loaded.
    """
    if (os.getenv(_LOADED_FLAG) or "").strip():
        return False
    sid = (secret_id or os.getenv("SECRET_ID") or "").strip()
    if not sid:
        return False
    region_name = (
        region
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "us-east-1"
    ).strip()
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("boto3 is required when SECRET_ID is set") from exc

    client = boto3.client("secretsmanager", region_name=region_name)
    try:
        resp = client.get_secret_value(SecretId=sid)
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(f"failed to load secret {sid}: {exc}") from exc

    raw = resp.get("SecretString") or ""
    if not raw and resp.get("SecretBinary"):
        raw = resp["SecretBinary"].decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError(f"secret {sid} must be a JSON object")
    for key, value in data.items():
        k = str(key)
        if k in os.environ and os.environ[k] != "":
            continue
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            os.environ[k] = json.dumps(value)
        else:
            os.environ[k] = str(value)
    os.environ[_LOADED_FLAG] = "1"
    return True
