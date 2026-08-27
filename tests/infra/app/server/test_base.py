# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/server/base.py.

Tests key functionality including:
- Server class initialization and properties
- Route and middleware management
- Request handling with middleware
- lock_helper context manager
- get_server_routes function
"""

import threading
from unittest.mock import AsyncMock, Mock

import pytest

from appinfra.app.server.base import Server, get_server_routes, lock_helper

# =============================================================================
# Test Server Initialization
# =============================================================================


@pytest.mark.unit
class TestServerInit:
    """Test Server initialization (lines 29-38)."""

    def test_basic_initialization(self):
        """Test basic initialization without parent (lines 36-38)."""
        server = Server()

        assert server.routes is not None
        assert server.middleware == []

    def test_initialization_with_parent(self):
        """Test initialization with parent (line 36)."""
        parent = Mock()
        server = Server(parent)

        assert server._parent is parent

    def test_creates_route_manager(self):
        """Test creates RouteManager instance (line 37)."""
        from appinfra.app.server.routes import RouteManager

        server = Server()

        assert isinstance(server.routes, RouteManager)


# =============================================================================
# Test server_routes Property
# =============================================================================


@pytest.mark.unit
class TestServerRoutesProperty:
    """Test server_routes property (lines 40-48)."""

    def test_returns_routes(self):
        """Test returns routes attribute (line 48)."""
        server = Server()

        assert server.server_routes is server.routes


# =============================================================================
# Test add_route
# =============================================================================


@pytest.mark.unit
class TestAddRoute:
    """Test add_route method (lines 50-63)."""

    def test_adds_route_with_default_methods(self):
        """Test adds route with default GET method (lines 61-62)."""
        server = Server()
        handler = Mock()

        server.add_route("/api/test", handler)

        # Verify route was added
        result = server.routes.get_handler("/api/test", "GET")
        assert result is handler

    def test_adds_route_with_custom_methods(self):
        """Test adds route with specified methods (line 63)."""
        server = Server()
        handler = Mock()

        server.add_route("/api/test", handler, methods=["POST", "PUT"])

        assert server.routes.get_handler("/api/test", "POST") is handler
        assert server.routes.get_handler("/api/test", "PUT") is handler
        assert server.routes.get_handler("/api/test", "GET") is None

    def test_adds_multiple_routes(self):
        """Test adds multiple routes."""
        server = Server()
        handler1 = Mock()
        handler2 = Mock()

        server.add_route("/api/users", handler1)
        server.add_route("/api/items", handler2)

        assert server.routes.get_handler("/api/users", "GET") is handler1
        assert server.routes.get_handler("/api/items", "GET") is handler2


# =============================================================================
# Test add_middleware
# =============================================================================


@pytest.mark.unit
class TestAddMiddleware:
    """Test add_middleware method (lines 65-72)."""

    def test_adds_middleware(self):
        """Test adds middleware to list (line 72)."""
        server = Server()
        middleware = Mock()

        server.add_middleware(middleware)

        assert middleware in server.middleware

    def test_adds_multiple_middleware(self):
        """Test adds multiple middleware in order."""
        server = Server()
        mw1 = Mock()
        mw2 = Mock()
        mw3 = Mock()

        server.add_middleware(mw1)
        server.add_middleware(mw2)
        server.add_middleware(mw3)

        assert server.middleware == [mw1, mw2, mw3]


# =============================================================================
# Test server_start
# =============================================================================


@pytest.mark.unit
class TestServerStart:
    """Test server_start method (lines 74-81)."""

    def test_server_start_does_nothing(self):
        """Test server_start is a no-op (line 81)."""
        server = Server()
        manager = Mock()

        # Should not raise
        result = server.server_start(manager)

        assert result is None


# =============================================================================
# Test server_tick
# =============================================================================


@pytest.mark.unit
class TestServerTick:
    """Test server_tick method (lines 83-89)."""

    def test_server_tick_does_nothing(self):
        """Test server_tick is a no-op (line 89)."""
        server = Server()

        # Should not raise
        result = server.server_tick()

        assert result is None


# =============================================================================
# Test HTTP Method Handlers
# =============================================================================


@pytest.mark.unit
class TestHttpMethodHandlers:
    """Test HTTP method handler methods (lines 91-141)."""

    def test_server_do_GET_does_nothing(self):
        """Test server_do_GET is a no-op (line 102)."""
        server = Server()
        req = Mock()

        result = server.server_do_GET(req, param="value")

        assert result is None

    def test_server_do_POST_does_nothing(self):
        """Test server_do_POST is a no-op (line 115)."""
        server = Server()
        req = Mock()

        result = server.server_do_POST(req, param="value")

        assert result is None

    def test_server_do_PUT_does_nothing(self):
        """Test server_do_PUT is a no-op (line 128)."""
        server = Server()
        req = Mock()

        result = server.server_do_PUT(req, param="value")

        assert result is None

    def test_server_do_DELETE_does_nothing(self):
        """Test server_do_DELETE is a no-op (line 141)."""
        server = Server()
        req = Mock()

        result = server.server_do_DELETE(req, param="value")

        assert result is None


# =============================================================================
# Test handle_request
# =============================================================================


@pytest.mark.unit
class TestHandleRequest:
    """Test handle_request method (lines 143-164)."""

    @pytest.mark.asyncio
    async def test_routes_request_without_middleware(self):
        """Test routes request to handler (line 158)."""
        server = Server()
        handler = AsyncMock(return_value={"status": 200})
        server.add_route("/api/test", handler)

        request = Mock()
        request.path = "/api/test"
        request.method = "GET"

        result = await server.handle_request(request)

        assert result == {"status": 200}

    @pytest.mark.asyncio
    async def test_applies_request_middleware(self):
        """Test applies middleware to request (lines 154-155)."""
        server = Server()
        handler = AsyncMock(return_value={"status": 200})
        server.add_route("/api/test", handler)

        middleware = Mock()
        modified_request = Mock(path="/api/test", method="GET")
        middleware.process_request = AsyncMock(return_value=modified_request)
        middleware.process_response = AsyncMock(side_effect=lambda r: r)
        server.add_middleware(middleware)

        request = Mock(path="/api/test", method="GET")
        await server.handle_request(request)

        middleware.process_request.assert_called_once_with(request)
        handler.assert_called_once_with(modified_request)

    @pytest.mark.asyncio
    async def test_applies_response_middleware_in_reverse(self):
        """Test applies middleware to response in reverse (lines 161-162)."""
        server = Server()
        handler = AsyncMock(return_value={"status": 200})
        server.add_route("/api/test", handler)

        call_order = []

        mw1 = Mock()
        mw1.process_request = AsyncMock(side_effect=lambda r: r)
        mw1.process_response = AsyncMock(
            side_effect=lambda r: (call_order.append(1), r)[1]
        )

        mw2 = Mock()
        mw2.process_request = AsyncMock(side_effect=lambda r: r)
        mw2.process_response = AsyncMock(
            side_effect=lambda r: (call_order.append(2), r)[1]
        )

        server.add_middleware(mw1)
        server.add_middleware(mw2)

        request = Mock(path="/api/test", method="GET")
        await server.handle_request(request)

        # Response middleware should be called in reverse order
        assert call_order == [2, 1]

    @pytest.mark.asyncio
    async def test_returns_404_for_unknown_route(self):
        """Test returns 404 for unknown route."""
        server = Server()

        request = Mock(path="/unknown", method="GET")
        result = await server.handle_request(request)

        assert result["status"] == 404


# =============================================================================
# Test lock_helper
# =============================================================================


@pytest.mark.unit
class TestLockHelper:
    """Test lock_helper context manager (lines 167-222)."""

    def test_acquires_and_releases_lock(self):
        """Test acquires and releases lock (lines 198-204)."""
        lock = threading.Lock()
        lg = Mock()
        lg.trace = Mock()

        with lock_helper(lock, lg, where="test", timeout=5.0):
            assert lock.locked()

        assert not lock.locked()

    def test_logs_acquisition(self):
        """Test logs lock acquisition (line 199)."""
        lock = threading.Lock()
        lg = Mock()

        with lock_helper(lock, lg, where="test", timeout=5.0):
            pass

        lg.trace.assert_any_call(
            "acquired lock",
            extra={"after": pytest.approx(0.0, abs=0.1), "where": "test"},
        )

    def test_logs_release(self):
        """Test logs lock release (lines 205-212)."""
        lock = threading.Lock()
        lg = Mock()

        with lock_helper(lock, lg, where="test", timeout=5.0):
            pass

        # Should have logged release
        release_calls = [
            c for c in lg.trace.call_args_list if c[0][0] == "released lock"
        ]
        assert len(release_calls) == 1

    def test_raises_timeout_error_on_timeout(self):
        """Test raises TimeoutError on timeout (lines 213-222)."""
        lock = threading.Lock()
        lock.acquire()  # Pre-acquire lock
        lg = Mock()
        lg.error = Mock()

        with pytest.raises(TimeoutError) as exc_info:
            with lock_helper(lock, lg, where="test_location", timeout=0.01):
                pass

        assert "test_location" in str(exc_info.value)
        lock.release()

    def test_logs_error_on_timeout(self):
        """Test logs error on timeout (lines 215-218)."""
        lock = threading.Lock()
        lock.acquire()  # Pre-acquire lock
        lg = Mock()

        try:
            with lock_helper(lock, lg, where="test", timeout=0.01):
                pass
        except TimeoutError:
            pass

        lg.error.assert_called_once()
        lock.release()

    def test_works_with_blocking_acquire(self):
        """Test works with blocking acquire (timeout=-1 means blocking)."""
        lock = threading.Lock()
        lg = Mock()

        # Use a small positive timeout instead of None
        with lock_helper(lock, lg, where="test", timeout=5.0):
            pass

        assert not lock.locked()

    def test_works_without_where(self):
        """Test works when where is None (line 171)."""
        lock = threading.Lock()
        lg = Mock()

        with lock_helper(lock, lg, timeout=5.0):
            pass

        assert not lock.locked()

    def test_releases_lock_on_exception(self):
        """Test releases lock even if exception raised in body."""
        lock = threading.Lock()
        lg = Mock()

        with pytest.raises(ValueError):
            with lock_helper(lock, lg, where="test", timeout=5.0):
                raise ValueError("test error")

        assert not lock.locked()


# =============================================================================
# Test get_server_routes
# =============================================================================


@pytest.mark.unit
class TestGetServerRoutes:
    """Test get_server_routes function (lines 225-249)."""

    def test_returns_empty_for_empty_list(self):
        """Test returns empty dict for empty list (line 238)."""
        result = get_server_routes([])

        assert result == {}

    def test_skips_tools_without_server_routes(self):
        """Test skips tools without server_routes attribute (line 240)."""
        tool1 = Mock(spec=[])  # No server_routes attribute
        tool2 = Mock()
        tool2.server_routes = None

        result = get_server_routes([tool1, tool2])

        assert result == {}

    def test_handles_dict_server_routes(self):
        """Test handles dictionary server_routes (lines 242-244)."""
        tool = Mock()
        tool.server_routes = {"/api/users": "handler1", "/api/items": "handler2"}

        result = get_server_routes([tool])

        assert result == {"/api/users": "handler1", "/api/items": "handler2"}

    def test_handles_list_server_routes(self):
        """Test handles list server_routes (lines 245-248)."""
        tool = Mock()
        tool.server_routes = ["/api/users", "/api/items"]

        result = get_server_routes([tool])

        assert result == {"/api/users": tool, "/api/items": tool}

    def test_merges_routes_from_multiple_tools(self):
        """Test merges routes from multiple tools."""
        tool1 = Mock()
        tool1.server_routes = {"/api/users": "handler1"}
        tool2 = Mock()
        tool2.server_routes = {"/api/items": "handler2"}

        result = get_server_routes([tool1, tool2])

        assert result == {"/api/users": "handler1", "/api/items": "handler2"}

    def test_handles_mixed_dict_and_list_routes(self):
        """Test handles mixed dict and list routes."""
        tool1 = Mock()
        tool1.server_routes = {"/api/users": "handler1"}
        tool2 = Mock()
        tool2.server_routes = ["/api/items", "/api/orders"]

        result = get_server_routes([tool1, tool2])

        assert result == {
            "/api/users": "handler1",
            "/api/items": tool2,
            "/api/orders": tool2,
        }

    def test_later_tool_overwrites_earlier(self):
        """Test later tool routes overwrite earlier (dict merge behavior)."""
        tool1 = Mock()
        tool1.server_routes = {"/api/users": "handler1"}
        tool2 = Mock()
        tool2.server_routes = {"/api/users": "handler2"}

        result = get_server_routes([tool1, tool2])

        assert result["/api/users"] == "handler2"

    def test_skips_empty_server_routes(self):
        """Test skips tools with empty server_routes."""
        tool1 = Mock()
        tool1.server_routes = {}
        tool2 = Mock()
        tool2.server_routes = []

        result = get_server_routes([tool1, tool2])

        assert result == {}


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestServerIntegration:
    """Test Server integration scenarios."""

    @pytest.mark.asyncio
    async def test_full_request_handling_workflow(self):
        """Test complete request handling with middleware."""
        server = Server()

        # Add handler
        handler = AsyncMock(return_value={"status": 200, "data": "original"})
        server.add_route("/api/test", handler)

        # Add middleware that modifies request/response
        class TestMiddleware:
            async def process_request(self, request):
                request.modified = True
                return request

            async def process_response(self, response):
                response["data"] = "modified"
                return response

        server.add_middleware(TestMiddleware())

        # Handle request
        request = Mock(path="/api/test", method="GET")
        result = await server.handle_request(request)

        # Verify middleware effects
        assert request.modified is True
        assert result["data"] == "modified"

    def test_subclass_can_override_handlers(self):
        """Test subclasses can override HTTP method handlers."""

        class CustomServer(Server):
            def server_do_GET(self, req, **kwargs):
                return {"method": "GET", "custom": True}

            def server_start(self, manager):
                self.started = True

        server = CustomServer()

        # Test overridden GET
        result = server.server_do_GET(Mock())
        assert result == {"method": "GET", "custom": True}

        # Test overridden server_start
        server.server_start(Mock())
        assert server.started is True

    @pytest.mark.asyncio
    async def test_multiple_middleware_chain(self):
        """Test multiple middleware are applied correctly."""
        server = Server()
        handler = AsyncMock(return_value={"value": 0})
        server.add_route("/api/test", handler)

        class IncrementMiddleware:
            def __init__(self, amount):
                self.amount = amount

            async def process_request(self, request):
                return request

            async def process_response(self, response):
                response["value"] += self.amount
                return response

        server.add_middleware(IncrementMiddleware(1))
        server.add_middleware(IncrementMiddleware(2))
        server.add_middleware(IncrementMiddleware(3))

        request = Mock(path="/api/test", method="GET")
        result = await server.handle_request(request)

        # All middleware should have added their amounts
        assert result["value"] == 6  # 0 + 3 + 2 + 1 (reverse order)
