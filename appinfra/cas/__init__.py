# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Content-addressed store: blobs, trees and commits, with named refs.

Objects are immutable and identified by the hash of their content. Refs are named
pointers to commits that move only with compare-and-set. Each repository of a store has
its own objects and refs.

Example:
    from appinfra.cas import Blob, FileStore, Tree, TreeEntry

    repo = FileStore("/var/lib/app/cas").repo("docs")
    blob = repo.put(Blob(b"hello"))
    tree = repo.put(Tree((TreeEntry("readme", "blob", blob),)))
    commit = repo.commit("main", tree, payload=b"first version")
"""

from .errors import (
    CasError,
    CorruptObjectError,
    InvalidNameError,
    ObjectNotFoundError,
    ObjectTypeError,
    RefConflictError,
)
from .file import FileStore
from .memory import MemoryStore
from .objects import (
    Blob,
    Commit,
    Object,
    ObjectType,
    Tree,
    TreeEntry,
    canonical_json,
    content_hash,
    is_object_id,
)
from .store import Repo, Store

__all__ = [
    # Objects
    "Object",
    "Blob",
    "Tree",
    "TreeEntry",
    "Commit",
    "ObjectType",
    "canonical_json",
    "content_hash",
    "is_object_id",
    # Stores
    "Store",
    "Repo",
    "MemoryStore",
    "FileStore",
    # Errors
    "CasError",
    "ObjectNotFoundError",
    "ObjectTypeError",
    "CorruptObjectError",
    "RefConflictError",
    "InvalidNameError",
]
