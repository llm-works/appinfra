"""
Low-level include processing helpers.

This module contains standalone helper functions for !include processing:
- Document-level include preprocessing
- Path resolution and validation
- Section extraction from included data
- Variable resolution within data structures

All functions in this module are internal implementation details (prefixed with _)
and should not be imported directly by external code.
"""

import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from ._utils import _file_exists
from .types import DOCUMENT_INCLUDE_PATTERN, ErrorContext


def _preprocess_document_includes(
    content: str,
) -> tuple[str, list[tuple[str, int, bool]]]:
    """
    Extract document-level !include directives from YAML content.

    Document-level includes are !include tags at column 0 (no indentation)
    that should be merged with the rest of the document. This preprocessing
    step is necessary because YAML parses !include as a tagged scalar, which
    cannot coexist with other root-level content without a document separator.

    Supports both !include (required) and !include? (optional) directives.
    Optional includes return {} if the file is missing.

    Args:
        content: Raw YAML content

    Returns:
        Tuple of (remaining_content, list_of_(path, line_number, is_optional) tuples)
        Line numbers are 1-indexed for display.
        is_optional is True if the directive was !include? (file may be missing).

    Example:
        Input:
            !include "./base.yaml"
            !include? "./optional.yaml"

            name: app
            server:
              port: 8080

        Output:
            ('\\nname: app\\nserver:\\n  port: 8080',
             [('./base.yaml', 1, False), ('./optional.yaml', 2, True)])
    """
    lines = content.splitlines(keepends=True)
    include_paths: list[tuple[str, int, bool]] = []
    remaining_lines: list[str] = []

    for line_num, line in enumerate(lines, start=1):
        # Only check non-indented lines (document level)
        stripped = line.lstrip()
        if line == stripped:  # No leading whitespace = document level
            match = DOCUMENT_INCLUDE_PATTERN.match(line.rstrip())
            if match:
                # Group 1 is the optional marker '?', groups 2-4 are path variants
                is_optional = match.group(1) == "?"
                path = match.group(2) or match.group(3) or match.group(4)
                if path:
                    include_paths.append((path, line_num, is_optional))
                continue  # Don't add this line to remaining content

        remaining_lines.append(line)

    return "".join(remaining_lines), include_paths


def _resolve_include_path_standalone(
    include_path_str: str,
    current_file: Path | None,
    ctx: ErrorContext | None = None,
) -> Path:
    """
    Resolve include path to absolute path (standalone version for preprocessing).

    Args:
        include_path_str: Path string from !include directive
        current_file: Path to current file (for relative path resolution)
        ctx: Error context for location info (optional)

    Returns:
        Resolved absolute path

    Raises:
        yaml.YAMLError: If relative path cannot be resolved
    """
    include_path = Path(include_path_str)

    if not include_path.is_absolute():
        if current_file is None:
            location = f" ({ctx.format_location()})" if ctx else ""
            raise yaml.YAMLError(
                f"Cannot resolve relative include path '{include_path_str}' "
                f"without a current file context{location}"
            )
        return (current_file.parent / include_path).resolve()

    return include_path.resolve()


def _check_circular_include(
    include_path: Path,
    include_chain: set[Path],
    ctx: ErrorContext | None = None,
) -> None:
    """Raise error if circular include detected."""
    if include_path in include_chain:
        chain_str = " -> ".join(str(f) for f in include_chain)
        location = f" ({ctx.format_location()})" if ctx else ""
        raise yaml.YAMLError(
            f"Circular include detected: {chain_str} -> {include_path}{location}"
        )


def _check_include_depth(
    include_path: Path,
    include_chain: set[Path],
    max_depth: int,
    ctx: ErrorContext | None = None,
) -> None:
    """Raise error if include depth exceeds maximum."""
    if len(include_chain) + 1 > max_depth:
        chain_str = " -> ".join(str(f) for f in include_chain)
        location = f" ({ctx.format_location()})" if ctx else ""
        msg = (
            f"Include depth exceeds maximum of {max_depth}. "
            f"This could indicate a deeply nested include or recursive include pattern. "
            f"Include chain: {chain_str} -> {include_path}{location}"
        )
        raise yaml.YAMLError(msg)


def _check_file_exists(
    include_path: Path,
    ctx: ErrorContext | None = None,
) -> None:
    """Raise error if include file doesn't exist."""
    location = f" ({ctx.format_location()})" if ctx else ""
    if not _file_exists(include_path):
        raise yaml.YAMLError(f"Include file not found: {include_path}{location}")


def _check_project_root(
    include_path: Path,
    project_root: Path | None,
    ctx: ErrorContext | None = None,
) -> None:
    """Raise error if path is outside project root."""
    if project_root is None:
        return
    try:
        include_path.relative_to(project_root)
    except (ValueError, TypeError) as e:
        location = f" ({ctx.format_location()})" if ctx else ""
        msg = (
            f"Security: Include path '{include_path}' is outside project root "
            f"'{project_root}'. This could be a path traversal attack.{location}"
        )
        raise yaml.YAMLError(msg) from e


def _validate_include_standalone(
    include_path: Path,
    include_chain: set[Path],
    project_root: Path | None,
    max_include_depth: int,
    ctx: ErrorContext | None = None,
    optional: bool = False,
) -> bool:
    """
    Validate include path for circular dependencies, existence, and security.

    Args:
        include_path: Path to validate
        include_chain: Set of files already in the include chain
        project_root: Optional project root to restrict includes
        max_include_depth: Maximum allowed include depth
        ctx: Error context for location info
        optional: If True, missing files return False instead of raising

    Returns:
        True if file exists and passes validation, False if optional and missing.

    Raises:
        yaml.YAMLError: If validation fails (except for optional missing files)
    """
    # For optional includes, check existence first
    if optional and not _file_exists(include_path):
        return False

    _check_circular_include(include_path, include_chain, ctx)
    _check_include_depth(include_path, include_chain, max_include_depth, ctx)
    if not optional:
        _check_file_exists(include_path, ctx)
    _check_project_root(include_path, project_root, ctx)
    return True


def _extract_section_data(
    data: Any,
    section_path: str,
    location: str,
    resolve_variables: bool = True,
) -> Any:
    """
    Extract a specific section from data using dot-notation path.

    Shared implementation used by both document-level includes (_include.py)
    and inline includes (loader.py).

    Args:
        data: Data to extract from
        section_path: Dot-separated path (e.g., "server.http")
        location: Human-readable location for error messages (file path or context)
        resolve_variables: If True, resolve ${var} references before extraction

    Returns:
        Data at the specified section path

    Raises:
        yaml.YAMLError: If section path is invalid or not found
    """
    if not section_path:
        return data

    # Resolve variables within the full file context BEFORE extraction
    # This allows ${sibling.key} references to resolve before the section is extracted
    if resolve_variables and isinstance(data, dict):
        data = _resolve_variables_in_data(data, data, pass_through_undefined=True)

    current = data
    parts = section_path.split(".")

    for i, part in enumerate(parts):
        if not isinstance(current, dict):
            traversed = ".".join(parts[:i])
            raise yaml.YAMLError(
                f"Cannot navigate to '{section_path}': "
                f"'{traversed}' is not a mapping (got {type(current).__name__}) "
                f"({location})"
            )
        if part not in current:
            raise yaml.YAMLError(
                f"Section '{section_path}' not found in included file. "
                f"Available keys at this level: {list(current.keys())} "
                f"({location})"
            )
        current = current[part]

    return current


def _filter_source_map_for_section(
    source_map: dict[str, Path | None],
    section_path: str,
) -> dict[str, Path | None]:
    """
    Filter source map to only include keys under the section path.

    Args:
        source_map: Original source map
        section_path: Section path that was extracted

    Returns:
        Filtered source map with section prefix removed from keys
    """
    prefix = section_path + "."
    filtered_map: dict[str, Path | None] = {}

    for key, source in source_map.items():
        if key.startswith(prefix):
            new_key = key[len(prefix) :]
            filtered_map[new_key] = source
        elif key == section_path:
            filtered_map[""] = source

    return filtered_map


# Sentinel value to distinguish "key not found" from "value is None"
_NOT_FOUND = object()


def _get_value_by_path(data: dict[str, Any], path: str) -> Any:
    """Get value from nested dict using dot-separated path.

    Returns _NOT_FOUND sentinel if path doesn't exist.
    """
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _NOT_FOUND
        current = current[part]
    return current


def _resolve_variables_in_data(
    data: Any,
    context: dict[str, Any],
    pass_through_undefined: bool = True,
) -> Any:
    """
    Resolve ${var} patterns in data using context dict.

    Resolution is scoped to the context (typically the full included file).
    Undefined variables are passed through for Config._resolve() to handle.
    Single-pass resolution (no recursive expansion) to prevent infinite loops.
    """
    if isinstance(data, dict):
        return {
            k: _resolve_variables_in_data(v, context, pass_through_undefined)
            for k, v in data.items()
        }
    elif isinstance(data, list):
        return [
            _resolve_variables_in_data(item, context, pass_through_undefined)
            for item in data
        ]
    elif isinstance(data, str):

        def substitute(match: re.Match[str]) -> str:
            var_name = match.group(1)
            value = _get_value_by_path(context, var_name)
            if value is _NOT_FOUND:
                if pass_through_undefined:
                    return match.group(0)  # Keep original ${var}
                raise KeyError(f"Variable '{var_name}' not found")
            return str(value)

        # Same pattern as Config._resolve() for consistency
        return re.sub(r"\$\{([a-zA-Z0-9_.]+)\}", substitute, data)
    return data


def _create_document_error_context(
    current_file: Path | None, line: int | None
) -> ErrorContext:
    """Create ErrorContext for document-level include errors."""
    # Line is 1-indexed from preprocessing, convert to 0-indexed for ErrorContext
    return ErrorContext(
        current_file=current_file,
        line=line - 1 if line is not None else None,
        column=0,  # Document-level includes are always at column 0
    )
