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
) -> tuple[Path, Path]:
    """Resolve the v1 config file + include-authorization root in one call.

    Encapsulates the v1 config-protocol precedence chain:

    1. ``custom_etc_dir`` present (typically ``args.etc_dir`` from
       ``--etc-dir``) → ``(<custom_etc_dir>/<package>.yaml,
       <custom_etc_dir>)``. The user's explicit path IS the
       include-authorization root; sibling ``!include``s inside it resolve
       by default, anything outside is the user's ``allowed_paths``
       problem.
    2. Else first existing ``xdg_candidates(namespace, package)``
       → ``(<candidate>, include_root_for(base_config))``. Defensive;
       includes bound to the packaged base's directory.
    3. Else packaged base → ``(<base_config>, include_root_for(base_config))``.

    Existence is probed only on the XDG candidates. The custom path is
    trusted: this helper does not pre-validate that
    ``<custom_etc_dir>/<package>.yaml`` exists — ``Config(...)`` raises a
    clear ``FileNotFoundError`` at load time if it does not.

    Args:
        namespace: XDG namespace (e.g. ``"llm-works"``).
        package: package name (e.g. ``"llm-infer"``); used for the config
            filename ``<package>.yaml`` under ``--etc-dir`` and inside the
            XDG search set.
        base_config: absolute path to the packaged base config
            (e.g. ``.../llm_infer/etc/llm-infer.yaml``).
        custom_etc_dir: user's ``--etc-dir`` value if passed;
            ``None`` otherwise.

    Returns:
        ``(config_file, project_root)`` — both pass directly to
        ``Config(str(config_file), project_root=project_root)``.
    """
    if custom_etc_dir:
        etc = Path(str(custom_etc_dir)).expanduser().resolve()
        return (etc / f"{package}.yaml", etc)

    for candidate in xdg_candidates(namespace, package):
        if candidate.exists():
            return (candidate, include_root_for(base_config))

    base = Path(str(base_config)).expanduser().resolve()
    return (base, include_root_for(base_config))


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
