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

from io import StringIO
from pathlib import Path
from typing import Any

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

# Public API exports
__all__ = [
    "load",
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


def _load_document_include(
    include_spec: str,
    current_file: Path | None,
    include_chain: set[Path],
    merge_strategy: str,
    track_sources: bool,
    project_root: Path | None,
    max_include_depth: int,
    line: int | None = None,
) -> tuple[Any, dict[str, Path | None]]:
    """Load a document-level include file with section extraction support."""
    # Parse include path and optional section anchor
    include_path_str, section_path = (
        include_spec.split("#", 1) if "#" in include_spec else (include_spec, "")
    )

    ctx = _create_document_error_context(current_file, line)
    resolved_project_root = project_root.resolve() if project_root else None
    include_path = _resolve_include_path_standalone(include_path_str, current_file, ctx)
    _validate_include_standalone(
        include_path, include_chain, resolved_project_root, max_include_depth, ctx
    )

    # Load the included file recursively
    data, source_map = _load_include_file(
        include_path,
        include_chain,
        merge_strategy,
        track_sources,
        project_root,
        max_include_depth,
    )

    # Extract section if specified
    if section_path and data is not None:
        data = _extract_section_data(data, section_path, include_path)
        if track_sources:
            source_map = _filter_source_map_for_section(source_map, section_path)

    return data, source_map


def _load_include_file(
    include_path: Path,
    include_chain: set[Path],
    merge_strategy: str,
    track_sources: bool,
    project_root: Path | None,
    max_include_depth: int,
) -> tuple[Any, dict[str, Path | None]]:
    """
    Load an included YAML file.

    Args:
        include_path: Resolved path to the included file
        include_chain: Current include chain for circular detection
        merge_strategy: Strategy for merging includes
        track_sources: If True, track source files
        project_root: Optional project root for security validation
        max_include_depth: Maximum allowed include depth

    Returns:
        Tuple of (data, source_map)
    """
    new_chain = include_chain | {include_path}
    with open(include_path) as f:
        result = load(
            f,
            current_file=include_path,
            merge_strategy=merge_strategy,
            track_sources=track_sources,
            project_root=project_root,
            max_include_depth=max_include_depth,
            _include_chain=new_chain,
        )

    if track_sources:
        return result  # type: ignore[return-value]
    return result, {}


def _merge_document_includes(
    doc_include_paths: list[tuple[str, int]],
    current_file: Path | None,
    include_chain: set[Path],
    merge_strategy: str,
    track_sources: bool,
    project_root: Path | None,
    max_include_depth: int,
) -> tuple[dict[str, Any] | None, dict[str, Path | None]]:
    """
    Load and merge all document-level includes.

    Args:
        doc_include_paths: List of (include_path, line_number) tuples from preprocessing
        current_file: Path to current file for relative path resolution
        include_chain: Current include chain for circular detection
        merge_strategy: Strategy for merging includes
        track_sources: If True, track source files
        project_root: Optional project root for security validation
        max_include_depth: Maximum allowed include depth

    Returns:
        Tuple of (merged_data, merged_source_map)
    """
    merged_data: dict[str, Any] | None = None
    merged_source_map: dict[str, Path | None] = {}

    for include_spec, line_num in doc_include_paths:
        include_data, include_source_map = _load_document_include(
            include_spec,
            current_file,
            include_chain,
            merge_strategy,
            track_sources,
            project_root,
            max_include_depth,
            line=line_num,
        )

        if include_data is not None:
            if not isinstance(include_data, dict):
                raise ValueError(
                    f"Document-level include '{include_spec}' (line {line_num}) must resolve "
                    f"to a mapping, got {type(include_data).__name__}"
                )
            if merged_data is None:
                merged_data = include_data
            else:
                merged_data = deep_merge(merged_data, include_data)

            if track_sources:
                merged_source_map.update(include_source_map)

    return merged_data, merged_source_map


def _parse_yaml_content(
    content: str,
    current_file: Path | None,
    include_chain: set[Path],
    merge_strategy: str,
    track_sources: bool,
    project_root: Path | None,
    max_include_depth: int,
) -> tuple[Any, dict[str, Path | None]]:
    """
    Parse YAML content using the Loader.

    Args:
        content: YAML content string to parse
        current_file: Path to current file for relative path resolution
        include_chain: Current include chain for circular detection
        merge_strategy: Strategy for merging includes
        track_sources: If True, track source files
        project_root: Optional project root for security validation
        max_include_depth: Maximum allowed include depth

    Returns:
        Tuple of (data, source_map)
    """
    loader = Loader(
        StringIO(content),
        current_file=current_file,
        include_chain=include_chain,
        merge_strategy=merge_strategy,
        track_sources=track_sources,
        project_root=project_root.resolve() if project_root else None,
        max_include_depth=max_include_depth,
    )
    try:
        data = loader.get_single_data()
        source_map = loader.source_map if track_sources else {}
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
    """
    include_chain = _init_include_chain(current_file, _include_chain)
    content = stream.read() if hasattr(stream, "read") else str(stream)
    content = preprocess_deep_tags(content)
    remaining_content, doc_include_paths = _preprocess_document_includes(content)

    merged_data, merged_source_map = _merge_document_includes(
        doc_include_paths,
        current_file,
        include_chain,
        merge_strategy,
        track_sources,
        project_root,
        max_include_depth,
    )
    main_data, main_source_map = _parse_yaml_content(
        remaining_content,
        current_file,
        include_chain,
        merge_strategy,
        track_sources,
        project_root,
        max_include_depth,
    )
    final_data, final_source_map = _merge_data_and_sources(
        merged_data, main_data, merged_source_map, main_source_map
    )

    return (final_data, final_source_map) if track_sources else final_data
