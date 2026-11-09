# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""MemoryStore against the concurrency part of the store conformance suite."""

from __future__ import annotations

import pytest

from appinfra.cas import MemoryStore
from appinfra.cas.conformance import StoreConcurrencyConformance
from appinfra.log import Logger

LG = Logger("test-cas")


class TestMemoryStore(StoreConcurrencyConformance):
    """MemoryStore passes the concurrency conformance tests."""

    @pytest.fixture
    def store(self) -> MemoryStore:
        """A fresh, empty store."""
        return MemoryStore(LG)
