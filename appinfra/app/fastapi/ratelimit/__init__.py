# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""HTTP rate limiting for FastAPI servers.

Provides a rate limiter interface, built-in implementations, and ASGI
middleware for integrating rate limiting with ServerBuilder.

Example:
    from appinfra.app.fastapi.ratelimit import TokenBucketLimiter

    server = (
        ServerBuilder(lg, "api")
        .with_rate_limiter(
            TokenBucketLimiter(rate="60/min", burst=10),
            exempt_paths=["/health"],
        )
        .routes.with_route("/health", health).done()
        .build()
    )
"""

from .interface import RateLimiter
from .middleware import RateLimitMiddleware
from .parsing import parse_rate
from .token_bucket import TokenBucketLimiter

__all__ = [
    "RateLimiter",
    "RateLimitMiddleware",
    "TokenBucketLimiter",
    "parse_rate",
]
