"""
Tests for app/server/handlers.py.

Tests key functionality including:
- Middleware base class
- RequestHandler class
- LoggingMiddleware
- AuthMiddleware
"""

from unittest.mock import AsyncMock, Mock

import pytest

from appinfra.app.server.handlers import (
    AuthMiddleware,
    LoggingMiddleware,
    Middleware,
    RequestHandler,
)

# =============================================================================
# Test Middleware Base Class
# =============================================================================


@pytest.mark.unit
class TestMiddlewareBase:
    """Test Middleware abstract base class."""

    def test_cannot_instantiate_directly(self):
        """Test Middleware is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            Middleware()


class ConcreteMiddleware(Middleware):
    """Concrete implementation for testing."""

    async def process_request(self, request):
        return request

    async def process_response(self, response):
        return response


@pytest.mark.unit
class TestConcreteMiddleware:
    """Test concrete Middleware implementation."""

    @pytest.mark.asyncio
    async def test_process_request(self):
        """Test process_request can be implemented."""
        middleware = ConcreteMiddleware()
        request = {"path": "/test"}

        result = await middleware.process_request(request)

        assert result == request

    @pytest.mark.asyncio
    async def test_process_response(self):
        """Test process_response can be implemented."""
        middleware = ConcreteMiddleware()
        response = {"status": 200}

        result = await middleware.process_response(response)

        assert result == response


# =============================================================================
# Test RequestHandler
# =============================================================================


@pytest.mark.unit
class TestRequestHandlerInit:
    """Test RequestHandler initialization."""

    def test_init_without_server(self):
        """Test initialization without server."""
        handler = RequestHandler()

        assert handler.server is None

    def test_init_with_server(self):
        """Test initialization with server."""
        server = Mock()
        handler = RequestHandler(server=server)

        assert handler.server is server


@pytest.mark.unit
class TestRequestHandlerHandle:
    """Test RequestHandler.handle method."""

    @pytest.mark.asyncio
    async def test_dispatches_to_method_handler(self):
        """Test dispatches to handle_<method> when available."""
        handler = RequestHandler()
        handler.handle_get = AsyncMock(return_value={"status": 200})
        request = Mock(method="GET")

        result = await handler.handle(request)

        handler.handle_get.assert_called_once_with(request)
        assert result == {"status": 200}

    @pytest.mark.asyncio
    async def test_falls_back_to_default(self):
        """Test falls back to handle_default when no method handler."""
        handler = RequestHandler()
        request = Mock(method="PATCH")  # No handle_patch method

        result = await handler.handle(request)

        assert result == {"status": 405, "message": "Method Not Allowed"}

    @pytest.mark.asyncio
    async def test_default_method_is_get(self):
        """Test defaults to GET when method attribute missing."""
        handler = RequestHandler()
        handler.handle_get = AsyncMock(return_value={"status": 200})
        request = Mock(spec=[])  # No method attribute

        result = await handler.handle(request)

        handler.handle_get.assert_called_once()


@pytest.mark.unit
class TestRequestHandlerHandleDefault:
    """Test RequestHandler.handle_default method."""

    @pytest.mark.asyncio
    async def test_returns_method_not_allowed(self):
        """Test returns 405 Method Not Allowed."""
        handler = RequestHandler()
        request = Mock()

        result = await handler.handle_default(request)

        assert result["status"] == 405
        assert "Not Allowed" in result["message"]


@pytest.mark.unit
class TestRequestHandlerMethodHandlers:
    """Test RequestHandler method-specific handlers."""

    @pytest.mark.asyncio
    async def test_handle_get_delegates_to_default(self):
        """Test handle_get delegates to handle_default."""
        handler = RequestHandler()
        request = Mock()

        result = await handler.handle_get(request)

        assert result["status"] == 405

    @pytest.mark.asyncio
    async def test_handle_post_delegates_to_default(self):
        """Test handle_post delegates to handle_default."""
        handler = RequestHandler()
        request = Mock()

        result = await handler.handle_post(request)

        assert result["status"] == 405

    @pytest.mark.asyncio
    async def test_handle_put_delegates_to_default(self):
        """Test handle_put delegates to handle_default."""
        handler = RequestHandler()
        request = Mock()

        result = await handler.handle_put(request)

        assert result["status"] == 405

    @pytest.mark.asyncio
    async def test_handle_delete_delegates_to_default(self):
        """Test handle_delete delegates to handle_default."""
        handler = RequestHandler()
        request = Mock()

        result = await handler.handle_delete(request)

        assert result["status"] == 405


# =============================================================================
# Test LoggingMiddleware
# =============================================================================


@pytest.mark.unit
class TestLoggingMiddlewareInit:
    """Test LoggingMiddleware initialization."""

    def test_stores_logger(self):
        """Test stores logger reference."""
        logger = Mock()
        middleware = LoggingMiddleware(logger)

        assert middleware.logger is logger


@pytest.mark.unit
class TestLoggingMiddlewareProcessRequest:
    """Test LoggingMiddleware.process_request method."""

    @pytest.mark.asyncio
    async def test_logs_incoming_request(self):
        """Test logs incoming request details."""
        logger = Mock()
        middleware = LoggingMiddleware(logger)
        request = Mock(path="/api/test", method="POST")

        result = await middleware.process_request(request)

        logger.info.assert_called_once()
        log_message = logger.info.call_args[0][0]
        assert "incoming request" in log_message
        extra = logger.info.call_args[1]["extra"]
        assert extra["method"] == "POST"
        assert extra["path"] == "/api/test"
        assert result is request

    @pytest.mark.asyncio
    async def test_handles_missing_attributes(self):
        """Test handles request without path/method attributes."""
        logger = Mock()
        middleware = LoggingMiddleware(logger)
        request = Mock(spec=[])  # No attributes

        result = await middleware.process_request(request)

        logger.info.assert_called_once()
        extra = logger.info.call_args[1]["extra"]
        assert extra["method"] == "GET"  # Default method
        assert extra["path"] == "/"  # Default path


@pytest.mark.unit
class TestLoggingMiddlewareProcessResponse:
    """Test LoggingMiddleware.process_response method."""

    @pytest.mark.asyncio
    async def test_logs_outgoing_response(self):
        """Test logs outgoing response details."""
        logger = Mock()
        middleware = LoggingMiddleware(logger)
        response = Mock(status=201)

        result = await middleware.process_response(response)

        logger.info.assert_called_once()
        extra = logger.info.call_args[1]["extra"]
        assert extra["status"] == 201
        assert result is response

    @pytest.mark.asyncio
    async def test_handles_missing_status(self):
        """Test handles response without status attribute."""
        logger = Mock()
        middleware = LoggingMiddleware(logger)
        response = Mock(spec=[])  # No status attribute

        result = await middleware.process_response(response)

        extra = logger.info.call_args[1]["extra"]
        assert extra["status"] == 200  # Default status


# =============================================================================
# Test AuthMiddleware
# =============================================================================


@pytest.mark.unit
class TestAuthMiddlewareInit:
    """Test AuthMiddleware initialization."""

    def test_stores_auth_checker(self):
        """Test stores auth checker function."""
        checker = Mock()
        middleware = AuthMiddleware(checker)

        assert middleware.auth_checker is checker


@pytest.mark.unit
class TestAuthMiddlewareProcessRequest:
    """Test AuthMiddleware.process_request method."""

    @pytest.mark.asyncio
    async def test_passes_authenticated_request(self):
        """Test passes request when authenticated."""
        checker = Mock(return_value=True)
        middleware = AuthMiddleware(checker)
        request = Mock()

        result = await middleware.process_request(request)

        checker.assert_called_once_with(request)
        assert result is request

    @pytest.mark.asyncio
    async def test_returns_unauthorized_for_failed_auth(self):
        """Test returns 401 when auth fails."""
        checker = Mock(return_value=False)
        middleware = AuthMiddleware(checker)
        request = Mock()

        result = await middleware.process_request(request)

        checker.assert_called_once_with(request)
        assert result["status"] == 401
        assert "Unauthorized" in result["message"]


@pytest.mark.unit
class TestAuthMiddlewareProcessResponse:
    """Test AuthMiddleware.process_response method."""

    @pytest.mark.asyncio
    async def test_passes_response_unchanged(self):
        """Test passes response unchanged."""
        checker = Mock()
        middleware = AuthMiddleware(checker)
        response = Mock()

        result = await middleware.process_response(response)

        assert result is response


@pytest.mark.unit
class TestAuthMiddlewareCreateUnauthorizedResponse:
    """Test AuthMiddleware._create_unauthorized_response method."""

    def test_creates_401_response(self):
        """Test creates 401 Unauthorized response."""
        checker = Mock()
        middleware = AuthMiddleware(checker)

        result = middleware._create_unauthorized_response()

        assert result["status"] == 401
        assert result["message"] == "Unauthorized"


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestMiddlewareIntegration:
    """Integration tests for middleware."""

    @pytest.mark.asyncio
    async def test_middleware_chain(self):
        """Test chaining multiple middleware."""
        logger = Mock()
        auth_checker = Mock(return_value=True)

        logging_mw = LoggingMiddleware(logger)
        auth_mw = AuthMiddleware(auth_checker)

        request = Mock(path="/api/data", method="GET")

        # Process through chain
        request = await logging_mw.process_request(request)
        request = await auth_mw.process_request(request)

        # Both should have processed
        assert logger.info.called
        assert auth_checker.called


@pytest.mark.integration
class TestRequestHandlerIntegration:
    """Integration tests for RequestHandler."""

    @pytest.mark.asyncio
    async def test_custom_handler_implementation(self):
        """Test custom handler with overridden methods."""

        class CustomHandler(RequestHandler):
            async def handle_get(self, request):
                return {"status": 200, "data": "custom"}

            async def handle_post(self, request):
                return {"status": 201, "created": True}

        handler = CustomHandler()

        get_request = Mock(method="GET")
        post_request = Mock(method="POST")
        delete_request = Mock(method="DELETE")

        get_result = await handler.handle(get_request)
        post_result = await handler.handle(post_request)
        delete_result = await handler.handle(delete_request)

        assert get_result["status"] == 200
        assert get_result["data"] == "custom"
        assert post_result["status"] == 201
        assert delete_result["status"] == 405  # Falls back to default
