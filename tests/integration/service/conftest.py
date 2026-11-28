# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Fixtures for the service integration tests."""

from collections.abc import Iterator

import pytest

from appinfra.service import Runtime
from tests.helpers.lg import quiet_lg


@pytest.fixture
def rt() -> Iterator[Runtime]:
    """A running service Runtime, stopped after the test: with a real logger,
    which an isolated service's process carries."""
    runtime = Runtime(quiet_lg(), name="test-runtime")
    runtime.start()
    yield runtime
    runtime.stop()
