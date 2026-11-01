# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for FastAPIAdapter with a real FastAPI app served through a test client."""

from unittest.mock import MagicMock, patch

import pytest

from appinfra.app.fastapi.config.api import ApiConfig
from appinfra.app.fastapi.runtime.adapter import FastAPIAdapter, MiddlewareDefinition


@pytest.mark.usefixtures("clean_env")
class TestSubprocessLoggerMiddlewareOrdering:
    """Integration test for middleware ordering with subprocess logger."""

    def test_app_state_lg_available_in_custom_middleware(self):
        """Test that app.state.lg is available in custom middleware before request.state.lg."""
        from fastapi import Request
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.testclient import TestClient

        # Track what the middleware observes
        middleware_observations: dict = {}

        class ObserverMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next):
                middleware_observations["app_state_lg"] = getattr(
                    request.app.state, "lg", None
                )
                middleware_observations["request_state_lg"] = getattr(
                    request.state, "lg", None
                )
                return await call_next(request)

        # Build app with real FastAPI (not mocked)
        with patch("appinfra.app.fastapi.runtime.adapter.FASTAPI_AVAILABLE", True):
            adapter = FastAPIAdapter(ApiConfig())
            mock_logger = MagicMock()
            mock_logger.name = "test_logger"

            # Inject logger and add custom middleware
            adapter.inject_subprocess_logger(mock_logger)
            adapter.add_middleware(
                MiddlewareDefinition(middleware_class=ObserverMiddleware)
            )

            app = adapter.build()

            # Add a simple route for testing
            @app.get("/test")
            async def test_route():
                return {"status": "ok"}

            # Make a request using context manager for proper lifespan handling
            with TestClient(app) as client:
                response = client.get("/test")

                assert response.status_code == 200

                # Verify middleware ordering: app.state.lg available, request.state.lg not yet set
                assert middleware_observations["app_state_lg"] is mock_logger
                assert middleware_observations["request_state_lg"] is None
