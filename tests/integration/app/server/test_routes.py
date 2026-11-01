# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/server/routes.py that register pattern routes.

Pattern routes compile through safe_compile, whose timeout arms SIGALRM.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from appinfra.app.server.routes import RouteManager


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
