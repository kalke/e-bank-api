from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.logger import get_logger, sanitize_sensitive_fields

logger = get_logger("http.client")


class LoggedHttpClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client()
        self._owns_client = client is None

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        safe_url = self._safe_url(url)
        start = time.perf_counter()

        try:
            response = self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.error(
                "external_request_failed",
                method=method.upper(),
                url=safe_url,
                duration_ms=duration_ms,
                error=str(exc),
                exc_info=True,
            )
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        payload = sanitize_sensitive_fields(
            {
                "method": method.upper(),
                "url": safe_url,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            }
        )

        if response.status_code >= 500:
            logger.error("external_request", **payload)
        elif response.status_code >= 400:
            logger.warning("external_request", **payload)
        else:
            logger.info("external_request", **payload)

        return response

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> LoggedHttpClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @staticmethod
    def _safe_url(url: str) -> str:
        parsed = urlparse(url)
        if not parsed.query:
            return url
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?[REDACTED]"
