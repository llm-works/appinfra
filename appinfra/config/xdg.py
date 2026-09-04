# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
XDG Base Directory Specification helpers for config-file discovery.

Provides `xdg_candidates`, a pure function that enumerates candidate config
file paths for a namespaced package in XDG load-order, plus `include_root_for`
and `resolve_config_source` — v1 config-protocol composition helpers that hide
the include-authorization boundary bookkeeping from consumer CLIs.
"""

from __future__ import annotations

import os
from pathlib import Path


def xdg_candidates(namespace: str, package: str) -> list[Path]:
    """Enumerate config candidates for ``<namespace>/<package>`` in XDG load-order.

    For each XDG dir in ``[$XDG_CONFIG_HOME, *$XDG_CONFIG_DIRS]``, emits the
    per-package file first, then the unified file:

    - ``D/<namespace>/<package>.yaml``
    - ``D/<namespace>/config.yaml``

    Defaults per XDG spec: ``XDG_CONFIG_HOME`` → ``~/.config``,
    ``XDG_CONFIG_DIRS`` → ``/etc/xdg``. Non-absolute ``XDG_CONFIG_HOME`` falls
    back to the default; empty and non-absolute entries in ``XDG_CONFIG_DIRS``
    are skipped. Pure function.
    """
    return [
        candidate
        for base in _xdg_config_dirs()
        for candidate in (
            base / namespace / f"{package}.yaml",
            base / namespace / "config.yaml",
        )
    ]


def include_root_for(base_config: Path | str) -> Path:
    """Return the include-authorization root for a bundled base config.

    Returns ``Path(base_config).parent`` — the base file's directory,
    typically the package's ``etc/`` dir. Pass as the ``project_root=``
    argument to ``Config`` when loading a user overlay that ``!include``s
    this base: the etc-dir boundary authorizes both the overlay's absolute
    ``!include <base>`` and the base's own relative sibling
    ``!include './...'`` directives, and no more — the tightest scope that
    still works.

    Pass a broader ancestor (e.g. ``Path(base_config).parent.parent`` for
    the package root) explicitly when the base's includes reach files
    outside ``etc/``; that call is intentional, not this helper's job.

    Example::

        BASE_CONFIG = Path(__file__).parent / "etc" / "myapp.yaml"
        Config(overlay, project_root=include_root_for(BASE_CONFIG))
    """
    return Path(str(base_config)).expanduser().resolve().parent


def resolve_config_source(
    namespace: str,
    package: str,
    base_config: Path | str,
    custom_etc_dir: Path | str | None = None,
    custom_config: str | None = None,
) -> tuple[Path, Path]:
    """Resolve the v1 config file + include-authorization root in one call.

    Encapsulates the v1 config-protocol precedence chain:

    1. ``custom_config`` is a direct path (absolute, or starts with
       ``./`` / ``../``) → ``(<resolved>, <resolved>.parent)``.
       ``custom_etc_dir`` is ignored; matches non-spec-mode's
       ``_load_direct_config`` semantics.
    2. ``custom_config`` is a bare filename →
       ``(<custom_etc_dir>/<custom_config>, <custom_etc_dir>)`` if
       ``custom_etc_dir`` is set, else
       ``(cwd/<custom_config>, cwd)``. Matches non-spec cases 2 and 3.
    3. ``custom_etc_dir`` present without ``custom_config`` →
       ``(<custom_etc_dir>/<package>.yaml, <custom_etc_dir>)``. The user's
       explicit path IS the include-authorization root; sibling
       ``!include``s inside it resolve by default, anything outside is the
       user's ``allowed_paths`` problem.
    4. Else first existing ``xdg_candidates(namespace, package)``
       → ``(<candidate>, include_root_for(base_config))``. Defensive;
       includes bound to the packaged base's directory.
    5. Else packaged base → ``(<base_config>, include_root_for(base_config))``.

    ``custom_config`` always bypasses XDG discovery and the packaged-base
    fallback (no name-comparison special case — matches non-spec-mode
    convention). Existence is probed only on the XDG candidates. Direct
    paths are trusted: ``Config(...)`` raises a clear ``FileNotFoundError``
    at load time if the file does not exist.

    Args:
        namespace: XDG namespace (e.g. ``"llm-works"``).
        package: package name (e.g. ``"llm-infer"``); used for the config
            filename ``<package>.yaml`` under ``--etc-dir`` and inside the
            XDG search set.
        base_config: absolute path to the packaged base config
            (e.g. ``.../llm_infer/etc/llm-infer.yaml``).
        custom_etc_dir: user's ``--etc-dir`` value if passed;
            ``None`` otherwise.
        custom_config: user's ``--config`` value if passed; ``None``
            otherwise. When set, XDG discovery and packaged-base fallback
            are skipped.

    Returns:
        ``(config_file, project_root)`` — both pass directly to
        ``Config(str(config_file), project_root=project_root)``.
    """
    if custom_config is not None:
        return _resolve_custom_config(custom_config, custom_etc_dir)

    if custom_etc_dir is not None:
        etc = Path(str(custom_etc_dir)).expanduser().resolve()
        return (etc / f"{package}.yaml", etc)

    for candidate in xdg_candidates(namespace, package):
        if candidate.exists():
            return (candidate, include_root_for(base_config))

    base = Path(str(base_config)).expanduser().resolve()
    return (base, include_root_for(base_config))


def _resolve_custom_config(
    custom_config: str, custom_etc_dir: Path | str | None
) -> tuple[Path, Path]:
    """Resolve ``--config`` under precedence rules 1 and 2.

    Direct path (absolute, or explicit relative ``./`` / ``../``) → load
    directly, ``--etc-dir`` ignored. Bare filename → compose with
    ``--etc-dir`` if passed, else cwd.
    """
    if _is_direct_path(custom_config):
        raw = Path(custom_config)
        raw_str = str(raw)
        if raw_str == "~" or raw_str.startswith("~/"):
            raw = raw.expanduser()
        resolved = (raw if raw.is_absolute() else Path.cwd() / raw).resolve()
        return (resolved, resolved.parent)

    base_dir = (
        Path(str(custom_etc_dir)).expanduser().resolve()
        if custom_etc_dir is not None
        else Path.cwd()
    )
    return (base_dir / custom_config, base_dir)


def _is_direct_path(config: str) -> bool:
    """Direct path if absolute, ``./``, ``../``, or ``~/``-prefixed.

    Matches non-spec ``_is_direct_path`` (see ``appinfra/app/core/app.py``)
    with a small addition for tilde-prefixed paths — ``--etc-dir`` already
    expands ``~`` explicitly (see ``TestResolveConfigSource.
    test_custom_etc_dir_expands_tilde``), so ``--config ~/x.yaml`` is
    likewise treated as an absolute path rather than a bare filename.
    Only ``~/...`` or ``~`` alone are matched; ``~username`` is not a
    valid expanduser target and would raise RuntimeError.
    """
    return (
        Path(config).is_absolute()
        or config.startswith(("./", "../", "~/"))
        or config == "~"
    )


def _xdg_config_dirs() -> list[Path]:
    """Return XDG config dirs in search order: user home first, then system dirs."""
    home_env = os.environ.get("XDG_CONFIG_HOME")
    if home_env and Path(home_env).is_absolute():
        home = home_env
    else:
        home = str(Path.home() / ".config")
    system = os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg"
    dirs = [Path(home)]
    for entry in system.split(":"):
        if not entry:
            continue
        path = Path(entry)
        if not path.is_absolute():
            continue
        dirs.append(path)
    return dirs
