"""In-memory per-IP rate limiting for public and auth endpoints."""
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core import config

_AUTH_PATHS = {"/api/auth/login", "/api/auth/register"}
_SENSITIVE_PREFIXES = (
    "/api/auth/",
    "/api/dev-collab/github/webhook",
    "/api/incidents/ingest-metrics",
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    _hits: dict[str, deque[float]] = defaultdict(deque)

    def __init__(self, app):
        super().__init__(app)

    def _client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    def _limit_for_path(self, path: str) -> int | None:
        if not config.settings.RATE_LIMIT_ENABLED:
            return None
        if path in _AUTH_PATHS:
            return config.settings.RATE_LIMIT_AUTH_PER_MINUTE
        if path.startswith(_SENSITIVE_PREFIXES):
            return config.settings.RATE_LIMIT_API_PER_MINUTE
        return None

    def _is_limited(self, key: str, limit: int) -> bool:
        now = time.time()
        window_start = now - 60.0
        bucket = RateLimitMiddleware._hits[key]
        while bucket and bucket[0] < window_start:
            bucket.popleft()
        if len(bucket) >= limit:
            return True
        bucket.append(now)
        return False

    async def dispatch(self, request: Request, call_next):
        limit = self._limit_for_path(request.url.path)
        if limit is None:
            return await call_next(request)

        ip = self._client_ip(request)
        key = f"{ip}:{request.url.path}"
        if self._is_limited(key, limit):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again in a minute."},
            )
        return await call_next(request)
