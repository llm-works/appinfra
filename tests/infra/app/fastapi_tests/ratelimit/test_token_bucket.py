"""Tests for TokenBucketLimiter."""

import pickle
import time

import pytest

from appinfra.app.fastapi.ratelimit.token_bucket import (
    TokenBucketLimiter,
    _extract_ip_from_scope,
    _extract_ip_with_header,
)

# =============================================================================
# Test IP extraction helpers
# =============================================================================


@pytest.mark.unit
class TestExtractIpFromScope:
    """Test _extract_ip_from_scope helper."""

    def test_extracts_client_ip(self):
        """Test extracting IP from scope client tuple."""
        scope = {"client": ("192.168.1.1", 12345)}
        assert _extract_ip_from_scope(scope) == "192.168.1.1"

    def test_no_client_returns_unknown(self):
        """Test fallback when no client in scope."""
        assert _extract_ip_from_scope({}) == "unknown"
        assert _extract_ip_from_scope({"client": None}) == "unknown"


@pytest.mark.unit
class TestExtractIpWithHeader:
    """Test _extract_ip_with_header helper."""

    def test_extracts_from_header(self):
        """Test extracting IP from a proxy header."""
        scope = {
            "client": ("10.0.0.1", 80),
            "headers": [(b"x-forwarded-for", b"203.0.113.50")],
        }
        result = _extract_ip_with_header(scope, b"x-forwarded-for")
        assert result == "203.0.113.50"

    def test_comma_separated_uses_leftmost(self):
        """Test X-Forwarded-For with multiple IPs uses leftmost."""
        scope = {
            "client": ("10.0.0.1", 80),
            "headers": [
                (b"x-forwarded-for", b"203.0.113.50, 70.41.3.18, 150.172.238.178")
            ],
        }
        result = _extract_ip_with_header(scope, b"x-forwarded-for")
        assert result == "203.0.113.50"

    def test_falls_back_to_client(self):
        """Test fallback to client IP when header not present."""
        scope = {"client": ("10.0.0.1", 80), "headers": []}
        result = _extract_ip_with_header(scope, b"x-forwarded-for")
        assert result == "10.0.0.1"

    def test_cloudflare_header(self):
        """Test CF-Connecting-IP header."""
        scope = {
            "client": ("10.0.0.1", 80),
            "headers": [(b"cf-connecting-ip", b"203.0.113.99")],
        }
        result = _extract_ip_with_header(scope, b"cf-connecting-ip")
        assert result == "203.0.113.99"


# =============================================================================
# Test TokenBucketLimiter initialization
# =============================================================================


@pytest.mark.unit
class TestTokenBucketInit:
    """Test TokenBucketLimiter initialization."""

    def test_string_rate(self):
        """Test initialization with string rate."""
        limiter = TokenBucketLimiter(rate="60/min")
        assert limiter.max_requests == 60
        assert limiter.window == 60.0
        assert limiter.burst == 60

    def test_int_rate_with_window(self):
        """Test initialization with int rate and explicit window."""
        limiter = TokenBucketLimiter(rate=100, window=3600.0)
        assert limiter.max_requests == 100
        assert limiter.window == 3600.0

    def test_custom_burst(self):
        """Test burst capacity override."""
        limiter = TokenBucketLimiter(rate="60/min", burst=10)
        assert limiter.burst == 10

    def test_invalid_rate(self):
        """Test error on invalid rate."""
        with pytest.raises(ValueError, match="positive"):
            TokenBucketLimiter(rate=0)
        with pytest.raises(ValueError, match="positive"):
            TokenBucketLimiter(rate=-5)

    def test_invalid_burst(self):
        """Test error on invalid burst."""
        with pytest.raises(ValueError, match="positive"):
            TokenBucketLimiter(rate="60/min", burst=0)
        with pytest.raises(ValueError, match="positive"):
            TokenBucketLimiter(rate="60/min", burst=-1)

    def test_invalid_window(self):
        """Test error on non-positive window."""
        with pytest.raises(ValueError, match="Window must be positive"):
            TokenBucketLimiter(rate=10, window=0)
        with pytest.raises(ValueError, match="Window must be positive"):
            TokenBucketLimiter(rate=10, window=-1.0)


# =============================================================================
# Test is_allowed
# =============================================================================


@pytest.mark.unit
class TestIsAllowed:
    """Test rate limiting logic."""

    def test_allows_within_limit(self):
        """Test requests within limit are allowed."""
        limiter = TokenBucketLimiter(rate=5, window=60.0)
        for _ in range(5):
            allowed, headers = limiter.is_allowed("client1")
            assert allowed is True

    def test_denies_over_limit(self):
        """Test requests over limit are denied."""
        limiter = TokenBucketLimiter(rate=3, window=60.0)
        for _ in range(3):
            limiter.is_allowed("client1")

        allowed, headers = limiter.is_allowed("client1")
        assert allowed is False
        assert "Retry-After" in headers

    def test_per_key_isolation(self):
        """Test different keys have independent limits."""
        limiter = TokenBucketLimiter(rate=2, window=60.0)

        # Exhaust client1
        limiter.is_allowed("client1")
        limiter.is_allowed("client1")
        allowed, _ = limiter.is_allowed("client1")
        assert allowed is False

        # client2 should still be allowed
        allowed, _ = limiter.is_allowed("client2")
        assert allowed is True

    def test_burst_allows_initial_spike(self):
        """Test burst capacity allows initial spike above sustained rate."""
        limiter = TokenBucketLimiter(rate=1, window=60.0, burst=5)
        # Should allow 5 rapid requests due to burst
        for _ in range(5):
            allowed, _ = limiter.is_allowed("client1")
            assert allowed is True

        # 6th should be denied
        allowed, _ = limiter.is_allowed("client1")
        assert allowed is False

    def test_tokens_refill_over_time(self):
        """Test that tokens refill after time passes."""
        limiter = TokenBucketLimiter(rate=10, window=1.0)  # 10/sec

        # Exhaust tokens
        for _ in range(10):
            limiter.is_allowed("client1")
        allowed, _ = limiter.is_allowed("client1")
        assert allowed is False

        # Wait for refill
        time.sleep(0.2)  # Should refill ~2 tokens
        allowed, _ = limiter.is_allowed("client1")
        assert allowed is True

    def test_headers_on_allowed(self):
        """Test rate limit headers on allowed response."""
        limiter = TokenBucketLimiter(rate=10, window=60.0)
        allowed, headers = limiter.is_allowed("client1")

        assert allowed is True
        assert "X-RateLimit-Limit" in headers
        assert headers["X-RateLimit-Limit"] == "10"
        assert "X-RateLimit-Remaining" in headers

    def test_headers_on_denied(self):
        """Test Retry-After header on denied response."""
        limiter = TokenBucketLimiter(rate=1, window=60.0)
        limiter.is_allowed("client1")  # Consume the one token

        allowed, headers = limiter.is_allowed("client1")
        assert allowed is False
        assert "Retry-After" in headers
        assert int(headers["Retry-After"]) > 0


# =============================================================================
# Test extract_key
# =============================================================================


@pytest.mark.unit
class TestExtractKey:
    """Test key extraction from ASGI scope."""

    def test_default_uses_client_ip(self):
        """Test default key extraction uses client IP."""
        limiter = TokenBucketLimiter(rate="60/min")
        scope = {"client": ("192.168.1.1", 12345), "headers": []}
        assert limiter.extract_key(scope) == "192.168.1.1"

    def test_proxy_header(self):
        """Test key extraction with proxy header."""
        limiter = TokenBucketLimiter(rate="60/min", proxy_header="X-Forwarded-For")
        scope = {
            "client": ("10.0.0.1", 80),
            "headers": [(b"x-forwarded-for", b"203.0.113.50")],
        }
        assert limiter.extract_key(scope) == "203.0.113.50"

    def test_custom_key_func(self):
        """Test custom key function."""
        limiter = TokenBucketLimiter(rate="60/min", key_func=lambda scope: "global")
        scope = {"client": ("192.168.1.1", 12345), "headers": []}
        assert limiter.extract_key(scope) == "global"

    def test_custom_key_func_overrides_proxy_header(self):
        """Test that key_func takes precedence over proxy_header."""
        limiter = TokenBucketLimiter(
            rate="60/min",
            key_func=lambda scope: "custom",
            proxy_header="X-Forwarded-For",
        )
        scope = {
            "client": ("10.0.0.1", 80),
            "headers": [(b"x-forwarded-for", b"203.0.113.50")],
        }
        assert limiter.extract_key(scope) == "custom"


# =============================================================================
# Test cleanup
# =============================================================================


@pytest.mark.unit
class TestCleanup:
    """Test stale entry cleanup."""

    def test_removes_stale_entries(self):
        """Test that cleanup removes old entries."""
        limiter = TokenBucketLimiter(rate=10, window=1.0, stale_ttl=0.1)

        limiter.is_allowed("stale_client")
        time.sleep(0.15)  # Exceed stale_ttl
        limiter.cleanup()

        # Bucket should be gone
        assert "stale_client" not in limiter._buckets

    def test_keeps_active_entries(self):
        """Test that cleanup keeps recent entries."""
        limiter = TokenBucketLimiter(rate=10, window=60.0, stale_ttl=120.0)

        limiter.is_allowed("active_client")
        limiter.cleanup()

        # Should still have the bucket (not stale)
        assert "active_client" in limiter._buckets


# =============================================================================
# Test pickle support
# =============================================================================


@pytest.mark.unit
class TestPickle:
    """Test pickle support for subprocess mode."""

    def test_pickle_roundtrip(self):
        """Test limiter can be pickled and unpickled."""
        limiter = TokenBucketLimiter(rate="60/min", burst=10)
        limiter.is_allowed("test_client")

        data = pickle.dumps(limiter)
        restored = pickle.loads(data)

        # Should work with fresh state
        allowed, headers = restored.is_allowed("new_client")
        assert allowed is True
        assert restored.max_requests == 60
        assert restored.burst == 10

    def test_pickle_clears_buckets(self):
        """Test that unpickled limiter has empty buckets."""
        limiter = TokenBucketLimiter(rate=1, window=60.0)
        limiter.is_allowed("client1")  # Consume the one token

        data = pickle.dumps(limiter)
        restored = pickle.loads(data)

        # Restored limiter should have fresh buckets
        allowed, _ = restored.is_allowed("client1")
        assert allowed is True

    def test_pickle_with_key_func(self):
        """Test that non-picklable key_func is stripped during pickle."""
        limiter = TokenBucketLimiter(rate="60/min", key_func=lambda scope: "global")
        # Lambda is not picklable, but __getstate__ strips it
        data = pickle.dumps(limiter)
        restored = pickle.loads(data)

        # Restored limiter falls back to default IP extraction
        assert restored._key_func is None
        scope = {"client": ("1.2.3.4", 80), "headers": []}
        assert restored.extract_key(scope) == "1.2.3.4"
