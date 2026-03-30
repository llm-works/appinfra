"""Rate limiter interface.

Defines the ABC that all rate limiter implementations must satisfy.
"""

from abc import ABC, abstractmethod
from typing import Any


class RateLimiter(ABC):
    """Abstract base class for HTTP rate limiters.

    Implementations control both the rate limiting algorithm (token bucket,
    sliding window, etc.) and the key extraction strategy (per-IP, global,
    custom).

    All methods are synchronous. In-memory rate limiting is pure math that
    completes in microseconds, so async is unnecessary. Thread safety is
    the implementation's responsibility.

    Note:
        This is the HTTP/ASGI rate limiter interface, distinct from
        ``appinfra.rate_limit.RateLimiter`` which is a general-purpose
        blocking rate limiter for controlling operation frequency.
    """

    @abstractmethod
    def is_allowed(self, key: str) -> tuple[bool, dict[str, str]]:
        """Check whether a request identified by key is allowed.

        Args:
            key: Rate limit key (e.g., client IP, API key, or "global").

        Returns:
            Tuple of (allowed, headers).
            - allowed: True if the request should proceed, False if rate limited.
            - headers: Dict of HTTP headers to include in the response.
              Must include "Retry-After" (seconds) when allowed is False.
              May include X-RateLimit-Limit, X-RateLimit-Remaining,
              X-RateLimit-Reset on allowed responses.
        """
        ...  # pragma: no cover

    @abstractmethod
    def extract_key(self, scope: dict[str, Any]) -> str:
        """Extract the rate limit key from an ASGI scope.

        The scope is a raw ASGI scope dict (not a Starlette Request), because
        the middleware operates at the ASGI level without constructing a
        Request object.

        Args:
            scope: ASGI connection scope. Key fields:
                - scope["client"]: tuple of (host, port) or None
                - scope["headers"]: list of (name, value) byte tuples

        Returns:
            Rate limit key string.
        """
        ...  # pragma: no cover

    def cleanup(self) -> None:
        """Remove stale entries to reclaim memory.

        Called periodically by the middleware. Default is a no-op, suitable
        for limiters that don't track per-key state.
        """
