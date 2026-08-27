# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Integration tests for rate limiting with ServerBuilder."""

from unittest.mock import Mock

import pytest

from appinfra.app.fastapi.builder.server import ServerBuilder
from appinfra.app.fastapi.ratelimit import TokenBucketLimiter


@pytest.mark.unit
class TestServerBuilderIntegration:
    """Test with_rate_limiter on ServerBuilder."""

    def test_with_rate_limiter_stores_definition(self):
        """Test that with_rate_limiter appends to list."""
        lg = Mock()
        limiter = TokenBucketLimiter(rate="60/min")
        builder = ServerBuilder(lg, "test").with_rate_limiter(
            limiter, exempt_paths=["/health"]
        )

        assert len(builder._rate_limiters) == 1
        assert builder._rate_limiters[0].limiter is limiter
        assert builder._rate_limiters[0].exempt_paths == ["/health"]

    def test_with_rate_limiter_chaining(self):
        """Test that with_rate_limiter returns self for chaining."""
        lg = Mock()
        limiter = TokenBucketLimiter(rate="60/min")
        result = ServerBuilder(lg, "test").with_rate_limiter(limiter)

        assert isinstance(result, ServerBuilder)

    def test_with_rate_limiter_default_exempt_paths(self):
        """Test that exempt_paths defaults to empty list."""
        lg = Mock()
        limiter = TokenBucketLimiter(rate="60/min")
        builder = ServerBuilder(lg, "test").with_rate_limiter(limiter)

        assert len(builder._rate_limiters) == 1
        assert builder._rate_limiters[0].exempt_paths == []

    def test_with_rate_limiter_custom_cleanup_interval(self):
        """Test custom cleanup interval."""
        lg = Mock()
        limiter = TokenBucketLimiter(rate="60/min")
        builder = ServerBuilder(lg, "test").with_rate_limiter(
            limiter, cleanup_interval=120.0
        )

        assert len(builder._rate_limiters) == 1
        assert builder._rate_limiters[0].cleanup_interval == 120.0

    def test_multiple_rate_limiters(self):
        """Test chaining multiple rate limiters."""
        lg = Mock()
        global_limiter = TokenBucketLimiter(
            rate="1000/min", key_func=lambda s: "global"
        )
        per_ip_limiter = TokenBucketLimiter(rate="60/min")

        builder = (
            ServerBuilder(lg, "test")
            .with_rate_limiter(global_limiter, exempt_paths=["/health"])
            .with_rate_limiter(per_ip_limiter, exempt_paths=["/health"])
        )

        assert len(builder._rate_limiters) == 2
        assert builder._rate_limiters[0].limiter is global_limiter
        assert builder._rate_limiters[1].limiter is per_ip_limiter


@pytest.mark.integration
class TestServerBuilderBuild:
    """Test that rate limiting is wired into the built server."""

    def test_build_with_rate_limiter(self):
        """Test that server builds successfully with rate limiter."""
        lg = Mock()
        limiter = TokenBucketLimiter(rate="60/min")

        async def health():
            return {"status": "ok"}

        server = (
            ServerBuilder(lg, "test")
            .with_rate_limiter(limiter, exempt_paths=["/health"])
            .routes.with_route("/health", health)
            .done()
            .build()
        )

        assert server is not None
        # Access the app to trigger build
        app = server.app
        assert app is not None

    def test_build_without_rate_limiter(self):
        """Test that server builds fine without rate limiter."""
        lg = Mock()

        async def health():
            return {"status": "ok"}

        server = (
            ServerBuilder(lg, "test")
            .routes.with_route("/health", health)
            .done()
            .build()
        )

        assert server is not None


@pytest.mark.integration
@pytest.mark.asyncio
class TestHttpIntegration:
    """Test rate limiting via HTTP requests using httpx."""

    async def test_rate_limiting_end_to_end(self):
        """Test full request cycle with rate limiting."""
        from httpx import ASGITransport, AsyncClient

        lg = Mock()
        limiter = TokenBucketLimiter(rate=3, window=60.0)

        async def echo():
            return {"message": "hello"}

        async def health():
            return {"status": "ok"}

        server = (
            ServerBuilder(lg, "test")
            .with_rate_limiter(limiter, exempt_paths=["/health"])
            .routes.with_route("/echo", echo)
            .with_route("/health", health)
            .done()
            .build()
        )

        transport = ASGITransport(app=server.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First 3 requests should succeed
            for _ in range(3):
                resp = await client.get("/echo")
                assert resp.status_code == 200
                assert "x-ratelimit-limit" in resp.headers

            # 4th should be rate limited
            resp = await client.get("/echo")
            assert resp.status_code == 429
            assert "retry-after" in resp.headers
            body = resp.json()
            assert body["detail"] == "Too Many Requests"

            # Health should still work (exempt)
            resp = await client.get("/health")
            assert resp.status_code == 200
