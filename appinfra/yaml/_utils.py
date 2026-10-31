# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Internal utilities for YAML processing."""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..errors import EmbeddedSecretError
from ..security.envelope import Envelope

# A ${path} reference. Restricted to config key characters (alphanumeric, dot,
# underscore) to prevent ReDoS.
REFERENCE_PATTERN = re.compile(r"\$\{([a-zA-Z0-9_.]+)\}")


def substitute_references(text: str, lookup: Callable[[re.Match[str]], Any]) -> Any:
    """
    Replace each ``${path}`` in ``text`` with the value ``lookup`` returns for its match.

    A text that is one reference and nothing else yields an ``Envelope`` as
    itself, so a secret travels on to the code that reveals it. Any other
    value is spliced in as ``str(value)``. An ``Envelope`` inside a larger
    string raises ``EmbeddedSecretError``: its ``str()`` is its mask.
    """
    whole = REFERENCE_PATTERN.fullmatch(text)
    if whole is not None:
        value = lookup(whole)
        return value if isinstance(value, Envelope) else str(value)

    def splice(match: re.Match[str]) -> str:
        value = lookup(match)
        if isinstance(value, Envelope):
            raise EmbeddedSecretError(match.group(1))
        return str(value)

    return REFERENCE_PATTERN.sub(splice, text)


def _file_exists(path: Path) -> bool:
    """
    Check if a file exists, letting permission/access errors propagate.

    Args:
        path: Path to check

    Returns:
        True if file exists, False if file not found.

    Raises:
        PermissionError: If parent directory is not accessible.
        OSError: For other filesystem errors.
    """
    # path.exists() returns False for missing files and raises for access errors
    # Don't catch exceptions - let PermissionError etc propagate as real problems
    return path.exists()


def _normalize_allowed_paths(
    entries: list[Path | str] | None,
) -> frozenset[Path]:
    """Normalize an `allowed_paths` list into the resolved set the loader
    checks membership against.

    Each entry is expanded (~) and resolved to an absolute path. `None` and
    empty list both become the empty set — no bypass entries.
    """
    if not entries:
        return frozenset()
    return frozenset(Path(str(e)).expanduser().resolve() for e in entries)
