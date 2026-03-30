"""Raw ASGI rate limiting middleware.

Uses the ASGI interface directly (not BaseHTTPMiddleware) to avoid known
issues with streaming responses and background tasks.
"""

import json
import time
from collections.abc import Sequence
from typing import Any

from .interface import RateLimiter

# Pre-encoded 429 response body
_429_BODY = json.dumps({"detail": "Too Many Requests"}).encode("utf-8")

# ASGI send/receive type aliases
Receive = Any
Send = Any
Scope = dict[str, Any]


class RateLimitMiddleware:
    """ASGI middleware that enforces rate limits on HTTP requests.

    Extracts a key from each request (via the limiter's extract_key method),
    checks the limiter, and either passes the request through or returns a
    429 response with Retry-After header.

    Non-HTTP scopes (websocket, lifespan) pass through unconditionally.
    Exempt paths bypass rate limiting entirely.
    """

    def __init__(
        self,
        app: Any,
        *,
        limiter: RateLimiter,
        exempt_paths: Sequence[str] = (),
        cleanup_interval: float = 60.0,
    ) -> None:
        """Initialize rate limit middleware.

        Args:
            app: The inner ASGI application.
            limiter: Rate limiter instance implementing the RateLimiter ABC.
            exempt_paths: Paths that bypass rate limiting (e.g., ["/health"]).
            cleanup_interval: Seconds between stale entry cleanup calls.
        """
        self.app = app
        self.limiter = limiter
        self.exempt_paths = frozenset(exempt_paths)
        self._cleanup_interval = cleanup_interval
        self._last_cleanup = time.monotonic()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI entry point."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Skip CORS preflight requests so OPTIONS responses carry CORS
        # headers even when the rate limit is exhausted.
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        self._maybe_cleanup()

        key = self.limiter.extract_key(scope)
        allowed, headers = self.limiter.is_allowed(key)

        if not allowed:
            await _send_429(send, headers)
            return

        # Pass through with rate limit headers injected into the response
        wrapped_send = _make_header_injector(send, headers)
        await self.app(scope, receive, wrapped_send)

    def _maybe_cleanup(self) -> None:
        """Run cleanup if enough time has passed since last cleanup."""
        now = time.monotonic()
        if now - self._last_cleanup >= self._cleanup_interval:
            self._last_cleanup = now
            self.limiter.cleanup()


async def _send_429(send: Send, headers: dict[str, str]) -> None:
    """Send a 429 Too Many Requests response."""
    response_headers: list[tuple[bytes, bytes]] = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(_429_BODY)).encode()),
    ]
    for name, value in headers.items():
        response_headers.append((name.lower().encode(), value.encode()))

    await send(
        {
            "type": "http.response.start",
            "status": 429,
            "headers": response_headers,
        }
    )
    await send({"type": "http.response.body", "body": _429_BODY})


def _make_header_injector(send: Send, headers: dict[str, str]) -> Any:
    """Wrap send to inject rate limit headers into the response."""
    extra_headers = [
        (name.lower().encode(), value.encode()) for name, value in headers.items()
    ]

    async def injecting_send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            existing = message.get("headers", [])
            # headers may be a tuple (immutable) - convert to list
            message["headers"] = list(existing) + extra_headers
        await send(message)

    return injecting_send
