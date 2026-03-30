"""Token bucket rate limiter.

O(1) per-request rate limiting with configurable burst support.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .interface import RateLimiter
from .parsing import parse_rate


@dataclass
class _Bucket:
    """Per-key token bucket state."""

    tokens: float
    last_refill: float


def _extract_ip_from_scope(scope: dict[str, Any]) -> str:
    """Extract client IP from ASGI scope, using direct connection."""
    client = scope.get("client")
    if client:
        return str(client[0])
    return "unknown"


def _extract_ip_with_header(scope: dict[str, Any], header_name: bytes) -> str:
    """Extract client IP from a proxy header, falling back to direct connection.

    For X-Forwarded-For style headers with comma-separated IPs, uses the
    leftmost (original client) value.
    """
    for name, value in scope.get("headers", []):
        if name == header_name:
            # Take leftmost IP for X-Forwarded-For style headers
            decoded: str = value.decode("latin-1").split(",")[0].strip()
            return decoded
    return _extract_ip_from_scope(scope)


class TokenBucketLimiter(RateLimiter):
    """Per-key token bucket rate limiter.

    Each unique key gets its own bucket that refills at a steady rate.
    Burst capacity allows short spikes above the sustained rate.

    Thread-safe via threading.Lock. All operations are O(1).

    Example:
        limiter = TokenBucketLimiter(rate="60/min", burst=10)
        allowed, headers = limiter.is_allowed("192.168.1.1")
    """

    def __init__(
        self,
        rate: int | str,
        window: float = 60.0,
        burst: int | None = None,
        key_func: Callable[[dict[str, Any]], str] | None = None,
        proxy_header: str | None = None,
        stale_ttl: float | None = None,
    ) -> None:
        """Initialize token bucket rate limiter.

        Args:
            rate: Max requests per window. Either an int (requires window param)
                or a string like "60/min", "1000/hour".
            window: Window duration in seconds. Ignored when rate is a string.
            burst: Max tokens (burst capacity). Defaults to the rate count,
                meaning no extra burst beyond the sustained rate.
            key_func: Custom key extraction function. Takes an ASGI scope dict,
                returns a string key. Overrides proxy_header if both are set.
            proxy_header: HTTP header name containing the real client IP
                (e.g., "X-Forwarded-For", "CF-Connecting-IP"). Not trusted by
                default - only set this if your server is behind a proxy.
            stale_ttl: Seconds before an idle bucket is eligible for cleanup.
                Defaults to window * 2.

        Raises:
            ValueError: If rate or burst values are invalid.
        """
        if isinstance(rate, str):
            self._max_requests, self._window = parse_rate(rate)
        else:
            if rate <= 0:
                raise ValueError(f"Rate must be positive, got: {rate}")
            self._max_requests = rate
            self._window = window

        if burst is not None and burst <= 0:
            raise ValueError(f"Burst must be positive, got: {burst}")
        self._burst = burst if burst is not None else self._max_requests

        self._refill_rate = self._max_requests / self._window  # tokens per second
        self._stale_ttl = stale_ttl if stale_ttl is not None else self._window * 2

        self._key_func = key_func
        self._proxy_header = (
            proxy_header.lower().encode("latin-1") if proxy_header else None
        )

        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    @property
    def max_requests(self) -> int:
        """Maximum requests per window (the sustained rate)."""
        return self._max_requests

    @property
    def window(self) -> float:
        """Window duration in seconds."""
        return self._window

    @property
    def burst(self) -> int:
        """Maximum burst capacity (bucket size)."""
        return self._burst

    def is_allowed(self, key: str) -> tuple[bool, dict[str, str]]:
        """Check if a request is allowed and consume a token if so."""
        now = time.monotonic()
        with self._lock:
            bucket = self._get_or_create_bucket(key, now)
            self._refill(bucket, now)

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True, self._build_headers(bucket)

            # Denied - calculate retry delay
            headers = self._build_headers(bucket)
            tokens_needed = 1.0 - bucket.tokens
            retry_after = tokens_needed / self._refill_rate
            headers["Retry-After"] = str(int(retry_after) + 1)
            return False, headers

    def extract_key(self, scope: dict[str, Any]) -> str:
        """Extract rate limit key from ASGI scope."""
        if self._key_func is not None:
            return self._key_func(scope)
        if self._proxy_header is not None:
            return _extract_ip_with_header(scope, self._proxy_header)
        return _extract_ip_from_scope(scope)

    def cleanup(self) -> None:
        """Remove buckets that have been idle longer than stale_ttl."""
        now = time.monotonic()
        with self._lock:
            stale_keys = [
                key
                for key, bucket in self._buckets.items()
                if now - bucket.last_refill > self._stale_ttl
            ]
            for key in stale_keys:
                del self._buckets[key]

    def _get_or_create_bucket(self, key: str, now: float) -> _Bucket:
        """Get existing bucket or create a new one at full capacity."""
        if key not in self._buckets:
            self._buckets[key] = _Bucket(tokens=float(self._burst), last_refill=now)
        return self._buckets[key]

    def _refill(self, bucket: _Bucket, now: float) -> None:
        """Refill tokens based on elapsed time since last refill."""
        elapsed = now - bucket.last_refill
        if elapsed > 0:
            bucket.tokens = min(
                self._burst, bucket.tokens + elapsed * self._refill_rate
            )
            bucket.last_refill = now

    def _build_headers(self, bucket: _Bucket) -> dict[str, str]:
        """Build rate limit response headers."""
        return {
            "X-RateLimit-Limit": str(self._max_requests),
            "X-RateLimit-Remaining": str(max(0, int(bucket.tokens))),
        }

    def __getstate__(self) -> dict[str, Any]:
        """Pickle support: strip lock and buckets for subprocess mode."""
        state = self.__dict__.copy()
        del state["_lock"]
        state["_buckets"] = {}
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Pickle support: recreate lock in new process."""
        self.__dict__.update(state)
        self._lock = threading.Lock()
