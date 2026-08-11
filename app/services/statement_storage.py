"""S3 persistence for bank receipt and statement PDFs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.core.logger import get_logger

logger = get_logger(__name__)

_SCHEMA_VERSION = "1"


def receipt_key(account_id: str, tx_public_id: str) -> str:
    return f"receipts/{account_id}/{tx_public_id}.pdf"


def statement_key(account_id: str, filters: dict[str, Any]) -> str:
    payload = {"v": _SCHEMA_VERSION, "account_id": account_id, **filters}
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"statements/{account_id}/{digest}.pdf"


class StatementPDFStore:
    """Get-or-create PDF bytes in S3 when a bucket is configured."""

    def __init__(
        self,
        *,
        bucket: str | None = None,
        region: str | None = None,
    ) -> None:
        settings = get_settings()
        raw_bucket = bucket if bucket is not None else settings.s3_bank_pdf_bucket
        raw_region = region if region is not None else settings.aws_region
        self.bucket = (raw_bucket or "").strip()
        self.region = (raw_region or "").strip() or "us-east-1"
        self._client: Any | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.bucket)

    def _s3(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("s3", region_name=self.region)
        return self._client

    def get(self, key: str) -> bytes | None:
        """Return object bytes, None on miss. Raises on unexpected S3 errors."""
        if not self.enabled:
            return None
        try:
            obj = self._s3().get_object(Bucket=self.bucket, Key=key)
            return obj["Body"].read()
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise

    def put(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str = "application/pdf",
    ) -> None:
        if not self.enabled:
            return
        self._s3().put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )


def get_or_create_pdf(
    *,
    key: str,
    generate: Callable[[], bytes],
    event_generated: str,
    event_hit: str,
    extra: dict[str, Any] | None = None,
    store: StatementPDFStore | None = None,
) -> bytes:
    """Fetch from S3 or generate+store. Domain audit events are owned here."""
    store = store or StatementPDFStore()
    fields = dict(extra or {})
    fields["s3_key"] = key
    if store.enabled:
        try:
            cached = store.get(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "bank.pdf.get_failed",
                outcome="error",
                error=str(exc),
                **fields,
            )
            cached = None
        else:
            if cached is not None:
                logger.info(event_hit, outcome="ok", **fields)
                return cached
    pdf = generate()
    if store.enabled:
        try:
            store.put(key, pdf)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "bank.pdf.put_failed",
                outcome="error",
                error=str(exc),
                **fields,
            )
    logger.info(event_generated, outcome="ok", **fields)
    return pdf
