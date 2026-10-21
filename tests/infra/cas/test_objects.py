# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Object ids, serialization and validation."""

from __future__ import annotations

import hashlib

import pytest

from appinfra.cas import (
    Blob,
    Commit,
    CorruptObjectError,
    Tree,
    TreeEntry,
    canonical_json,
    content_hash,
    is_object_id,
)
from appinfra.cas.objects import deserialize

pytestmark = pytest.mark.unit

ID = "a" * 64


class TestIds:
    """How ids are computed."""

    def test_id_hashes_type_and_length_header(self) -> None:
        """id = sha256('<type> <length>\\0' + bytes)."""
        assert Blob(b"hi").id == hashlib.sha256(b"blob 2\0hi").hexdigest()

    def test_same_bytes_different_type_differ(self) -> None:
        """The type is part of the hash."""
        assert content_hash("blob", b"[]") != content_hash("tree", b"[]")
        assert Tree().id == content_hash("tree", b"[]")

    def test_is_object_id(self) -> None:
        """Only 64 lowercase hex characters are ids."""
        assert is_object_id(ID)
        assert not is_object_id("A" * 64)
        assert not is_object_id("a" * 63)
        assert not is_object_id(None)

    def test_canonical_json_is_stable(self) -> None:
        """Key order does not change the bytes."""
        assert canonical_json({"b": 1, "a": "é"}) == canonical_json({"a": "é", "b": 1})
        assert canonical_json({"b": 1, "a": "é"}) == '{"a":"é","b":1}'.encode()

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_canonical_json_rejects_non_json_numbers(self, value: float) -> None:
        """NaN and infinities have no JSON form."""
        with pytest.raises(ValueError):
            canonical_json({"x": value})


class TestTree:
    """Tree ordering, validation and serialization."""

    def test_entries_sorted_and_order_independent(self) -> None:
        """The same entries in any order give the same tree."""
        a, b = TreeEntry("a", "blob", ID), TreeEntry("b", "tree", ID)
        assert Tree((b, a)) == Tree((a, b))
        assert Tree((b, a)).entries == (a, b)

    def test_duplicate_names_rejected(self) -> None:
        """Entry names are unique."""
        with pytest.raises(CorruptObjectError):
            Tree((TreeEntry("a", "blob", ID), TreeEntry("a", "tree", ID)))

    @pytest.mark.parametrize(
        ("name", "type_", "id_"),
        [("", "blob", ID), ("a", "commit", ID), ("a", "blob", "short")],
    )
    def test_bad_entry_rejected(self, name: str, type_: str, id_: str) -> None:
        """Empty names, commit entries and malformed ids are refused."""
        with pytest.raises(CorruptObjectError):
            TreeEntry(name, type_, id_)  # type: ignore[arg-type]

    def test_any_name_round_trips(self) -> None:
        """Names may hold slashes, newlines and non-ASCII text."""
        tree = Tree((TreeEntry("a/b\nc é", "blob", ID),))
        assert Tree.deserialize(tree.serialize()) == tree

    def test_get(self) -> None:
        """get() finds an entry by name."""
        entry = TreeEntry("readme", "blob", ID)
        assert Tree((entry,)).get("readme") == entry
        assert Tree((entry,)).get("other") is None

    @pytest.mark.parametrize("data", [b"\xff", b"{}", b"[[1, 2]]", b"not json"])
    def test_corrupt_bytes(self, data: bytes) -> None:
        """Bytes that are not a list of [name, type, id] raise."""
        with pytest.raises(CorruptObjectError):
            Tree.deserialize(data)


class TestCommit:
    """Commit validation and serialization."""

    def test_round_trip_with_binary_payload(self) -> None:
        """The payload is opaque bytes, including blank lines."""
        commit = Commit(ID, ("b" * 64, "c" * 64), b"\n\nbinary\x00\xff")
        assert Commit.deserialize(commit.serialize()) == commit
        assert deserialize("commit", commit.serialize()) == commit

    def test_serialized_form(self) -> None:
        """Header lines, a blank line, then the payload."""
        commit = Commit(ID, ("b" * 64,), b"meta")
        assert commit.serialize() == f"tree {ID}\nparent {'b' * 64}\n\nmeta".encode()

    def test_parents_list_becomes_tuple(self) -> None:
        """Commits are hashable and compare equal whatever sequence type was passed."""
        assert Commit(ID, ["b" * 64]) == Commit(ID, ("b" * 64,))  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("tree", "parents"),
        [("short", ()), (ID, ("short",)), (ID, ("b" * 64, "b" * 64))],
    )
    def test_invalid_links_rejected(self, tree: str, parents: tuple[str, ...]) -> None:
        """Malformed ids and duplicate parents are refused."""
        with pytest.raises(CorruptObjectError):
            Commit(tree, parents)

    @pytest.mark.parametrize(
        "data",
        [
            f"tree {ID}".encode(),
            b"\xff\n\n",
            f"parent {ID}\n\n".encode(),
            f"tree {ID}\nauthor x\n\n".encode(),
        ],
    )
    def test_corrupt_bytes(self, data: bytes) -> None:
        """Missing blank line, non-ASCII header, wrong or unknown lines raise."""
        with pytest.raises(CorruptObjectError):
            Commit.deserialize(data)


def test_blob_round_trip() -> None:
    """A blob is its bytes."""
    assert deserialize("blob", b"x") == Blob(b"x")
