# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Type definitions, patterns, and warning classes for YAML processing.

This module contains:
- ErrorContext and IncludeContext dataclasses for error reporting
- Regex pattern for document-level !include directives
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ErrorContext:
    """Context for YAML error reporting with file location information."""

    current_file: Path | None = None
    line: int | None = None
    column: int | None = None

    def format_location(self) -> str:
        """Format file and position for error messages."""
        parts = []
        if self.current_file:
            parts.append(f"in '{self.current_file}'")
        if self.line is not None:
            # YAML lines are 0-indexed, display as 1-indexed
            parts.append(f"line {self.line + 1}")
        if self.column is not None:
            parts.append(f"column {self.column + 1}")
        return ", ".join(parts) if parts else "unknown location"


@dataclass(frozen=True)
class IncludeContext(ErrorContext):
    """Extended context for !include directive processing."""

    include_chain: frozenset[Path] = frozenset()
    origin: Path | None = None
    max_include_depth: int = 10
    allowed_paths: frozenset[Path] = frozenset()


# Pattern for document-level !include directives (at column 0)
# Matches: !include "./path.yaml" or !include '/path.yaml' or !include path.yaml
# Also matches: !include? for optional includes (return {} if file missing)
# Optionally with section anchor: !include "./path.yaml#section"
# Optionally with trailing comment: !include "./path.yaml"  # comment
# Groups: (1) optional marker '?', (2) double-quoted path, (3) single-quoted path,
#         (4) unquoted path
DOCUMENT_INCLUDE_PATTERN = re.compile(
    r"^!include(\??)\s+"  # Capture optional '?' marker
    r'(?:"([^"]+)"|\'([^\']+)\'|(\S+))'  # Quoted or unquoted path (greedy to include #fragment)
    r"\s*(?:#.*)?$"  # Optional trailing comment (for quoted paths; unquoted paths capture # as part of path)
)


class DeepMergeWrapper:
    """
    Wrapper to mark data for deep merging with YAML merge keys (<<).

    When used with the !deep tag, signals that the wrapped data should be
    deep-merged into the parent mapping instead of shallow-merged.

    With override=False (default): document values win (inheritance pattern).
    With override=True: merged values win (overlay pattern).
    """

    __slots__ = ("data", "override")

    def __init__(self, data: dict[Any, Any], override: bool = False) -> None:
        """
        Initialize wrapper with data to deep merge.

        Args:
            data: Dictionary data to be deep merged. Must be a dict.
            override: If True, this data wins over document values.
                     If False, document values win (default).

        Raises:
            TypeError: If data is not a dictionary.
        """
        if not isinstance(data, dict):
            raise TypeError(
                f"!deep tag requires a mapping (dict), got {type(data).__name__}. "
                "Use !deep with anchors or includes that resolve to mappings."
            )
        self.data = data
        self.override = override

    def __repr__(self) -> str:
        if self.override:
            return f"DeepMergeWrapper({self.data!r}, override=True)"
        return f"DeepMergeWrapper({self.data!r})"


class DeepMergeDict(dict[Any, Any]):
    """
    Dict subclass that signals deep merge behavior in YAML merge keys.

    Used by !include to mark included dicts for deep merging. Unlike
    DeepMergeWrapper, this is a real dict so it works in all contexts
    (not just merge keys).
    """


class ResetValue:
    """
    Wrapper to mark a value for complete replacement (no merging).

    When used with the !reset tag, signals that this value should completely
    replace any inherited value, bypassing deep merge behavior.

    Example:
        # base.yaml has: options: {a: 1, b: 2}
        config:
          <<: !include "base.yaml"   # Deep merges by default
          options: !reset {c: 3}     # Replaces entirely: options = {c: 3}

    Without !reset, the result would be: options = {a: 1, b: 2, c: 3}
    With !reset, the result is: options = {c: 3}
    """

    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        """Initialize with value to use as complete replacement."""
        self.value = value

    def __repr__(self) -> str:
        return f"ResetValue({self.value!r})"
