# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the console's rich status display, which refreshes on a thread of its own."""

from __future__ import annotations

from io import StringIO

import pytest

from appinfra.ui.console import (
    Console,
    reset_console,
)


@pytest.fixture(autouse=True)
def reset_global_console():
    """Reset the global console before each test."""
    reset_console()
    yield
    reset_console()


class TestConsoleRichPath:
    """Tests for Console when rich is actually used."""

    def test_status_returns_context_manager(self):
        """Test status returns a context manager that can be used."""
        output = StringIO()
        console = Console(no_color=False, force_terminal=True, file=output)

        # Exercise status path
        with console.status("Processing...") as status:
            # Status object should exist
            assert status is not None
