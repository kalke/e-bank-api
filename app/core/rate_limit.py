from __future__ import annotations

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.logger import get_logger

logger = get_logger(__name__)


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__("rate limit exceeded")


class RateLimiter:
    """Fixed-window counter per subject. Fail-closed when Redis errors."""

    def __init__(
        self,
        redis_client: Redis,
        *,
        limit: int = 60,
        window_seconds: int = 60,
    ) -> None:
        self._redis = redis_client
        self._limit = limit
        self._window = window_seconds

    async def allow(self, subject: str) -> tuple[bool, int, int]:
        key = f"ratelimit:bank:{subject}"
        try:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, self._window)
            ttl = await self._redis.ttl(key)
            if ttl < 0:
                ttl = self._window
            remaining = max(0, self._limit - int(count))
            allowed = int(count) <= self._limit
            return allowed, remaining, int(ttl)
        except RedisError as exc:
            logger.error("rate_limit_redis_error", error=str(exc), exc_info=True)
            raise RateLimitExceeded(self._window) from exc
