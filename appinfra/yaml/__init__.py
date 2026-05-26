"""
Custom YAML loader with enhanced key handling and include support.

This module provides a custom YAML loader that automatically converts
certain key types to strings for better compatibility and supports
file inclusion via the !include tag and secrets validation via !secret tag.

Public API:
    load: Load YAML with include support and optional source tracking
    Loader: Custom YAML loader class
    deep_merge: Deep merge two dictionaries
    ErrorContext: Context for YAML error reporting
    IncludeContext: Extended context for !include processing
    SecretLiteralWarning: Warning for literal secrets
"""

from dataclasses import dataclass, replace
from io import StringIO
from pathlib import Path
from typing import Any, Literal, overload

from ._include import (
    _create_document_error_context,
    _extract_section_data,
    _filter_source_map_for_section,
    _preprocess_document_includes,
    _resolve_include_path_standalone,
    _validate_include_standalone,
)
from .loader import Loader, preprocess_deep_tags
from .types import (
    DeepMergeWrapper,
    ErrorContext,
    IncludeContext,
    ResetValue,
    SecretLiteralWarning,
)


@dataclass(frozen=True, slots=True)
class _LoadContext:
    """Immutable bag of per-load() parameters.

    Threaded through every internal helper so signatures don't have to repeat
    the 7-field bag. Recursion (when entering an included file) builds a fresh
    context via ``dataclasses.replace`` with the new ``current_file`` and
    extended ``include_chain``; everything else carries over verbatim.
    """

    current_file: Path | None
    include_chain: set[Path]
    merge_strategy: str
    track_sources: bool
    project_root: Path | None
    max_include_depth: int
    env_overrides: dict[str, str] | None


# Public API exports
__all__ = [
    "load",
    "load_file",
    "Loader",
    "deep_merge",
    "DeepMergeWrapper",
    "ResetValue",
    "ErrorContext",
    "IncludeContext",
    "SecretLiteralWarning",
]


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """
    Deep merge two dictionaries, with override taking precedence.

    ResetValue wrappers in override bypass merging - the wrapped value
    replaces the base value entirely.

    Args:
        base: Base dictionary to merge into
        override: Dictionary with values to override base

    Returns:
        Merged dictionary
    """
    result = base.copy()
    for key, value in override.items():
        # ResetValue bypasses merging - use wrapped value directly
        if isinstance(value, ResetValue):
            result[key] = value.value
        elif (
            key in result and isinstance(result[key], dict) and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _apply_section_filter(
    ctx: _LoadContext,
    data: Any,
    source_map: dict[str, Path | None],
    section_path: str,
    include_path: Path,
) -> tuple[Any, dict[str, Path | None]]:
    """Extract section from data and filter source map if applicable."""
    if not section_path or data is None:
        return data, source_map
    data = _extract_section_data(
        data, section_path, str(include_path), env_overrides=ctx.env_overrides
    )
    if ctx.track_sources:
        source_map = _filter_source_map_for_section(source_map, section_path)
    return data, source_map


def _resolve_and_validate_include(
    ctx: _LoadContext,
    include_path_str: str,
    line: int | None,
    optional: bool,
) -> Path | None:
    """Resolve and validate include path. Returns None if optional and missing."""
    err_ctx = _create_document_error_context(ctx.current_file, line)
    resolved_root = ctx.project_root.resolve() if ctx.project_root else None
    include_path = _resolve_include_path_standalone(
        include_path_str, ctx.current_file, err_ctx
    )
    file_exists = _validate_include_standalone(
        include_path,
        ctx.include_chain,
        resolved_root,
        ctx.max_include_depth,
        err_ctx,
        optional=optional,
    )
    return include_path if file_exists else None


def _load_document_include(
    ctx: _LoadContext,
    include_spec: str,
    line: int | None = None,
    optional: bool = False,
) -> tuple[Any, dict[str, Path | None]]:
    """Load a document-level include file. Returns (None, {}) if optional and missing."""
    include_path_str, section_path = (
        include_spec.split("#", 1) if "#" in include_spec else (include_spec, "")
    )
    include_path = _resolve_and_validate_include(ctx, include_path_str, line, optional)
    if include_path is None:
        return None, {}

    data, source_map = _load_include_file(ctx, include_path)
    return _apply_section_filter(ctx, data, source_map, section_path, include_path)


def _load_include_file(
    ctx: _LoadContext, include_path: Path
) -> tuple[Any, dict[str, Path | None]]:
    """
    Load an included YAML file by recursing into the loader with a fresh
    context pointing at the included file (and the chain extended to include
    it, for circular-include detection).
    """
    inner = replace(
        ctx, current_file=include_path, include_chain=ctx.include_chain | {include_path}
    )
    with open(include_path) as f:
        result = _load_with_context(inner, f)

    if ctx.track_sources:
        return result  # type: ignore[return-value]
    return result, {}


def _validate_include_data(include_data: Any, include_spec: str, line_num: int) -> None:
    """Validate that include data is a dict."""
    if not isinstance(include_data, dict):
        raise ValueError(
            f"Document-level include '{include_spec}' (line {line_num}) must resolve "
            f"to a mapping, got {type(include_data).__name__}"
        )


def _merge_document_includes(
    ctx: _LoadContext,
    doc_include_paths: list[tuple[str, int, bool]],
) -> tuple[dict[str, Any] | None, dict[str, Path | None]]:
    """Load and merge all document-level includes."""
    merged_data: dict[str, Any] | None = None
    merged_source_map: dict[str, Path | None] = {}

    for include_spec, line_num, is_optional in doc_include_paths:
        include_data, source_map = _load_document_include(
            ctx, include_spec, line=line_num, optional=is_optional
        )
        if include_data is None:
            continue

        _validate_include_data(include_data, include_spec, line_num)
        merged_data = (
            deep_merge(merged_data, include_data) if merged_data else include_data
        )
        if ctx.track_sources:
            merged_source_map.update(source_map)

    return merged_data, merged_source_map


def _parse_yaml_content(
    ctx: _LoadContext, content: str
) -> tuple[Any, dict[str, Path | None]]:
    """Parse YAML content using the Loader.

    Loader is constructed with kwargs from the context — Loader keeps its
    explicit-kwarg constructor because it inherits from yaml.SafeLoader, whose
    __init__ already takes ``stream`` from the PyYAML hierarchy.
    """
    loader = Loader(
        StringIO(content),
        current_file=ctx.current_file,
        include_chain=ctx.include_chain,
        merge_strategy=ctx.merge_strategy,
        track_sources=ctx.track_sources,
        project_root=ctx.project_root.resolve() if ctx.project_root else None,
        max_include_depth=ctx.max_include_depth,
        env_overrides=ctx.env_overrides,
    )
    try:
        data = loader.get_single_data()
        source_map = loader.source_map if ctx.track_sources else {}
        return data, source_map
    finally:
        loader.dispose()


def _merge_data_and_sources(
    merged_data: dict[str, Any] | None,
    main_data: Any,
    merged_source_map: dict[str, Path | None],
    main_source_map: dict[str, Path | None],
) -> tuple[Any, dict[str, Path | None]]:
    """
    Merge document-level includes with main document data.

    Document-level includes provide defaults; main document overrides.

    Args:
        merged_data: Data merged from document-level includes
        main_data: Data from the main document
        merged_source_map: Source map from document-level includes
        main_source_map: Source map from main document

    Returns:
        Tuple of (final_data, final_source_map)
    """
    if merged_data is not None and main_data is not None:
        if isinstance(main_data, dict):
            final_data = deep_merge(merged_data, main_data)
        else:
            final_data = main_data  # Non-dict takes full precedence
    elif merged_data is not None:
        final_data = merged_data
    else:
        final_data = main_data

    final_source_map = {**merged_source_map, **main_source_map}
    return final_data, final_source_map


def _init_include_chain(
    current_file: Path | None, _include_chain: set[Path] | None
) -> set[Path]:
    """Initialize include chain, adding current file if provided."""
    chain = _include_chain if _include_chain is not None else set()
    if current_file is not None:
        chain = chain | {current_file.resolve()}
    return chain


def load(
    stream: Any,
    current_file: Path | None = None,
    merge_strategy: str = "replace",
    track_sources: bool = False,
    project_root: Path | None = None,
    max_include_depth: int = 10,
    env_overrides: dict[str, str] | None = None,
    _include_chain: set[Path] | None = None,
) -> Any | tuple[Any, dict[str, Path | None]]:
    """
    Load YAML with include support and optional source tracking.

    Supports key-level includes (`database: !include "db.yaml"`) and document-level
    includes (`!include "./base.yaml"` at line start). Document-level includes provide
    defaults; main document content overrides.

    Args:
        stream: File object or string to load YAML from
        current_file: Path to current file (for relative includes)
        merge_strategy: Strategy for merging - "replace" or "merge"
        track_sources: If True, return (data, source_map) tuple
        project_root: Restrict includes to this directory
        max_include_depth: Max nested include depth (default: 10)
        env_overrides: Optional explicit name→value map applied during
            include-time `${var}` substitution. Callers that want env-aware
            substitution (e.g. Config) pass an explicit map; standalone callers
            leave this None and get raw YAML values only.
    """
    ctx = _LoadContext(
        current_file=current_file,
        include_chain=_init_include_chain(current_file, _include_chain),
        merge_strategy=merge_strategy,
        track_sources=track_sources,
        project_root=project_root,
        max_include_depth=max_include_depth,
        env_overrides=env_overrides,
    )
    return _load_with_context(ctx, stream)


def _load_with_context(
    ctx: _LoadContext, stream: Any
) -> Any | tuple[Any, dict[str, Path | None]]:
    """Context-aware body of load(). Re-entered by _load_include_file with a
    derived context when recursing into an included file.
    """
    content = stream.read() if hasattr(stream, "read") else str(stream)
    content = preprocess_deep_tags(content)
    remaining_content, doc_include_paths = _preprocess_document_includes(content)

    merged_data, merged_source_map = _merge_document_includes(ctx, doc_include_paths)
    main_data, main_source_map = _parse_yaml_content(ctx, remaining_content)
    final_data, final_source_map = _merge_data_and_sources(
        merged_data, main_data, merged_source_map, main_source_map
    )

    return (final_data, final_source_map) if ctx.track_sources else final_data


@overload
def load_file(
    path: str | Path,
    merge_strategy: str = ...,
    track_sources: Literal[False] = ...,
    project_root: Path | None = ...,
    max_include_depth: int = ...,
    optional: bool = ...,
) -> Any: ...


@overload
def load_file(
    path: str | Path,
    merge_strategy: str = ...,
    track_sources: Literal[True] = ...,
    project_root: Path | None = ...,
    max_include_depth: int = ...,
    optional: bool = ...,
) -> tuple[Any, dict[str, Path | None]]: ...


def load_file(
    path: str | Path,
    merge_strategy: str = "replace",
    track_sources: bool = False,
    project_root: Path | None = None,
    max_include_depth: int = 10,
    optional: bool = False,
) -> Any | tuple[Any, dict[str, Path | None]]:
    """
    Load YAML from a file with automatic file context for includes.

    Convenience wrapper around load() that sets up current_file automatically,
    enabling relative path resolution for !include and !include? directives.

    Args:
        path: Path to YAML file
        merge_strategy: Strategy for merging - "replace" or "merge"
        track_sources: If True, return (data, source_map) tuple
        project_root: Restrict includes to this directory
        max_include_depth: Max nested include depth (default: 10)
        optional: If True, return empty dict (or ({}, {}) with track_sources)
            when file doesn't exist instead of raising FileNotFoundError

    Example:
        config = load_file('etc/config.yaml')
        optional_config = load_file('overrides.yaml', optional=True)
    """
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as f:
            return load(
                f,
                current_file=path,
                merge_strategy=merge_strategy,
                track_sources=track_sources,
                project_root=project_root,
                max_include_depth=max_include_depth,
            )
    except FileNotFoundError:
        if optional:
            return ({}, {}) if track_sources else {}
        raise
