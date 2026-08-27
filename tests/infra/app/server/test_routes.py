# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/server/routes.py.

Tests key functionality including:
- RouteManager class methods
- Route registration
- Request handling
- Pattern matching
"""

from unittest.mock import AsyncMock, Mock

import pytest

from appinfra.app.server.routes import RouteManager

# =============================================================================
# Test RouteManager Initialization
# =============================================================================


@pytest.mark.unit
class TestRouteManagerInit:
    """Test RouteManager initialization."""

    def test_basic_initialization(self):
        """Test basic initialization (lines 14-16)."""
        manager = RouteManager()

        assert manager._routes == {}
        assert manager._patterns == []


# =============================================================================
# Test add_route
# =============================================================================


@pytest.mark.unit
class TestAddRoute:
    """Test add_route method (lines 18-37)."""

    def test_add_simple_route(self):
        """Test adding simple string route (lines 32-37)."""
        manager = RouteManager()
        handler = Mock()

        manager.add_route("/api/users", handler, ["GET"])

        assert "/api/users" in manager._routes
        assert "GET" in manager._routes["/api/users"]
        assert manager._routes["/api/users"]["GET"] is handler

    def test_add_route_multiple_methods(self):
        """Test adding route with multiple methods (lines 36-37)."""
        manager = RouteManager()
        handler = Mock()

        manager.add_route("/api/users", handler, ["GET", "POST", "PUT"])

        assert "GET" in manager._routes["/api/users"]
        assert "POST" in manager._routes["/api/users"]
        assert "PUT" in manager._routes["/api/users"]

    def test_add_pattern_route_with_wildcard(self):
        """Test adding pattern route with wildcard (lines 27-31)."""
        manager = RouteManager()
        handler = Mock()

        manager.add_route("/api/users/*", handler, ["GET"])

        assert len(manager._patterns) == 1
        pattern, route_info = manager._patterns[0]
        assert "GET" in route_info

    def test_add_pattern_route_with_param(self):
        """Test adding pattern route with parameter (line 27)."""
        manager = RouteManager()
        handler = Mock()

        manager.add_route("/api/users/{id}", handler, ["GET"])

        assert len(manager._patterns) == 1

    def test_add_pattern_route_with_regex(self):
        """Test adding pattern route with regex (line 27)."""
        manager = RouteManager()
        handler = Mock()

        manager.add_route("/api/users/[0-9]+", handler, ["GET"])

        assert len(manager._patterns) == 1

    def test_add_multiple_routes_same_path(self):
        """Test adding multiple handlers for same path."""
        manager = RouteManager()
        get_handler = Mock()
        post_handler = Mock()

        manager.add_route("/api/users", get_handler, ["GET"])
        manager.add_route("/api/users", post_handler, ["POST"])

        assert manager._routes["/api/users"]["GET"] is get_handler
        assert manager._routes["/api/users"]["POST"] is post_handler


# =============================================================================
# Test get_handler
# =============================================================================


@pytest.mark.unit
class TestGetHandler:
    """Test get_handler method (lines 39-59)."""

    def test_get_handler_simple_route(self):
        """Test getting handler for simple route (lines 50-52)."""
        manager = RouteManager()
        handler = Mock()
        manager.add_route("/api/users", handler, ["GET"])

        result = manager.get_handler("/api/users", "GET")

        assert result is handler

    def test_get_handler_wrong_method(self):
        """Test getting handler for wrong method."""
        manager = RouteManager()
        handler = Mock()
        manager.add_route("/api/users", handler, ["GET"])

        result = manager.get_handler("/api/users", "POST")

        assert result is None

    def test_get_handler_unknown_path(self):
        """Test getting handler for unknown path (line 59)."""
        manager = RouteManager()

        result = manager.get_handler("/unknown", "GET")

        assert result is None

    def test_get_handler_pattern_route(self):
        """Test getting handler for pattern route (lines 55-57)."""
        manager = RouteManager()
        handler = Mock()
        manager.add_route("/api/users/[0-9]+", handler, ["GET"])

        result = manager.get_handler("/api/users/123", "GET")

        assert result is handler

    def test_simple_route_takes_precedence(self):
        """Test simple route checked before patterns (line 51)."""
        manager = RouteManager()
        simple_handler = Mock(name="simple")
        pattern_handler = Mock(name="pattern")

        manager.add_route("/api/users", simple_handler, ["GET"])
        manager.add_route("/api/.*", pattern_handler, ["GET"])

        result = manager.get_handler("/api/users", "GET")

        assert result is simple_handler


# =============================================================================
# Test handle_request
# =============================================================================


@pytest.mark.unit
class TestHandleRequest:
    """Test handle_request method (lines 61-79)."""

    @pytest.mark.asyncio
    async def test_handle_request_calls_handler(self):
        """Test handle_request calls the right handler (lines 71-76)."""
        manager = RouteManager()
        handler = AsyncMock(return_value={"status": 200})
        manager.add_route("/api/users", handler, ["GET"])

        request = Mock()
        request.path = "/api/users"
        request.method = "GET"

        result = await manager.handle_request(request)

        handler.assert_called_once_with(request)
        assert result == {"status": 200}

    @pytest.mark.asyncio
    async def test_handle_request_returns_404(self):
        """Test handle_request returns 404 for unknown route (lines 78-79)."""
        manager = RouteManager()

        request = Mock()
        request.path = "/unknown"
        request.method = "GET"

        result = await manager.handle_request(request)

        assert result["status"] == 404

    @pytest.mark.asyncio
    async def test_handle_request_default_path_method(self):
        """Test handle_request uses defaults for missing attrs (lines 71-72)."""
        manager = RouteManager()
        handler = AsyncMock(return_value={"status": 200})
        manager.add_route("/", handler, ["GET"])

        request = Mock(spec=[])  # No path or method attributes

        result = await manager.handle_request(request)

        handler.assert_called_once()


# =============================================================================
# Test _create_404_response
# =============================================================================


@pytest.mark.unit
class TestCreate404Response:
    """Test _create_404_response method (lines 81-84)."""

    def test_creates_404_response(self):
        """Test creates proper 404 response."""
        manager = RouteManager()

        result = manager._create_404_response()

        assert result["status"] == 404
        assert "Not Found" in result["message"]


# =============================================================================
# Test list_routes
# =============================================================================


@pytest.mark.unit
class TestListRoutes:
    """Test list_routes method (lines 86-103)."""

    def test_list_empty_routes(self):
        """Test listing empty routes."""
        manager = RouteManager()

        result = manager.list_routes()

        assert result == {}

    def test_list_simple_routes(self):
        """Test listing simple routes (lines 96-97)."""
        manager = RouteManager()
        manager.add_route("/api/users", Mock(), ["GET", "POST"])
        manager.add_route("/api/items", Mock(), ["GET"])

        result = manager.list_routes()

        assert "/api/users" in result
        assert set(result["/api/users"]) == {"GET", "POST"}
        assert "/api/items" in result
        assert result["/api/items"] == ["GET"]

    def test_list_pattern_routes(self):
        """Test listing pattern routes (lines 100-101)."""
        manager = RouteManager()
        manager.add_route("/api/users/[0-9]+", Mock(), ["GET"])

        result = manager.list_routes()

        # Pattern routes are listed with "PATTERN:" prefix
        pattern_key = [k for k in result.keys() if k.startswith("PATTERN:")][0]
        assert "GET" in result[pattern_key]

    def test_list_mixed_routes(self):
        """Test listing both simple and pattern routes."""
        manager = RouteManager()
        manager.add_route("/api/users", Mock(), ["GET"])
        manager.add_route("/api/items/*", Mock(), ["POST"])

        result = manager.list_routes()

        assert "/api/users" in result
        pattern_keys = [k for k in result.keys() if k.startswith("PATTERN:")]
        assert len(pattern_keys) == 1


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestRouteManagerIntegration:
    """Test RouteManager integration scenarios."""

    @pytest.mark.asyncio
    async def test_full_routing_workflow(self):
        """Test complete routing workflow."""
        manager = RouteManager()

        # Setup handlers
        users_handler = AsyncMock(return_value={"users": []})
        user_handler = AsyncMock(return_value={"user": {"id": 1}})
        create_handler = AsyncMock(return_value={"created": True})

        # Add routes
        manager.add_route("/api/users", users_handler, ["GET"])
        manager.add_route("/api/users", create_handler, ["POST"])
        manager.add_route("/api/users/[0-9]+", user_handler, ["GET"])

        # Test list users
        request = Mock(path="/api/users", method="GET")
        result = await manager.handle_request(request)
        assert result == {"users": []}

        # Test create user
        request = Mock(path="/api/users", method="POST")
        result = await manager.handle_request(request)
        assert result == {"created": True}

        # Test get specific user
        request = Mock(path="/api/users/123", method="GET")
        result = await manager.handle_request(request)
        assert result == {"user": {"id": 1}}

        # Test 404
        request = Mock(path="/api/unknown", method="GET")
        result = await manager.handle_request(request)
        assert result["status"] == 404

        # Verify routes list
        routes = manager.list_routes()
        assert "/api/users" in routes
