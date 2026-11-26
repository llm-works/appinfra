# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Fixtures for the service integration tests."""

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from appinfra.service import Runtime


@pytest.fixture
def rt() -> Iterator[Runtime]:
    """A running service Runtime, stopped after the test."""
    runtime = Runtime(MagicMock(), name="test-runtime")
    runtime.start()
    yield runtime
    runtime.stop()
