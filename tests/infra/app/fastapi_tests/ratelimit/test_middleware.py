"""Tests for RateLimitMiddleware."""

import json

import pytest

from appinfra.app.fastapi.ratelimit.middleware import (
    RateLimitMiddleware,
    _make_header_injector,
    _send_429,
)
from appinfra.app.fastapi.ratelimit.token_bucket import TokenBucketLimiter

# =============================================================================
# Helpers
# =============================================================================


class MockApp:
    """Mock ASGI application that returns 200 OK."""

    def __init__(self) -> None:
        self.called = False
        self.scope = None

    async def __call__(self, scope, receive, send) -> None:
        self.called = True
        self.scope = scope
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"ok":true}'})


class MessageCollector:
    """Collects ASGI messages sent via send()."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def __call__(self, message: dict) -> None:
        self.messages.append(message)

    @property
    def status(self) -> int | None:
        """Get the HTTP status code from the response."""
        for msg in self.messages:
            if msg["type"] == "http.response.start":
                return msg["status"]
        return None

    @property
    def headers(self) -> dict[str, str]:
        """Get response headers as a dict."""
        for msg in self.messages:
            if msg["type"] == "http.response.start":
                return {k.decode(): v.decode() for k, v in msg.get("headers", [])}
        return {}

    @property
    def body(self) -> bytes:
        """Get the response body."""
        for msg in self.messages:
            if msg["type"] == "http.response.body":
                return msg.get("body", b"")
        return b""


def _http_scope(path: str = "/test", client_ip: str = "127.0.0.1") -> dict:
    """Create a minimal HTTP ASGI scope."""
    return {
        "type": "http",
        "path": path,
        "client": (client_ip, 12345),
        "headers": [],
    }


# =============================================================================
# Test _send_429
# =============================================================================


@pytest.mark.unit
class TestSend429:
    """Test 429 response generation."""

    @pytest.mark.asyncio
    async def test_sends_429_status(self):
        """Test that 429 status code is sent."""
        collector = MessageCollector()
        await _send_429(collector, {"Retry-After": "60"})
        assert collector.status == 429

    @pytest.mark.asyncio
    async def test_includes_retry_after(self):
        """Test that Retry-After header is included."""
        collector = MessageCollector()
        await _send_429(collector, {"Retry-After": "30"})
        assert collector.headers["retry-after"] == "30"

    @pytest.mark.asyncio
    async def test_json_body(self):
        """Test that body is JSON with detail message."""
        collector = MessageCollector()
        await _send_429(collector, {"Retry-After": "60"})
        body = json.loads(collector.body)
        assert body["detail"] == "Too Many Requests"


# =============================================================================
# Test _make_header_injector
# =============================================================================


@pytest.mark.unit
class TestMakeHeaderInjector:
    """Test header injection wrapper."""

    @pytest.mark.asyncio
    async def test_injects_headers_on_response_start(self):
        """Test that extra headers are added to response start."""
        collector = MessageCollector()
        injector = _make_header_injector(collector, {"X-RateLimit-Limit": "60"})

        await injector(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )

        assert collector.headers["x-ratelimit-limit"] == "60"
        assert collector.headers["content-type"] == "application/json"

    @pytest.mark.asyncio
    async def test_passes_through_body(self):
        """Test that body messages pass through unchanged."""
        collector = MessageCollector()
        injector = _make_header_injector(collector, {"X-Test": "value"})

        await injector({"type": "http.response.body", "body": b"hello"})

        assert collector.body == b"hello"

    @pytest.mark.asyncio
    async def test_handles_tuple_headers(self):
        """Test that tuple (immutable) headers are handled."""
        collector = MessageCollector()
        injector = _make_header_injector(collector, {"X-Test": "value"})

        await injector(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": ((b"content-type", b"text/plain"),),
            }
        )

        assert collector.headers["x-test"] == "value"
        assert collector.headers["content-type"] == "text/plain"


# =============================================================================
# Test RateLimitMiddleware
# =============================================================================


@pytest.mark.unit
class TestRateLimitMiddleware:
    """Test the full ASGI middleware."""

    @pytest.mark.asyncio
    async def test_allows_within_limit(self):
        """Test that requests within limit pass through."""
        app = MockApp()
        limiter = TokenBucketLimiter(rate=10, window=60.0)
        middleware = RateLimitMiddleware(app, limiter=limiter)

        collector = MessageCollector()
        await middleware(_http_scope(), None, collector)

        assert app.called is True
        assert collector.status == 200

    @pytest.mark.asyncio
    async def test_returns_429_over_limit(self):
        """Test that requests over limit get 429."""
        app = MockApp()
        limiter = TokenBucketLimiter(rate=2, window=60.0)
        middleware = RateLimitMiddleware(app, limiter=limiter)
        collector = MessageCollector()

        # Exhaust limit
        for _ in range(2):
            c = MessageCollector()
            await middleware(_http_scope(), None, c)

        # Third request should be denied
        await middleware(_http_scope(), None, collector)
        assert collector.status == 429
        assert "retry-after" in collector.headers

    @pytest.mark.asyncio
    async def test_exempt_paths_bypass(self):
        """Test that exempt paths bypass rate limiting."""
        app = MockApp()
        limiter = TokenBucketLimiter(rate=1, window=60.0)
        middleware = RateLimitMiddleware(app, limiter=limiter, exempt_paths=["/health"])

        # First request exhausts the limit
        c = MessageCollector()
        await middleware(_http_scope(path="/test"), None, c)

        # Health should still pass
        collector = MessageCollector()
        await middleware(_http_scope(path="/health"), None, collector)
        assert collector.status == 200

    @pytest.mark.asyncio
    async def test_non_http_passes_through(self):
        """Test that non-HTTP scopes pass through."""
        app = MockApp()
        limiter = TokenBucketLimiter(rate=1, window=60.0)
        middleware = RateLimitMiddleware(app, limiter=limiter)

        scope = {"type": "websocket", "path": "/ws"}
        collector = MessageCollector()
        await middleware(scope, None, collector)

        assert app.called is True

    @pytest.mark.asyncio
    async def test_options_bypasses_rate_limiting(self):
        """Test that OPTIONS requests bypass rate limiting (CORS preflight)."""
        app = MockApp()
        limiter = TokenBucketLimiter(rate=1, window=60.0)
        middleware = RateLimitMiddleware(app, limiter=limiter)

        # Exhaust limit with a normal request
        c = MessageCollector()
        await middleware(_http_scope(), None, c)

        # OPTIONS should still pass through even though limit is exhausted
        scope = _http_scope()
        scope["method"] = "OPTIONS"
        collector = MessageCollector()
        await middleware(scope, None, collector)
        assert collector.status == 200

    @pytest.mark.asyncio
    async def test_injects_rate_limit_headers(self):
        """Test that rate limit headers are injected on 200 responses."""
        app = MockApp()
        limiter = TokenBucketLimiter(rate=10, window=60.0)
        middleware = RateLimitMiddleware(app, limiter=limiter)

        collector = MessageCollector()
        await middleware(_http_scope(), None, collector)

        assert "x-ratelimit-limit" in collector.headers
        assert collector.headers["x-ratelimit-limit"] == "10"

    @pytest.mark.asyncio
    async def test_per_ip_isolation(self):
        """Test that different IPs have independent limits."""
        app = MockApp()
        limiter = TokenBucketLimiter(rate=1, window=60.0)
        middleware = RateLimitMiddleware(app, limiter=limiter)

        # Exhaust client1
        c = MessageCollector()
        await middleware(_http_scope(client_ip="1.1.1.1"), None, c)
        c = MessageCollector()
        await middleware(_http_scope(client_ip="1.1.1.1"), None, c)
        assert c.status == 429

        # client2 should still be allowed
        collector = MessageCollector()
        await middleware(_http_scope(client_ip="2.2.2.2"), None, collector)
        assert collector.status == 200

    @pytest.mark.asyncio
    async def test_cleanup_triggered(self):
        """Test that cleanup removes stale buckets."""
        app = MockApp()
        limiter = TokenBucketLimiter(rate=1, window=60.0, stale_ttl=0.01)
        middleware = RateLimitMiddleware(app, limiter=limiter, cleanup_interval=0.01)

        # Make a request to create a bucket and exhaust its token
        c = MessageCollector()
        await middleware(_http_scope(client_ip="1.1.1.1"), None, c)
        assert c.status == 200

        # Verify the bucket exists and is exhausted
        assert "1.1.1.1" in limiter._buckets

        import time

        time.sleep(0.02)

        # Next request from different IP triggers cleanup
        c = MessageCollector()
        await middleware(_http_scope(client_ip="2.2.2.2"), None, c)

        # The original client's bucket should have been cleaned up
        assert "1.1.1.1" not in limiter._buckets

        # A new request from the original IP gets a fresh bucket (allowed)
        c = MessageCollector()
        await middleware(_http_scope(client_ip="1.1.1.1"), None, c)
        assert c.status == 200
