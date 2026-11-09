# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for a FastAPI ServerBuilder app served through a test client, which runs the app
on a thread of its own."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_lg():
    """Mock logger for ServerBuilder."""
    return MagicMock()


_DOCS_PATHS = ["/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"]


class TestDocsRoutes:
    """Docs and schema routes served by a real FastAPI app."""

    def _get_all(self, mock_lg, *, docs: bool | None) -> dict[str, int]:
        """Status of each docs path on a server built with the given setting."""
        from starlette.testclient import TestClient

        from appinfra.app.fastapi.builder.server import ServerBuilder

        builder = ServerBuilder(mock_lg, "test-api").routes.with_route(
            "/health", lambda: {"status": "ok"}
        )
        builder = builder.done()
        if docs is not None:
            builder.with_docs(docs)
        with TestClient(builder.build().app) as client:
            assert client.get("/health").status_code == 200
            return {path: client.get(path).status_code for path in _DOCS_PATHS}

    @pytest.mark.parametrize("docs", [None, False], ids=["default", "disabled"])
    def test_docs_routes_absent(self, mock_lg, docs):
        """Without with_docs(True) every docs path answers 404."""
        assert self._get_all(mock_lg, docs=docs) == dict.fromkeys(_DOCS_PATHS, 404)

    def test_docs_routes_served_when_enabled(self, mock_lg):
        """with_docs() serves the Swagger UI, ReDoc and the schema."""
        assert self._get_all(mock_lg, docs=True) == dict.fromkeys(_DOCS_PATHS, 200)
