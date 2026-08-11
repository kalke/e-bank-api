"""S3 persistence for immutable bank receipt PDFs."""

from __future__ import annotations

from botocore.client import BaseClient
from botocore.exceptions import ClientError

from app.core.config import get_settings


def receipt_key(account_id: str, tx_public_id: str) -> str:
    return f"receipts/{account_id}/{tx_public_id}.pdf"


class BankPDFStore:
    """Get/put receipt PDF bytes in S3 when a bucket is configured."""

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
        self._client: BaseClient | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.bucket)

    def _s3(self) -> BaseClient:
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
