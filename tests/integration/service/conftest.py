# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Fixtures for the service integration tests."""

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from appinfra.runtime import Runtime as Tasks


@pytest.fixture
def tasks() -> Iterator[Tasks]:
    """A running appinfra.runtime Runtime for TaskRunners to run services on."""
    tasks = Tasks(MagicMock())
    tasks.start()
    yield tasks
    tasks.stop()
