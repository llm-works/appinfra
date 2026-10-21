# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""MemoryStore against the store conformance suite."""

from __future__ import annotations

import pytest

from appinfra.cas import Blob, MemoryStore
from appinfra.cas.conformance import Age, StoreConformance

pytestmark = pytest.mark.unit


class TestMemoryStore(StoreConformance):
    """MemoryStore passes the conformance suite."""

    @pytest.fixture
    def store(self) -> MemoryStore:
        """A fresh, empty store."""
        return MemoryStore()

    @pytest.fixture
    def age(self, store: MemoryStore) -> Age:
        """Move an object's recorded write time into the past."""

        def age(repo: str, object_id: str, seconds: float) -> None:
            objects = store._repos[repo].objects
            object_type, data, mtime = objects[object_id]
            objects[object_id] = (object_type, data, mtime - seconds)

        return age

    def test_stored_data_is_a_copy(self, store: MemoryStore) -> None:
        """Mutating the caller's buffer after a write does not change the stored object."""
        data = bytearray(b"abc")
        object_id = Blob(b"abc").id
        store.write_object("r", object_id, "blob", data)  # type: ignore[arg-type]
        data[0] = ord("z")
        assert store.read_object("r", object_id) == ("blob", b"abc")

    def test_failed_ref_write_creates_no_repo(self, store: MemoryStore) -> None:
        """A compare-and-set that fails leaves no empty repository behind."""
        assert not store.write_ref("r", "main", None, "0" * 64)
        assert store.list_repos() == []
