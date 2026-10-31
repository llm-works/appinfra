# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Internal utilities for YAML processing."""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..envelope import Envelope

# A ${path} reference. Restricted to config key characters (alphanumeric, dot,
# underscore) to prevent ReDoS.
REFERENCE_PATTERN = re.compile(r"\$\{([a-zA-Z0-9_.]+)\}")


def substitute_references(text: str, lookup: Callable[[re.Match[str]], Any]) -> Any:
    """
    Replace each ``${path}`` in ``text`` with the value ``lookup`` returns for its match.

    Values are spliced in as ``str(value)``. Text that references an
    ``Envelope`` is a secret as a whole: the result is an ``Envelope`` of the
    substituted text, so a URL built from a secret password travels on masked
    to the code that reveals it.
    """
    secret = False

    def splice(match: re.Match[str]) -> str:
        nonlocal secret
        value = lookup(match)
        if isinstance(value, Envelope):
            secret = True
            return value.reveal()
        return str(value)

    result = REFERENCE_PATTERN.sub(splice, text)
    return Envelope(result) if secret else result


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
