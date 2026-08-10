"""BrasilAPI CEP lookup (server-side)."""

from __future__ import annotations

import httpx

from app.core.logger import get_logger
from app.domain.validation import validate_cep
from app.errors import OnboardingError

logger = get_logger(__name__)

BRASIL_API_CEP = "https://brasilapi.com.br/api/cep/v1/{cep}"


class CepLookup:
    def __init__(self, *, timeout: float = 8.0) -> None:
        self._timeout = timeout

    async def lookup(self, cep: str) -> dict[str, str]:
        cleaned = validate_cep(cep)
        url = BRASIL_API_CEP.format(cep=cleaned)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url)
        except httpx.HTTPError as exc:
            logger.warning("cep_lookup_failed", cep=cleaned, error=str(exc))
            raise OnboardingError("CEP lookup unavailable") from exc

        if resp.status_code == 404:
            raise OnboardingError("CEP not found")
        if resp.status_code >= 400:
            raise OnboardingError("CEP lookup failed")

        data = resp.json()
        return {
            "cep": cleaned,
            "street": str(data.get("street") or ""),
            "neighborhood": str(data.get("neighborhood") or ""),
            "city": str(data.get("city") or ""),
            "state": str(data.get("state") or ""),
        }
