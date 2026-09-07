# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Config-protocol identity and resolution for an application's configuration.

``ConfigSpec`` names where a config's packaged base lives (protocol rule 2:
``etc/<name>.yaml`` beside the code that ships it, the name being the
package name for a package) and resolves, against user overrides, the one
file to load (rule 6 precedence). The result is a ``ConfigFile``: the path
plus the include-authorization root that goes with it. A ``Config`` is then
loaded from that file; the spec never produces a ``Config`` itself.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import FrameType


class Auto:
    """Marker for a ``ConfigSpec`` part that is derived from the config name."""

    def __repr__(self) -> str:
        return "AUTO"


AUTO = Auto()


@dataclass(frozen=True)
class ConfigFile:
    """A located config file: the path to load and its include boundary.

    Produced by ``ConfigSpec.resolve``; accepted by ``Config`` as its source.

    Attributes:
        path: the file to load.
        project_root: include-authorization root for ``!include`` directives
            inside ``path``.
        rule: which precedence rule chose ``path`` (1-6, see
            ``ConfigSpec.resolve``). Diagnostic only.
    """

    path: Path
    project_root: Path
    rule: int


@dataclass(frozen=True, init=False)
class ConfigSpec:
    """Where a config lives, and how to resolve the file to load.

    The packaged base is ``<origin dir>/<etc_dir>/<filename>``. Every part
    has a rule-2 default derived from the config's name, so a conforming
    package needs only its identity::

        ConfigSpec("llm-works", "my-app")   # <my_app>/etc/my-app.yaml

    With ``origin`` left ``AUTO`` the anchor is the directory of the module
    named after the config (``"-"`` mapped to ``"_"``, found via
    ``importlib.util.find_spec`` without importing it), or, when no such
    module exists or holds the file, the directory of the calling script.
    The first candidate holding the file wins; neither existing is an
    error. Each keyword declares one deviation: ``origin`` anchors the
    layout on a file's directory or a directory; ``etc_dir`` names the
    directory under the origin, ``""`` for the origin itself, or an
    absolute directory; ``filename`` names the file. ``path`` names the
    file outright and excludes the other three.

    Attributes:
        namespace: XDG namespace (e.g. ``"llm-works"``).
        name: the config's name (e.g. ``"my-app"``): the base filename
            stem, the XDG entry ``<namespace>/<name>.yaml``, and what
            ``--etc-dir`` looks for. For a package, its package name.
        etc_dir: the declared etc directory, as given.
        base_config: absolute path to the packaged base config.

    Example::

        spec = ConfigSpec("llm-works", "my-app")
        config = Config(spec.resolve(etc_dir=args.etc_dir))
    """

    namespace: str
    name: str
    etc_dir: str
    base_config: Path

    def __init__(
        self,
        namespace: str,
        name: str,
        *,
        origin: str | Path | Auto = AUTO,
        etc_dir: str = "etc",
        filename: str | Auto = AUTO,
        path: str | Path | None = None,
    ) -> None:
        _check_identity(namespace, name)
        if origin is None or filename is None:
            raise TypeError("origin and filename take a value or AUTO, not None")
        if path is not None:
            if origin is not AUTO or filename is not AUTO or etc_dir != "etc":
                raise ValueError("path excludes origin, etc_dir and filename")
            base = Path(str(path)).expanduser().resolve()
        else:
            fname = f"{name}.yaml" if isinstance(filename, Auto) else filename
            if isinstance(origin, Auto):
                base = _locate_base(name, etc_dir, fname)
            else:
                base = _origin_dir(origin) / etc_dir / fname
        object.__setattr__(self, "namespace", namespace)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "etc_dir", etc_dir)
        object.__setattr__(self, "base_config", base)

    @property
    def include_root(self) -> Path:
        """Include-authorization root for the packaged base: its directory.

        The tightest boundary that authorizes both an overlay's absolute
        ``!include <base>`` and the base's own relative sibling includes.
        """
        return self.base_config.parent

    def xdg_candidates(self) -> list[Path]:
        """Enumerate user-override candidates in XDG load order.

        For each dir in ``[$XDG_CONFIG_HOME, *$XDG_CONFIG_DIRS]``: the
        per-config file ``<namespace>/<name>.yaml``, then the unified
        ``<namespace>/config.yaml``. Defaults per the XDG spec:
        ``~/.config`` and ``/etc/xdg``. Pure; probes nothing.
        """
        return [
            candidate
            for base in _xdg_config_dirs()
            for candidate in (
                base / self.namespace / f"{self.name}.yaml",
                base / self.namespace / "config.yaml",
            )
        ]

    def project_local(self) -> Path | None:
        """Walk up from cwd looking for ``<etc_dir>/<filename>``.

        Returns the first hit, or ``None``. Stops before ``$HOME`` and before
        the filesystem root, so home-dir dotfiles and system ``/etc`` are
        never picked up. An absolute ``etc_dir`` has no project-local form
        and yields ``None``. Never raises: an unresolvable cwd or home falls
        through to the XDG and packaged-base tiers.
        """
        filename = self.base_config.name
        if not filename or Path(self.etc_dir).is_absolute():
            return None
        try:
            current = Path.cwd().resolve()
            home = Path.home().resolve()
        except (OSError, RuntimeError):
            return None
        while current != home and current != current.parent:
            candidate = current / self.etc_dir / filename
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                pass  # permission denied or other I/O error: skip candidate
            current = current.parent
        return None

    def resolve(
        self,
        *,
        etc_dir: str | Path | None = None,
        config_file: str | None = None,
    ) -> ConfigFile:
        """Pick the one file to load under the rule-6 precedence chain.

        ``etc_dir`` and ``config_file`` are the operator's ``--etc-dir`` and
        ``--config`` values for this run; ``etc_dir`` here replaces the
        packaged etc directory declared on the spec.

        1. ``config_file`` is a direct path (absolute, ``./``, ``../``, ``~/``)
           → that file; ``etc_dir`` ignored; root is the file's parent.
        2. ``config_file`` is a bare filename → ``<etc_dir>/<name>`` if
           ``etc_dir`` is set, else ``<cwd>/<name>``; root is that directory.
        3. ``etc_dir`` alone → ``<etc_dir>/<filename>``; root is ``etc_dir``.
           The user's directory is the include boundary.
        4. Project-local: first ``<spec etc_dir>/<filename>`` walking up from
           cwd; root is that directory.
        5. First existing XDG candidate; root is ``include_root``.
        6. The packaged base; root is ``include_root``.

        ``config_file`` bypasses everything below it. Existence is probed
        only on tiers 4 and 5; direct paths are trusted and ``Config`` raises
        ``FileNotFoundError`` at load time if they do not exist.
        """
        if config_file is not None:
            return _resolve_custom_config(config_file, etc_dir)
        if etc_dir is not None:
            etc = Path(str(etc_dir)).expanduser().resolve()
            return ConfigFile(etc / self.base_config.name, etc, rule=3)
        local = self.project_local()
        if local is not None:
            return ConfigFile(local, local.parent, rule=4)
        for candidate in self.xdg_candidates():
            if candidate.exists():
                return ConfigFile(candidate, self.include_root, rule=5)
        return ConfigFile(self.base_config, self.include_root, rule=6)


def _check_identity(namespace: object, name: object) -> None:
    """Both identity parts are non-empty strings; a module object is the classic mistake."""
    if not isinstance(namespace, str) or not isinstance(name, str):
        raise TypeError(
            "namespace and name are strings; pass the config name, not a module object"
        )
    if not namespace or not name:
        raise ValueError("namespace and name must be non-empty")


def _locate_base(name: str, etc_dir: str, filename: str) -> Path:
    """AUTO origin: the first existing ``<dir>/<etc_dir>/<filename>``.

    Candidate directories, in order: the module named after the config,
    then the calling script's directory. Raises ``ValueError`` naming both
    when neither holds the file.
    """
    module_name = name.replace("-", "_")
    tried: list[str] = []
    for label, anchor in (
        (f"module {module_name!r}", _module_dir(module_name)),
        ("calling script", _caller_dir()),
    ):
        if anchor is None:
            tried.append(f"{label}: not found")
            continue
        candidate = anchor / etc_dir / filename
        if candidate.is_file():
            return candidate
        tried.append(f"{label}: {candidate} does not exist")
    raise ValueError(
        f"cannot locate the base config for {name!r} "
        f"({'; '.join(tried)}); pass origin= or path="
    )


def _module_dir(module_name: str) -> Path | None:
    """Directory of an importable top-level module, without importing it."""
    try:
        found = importlib.util.find_spec(module_name)
    except (ImportError, ValueError):
        return None
    if found is None or not found.has_location or found.origin is None:
        return None
    return Path(found.origin).resolve().parent


def _caller_dir() -> Path | None:
    """Directory of the nearest calling frame outside the appinfra package."""
    frame: FrameType | None = sys._getframe(1)
    while frame is not None:
        module = frame.f_globals.get("__name__", "")
        if module != "appinfra" and not module.startswith("appinfra."):
            file = frame.f_globals.get("__file__")
            return Path(file).resolve().parent if file else None
        frame = frame.f_back
    return None


def _origin_dir(origin: str | Path) -> Path:
    """Anchor directory for an explicit origin: the directory itself, or a file's parent."""
    resolved = Path(str(origin)).expanduser().resolve()
    return resolved if resolved.is_dir() else resolved.parent


def _resolve_custom_config(config_file: str, etc_dir: str | Path | None) -> ConfigFile:
    """Rules 1 and 2: a user-named file, direct path or bare filename."""
    if _is_direct_path(config_file):
        raw = Path(config_file)
        if config_file == "~" or config_file.startswith("~/"):
            raw = raw.expanduser()
        resolved = (raw if raw.is_absolute() else Path.cwd() / raw).resolve()
        return ConfigFile(resolved, resolved.parent, rule=1)
    base_dir = (
        Path(str(etc_dir)).expanduser().resolve() if etc_dir is not None else Path.cwd()
    )
    return ConfigFile(base_dir / config_file, base_dir, rule=2)


def _is_direct_path(config: str) -> bool:
    """Direct path if absolute, ``./``, ``../``, or ``~/``-prefixed, or ``~`` alone.

    Only ``~/...`` and ``~`` are treated as home-relative; ``~name`` is a bare
    filename because ``expanduser`` raises for unknown users.
    """
    return (
        Path(config).is_absolute()
        or config.startswith(("./", "../", "~/"))
        or config == "~"
    )


def _xdg_config_dirs() -> list[Path]:
    """XDG config dirs in search order: user home first, then system dirs.

    Non-absolute ``XDG_CONFIG_HOME`` falls back to ``~/.config``; empty and
    non-absolute ``XDG_CONFIG_DIRS`` entries are skipped, per the XDG spec.
    """
    home_env = os.environ.get("XDG_CONFIG_HOME")
    home = home_env if home_env and Path(home_env).is_absolute() else None
    dirs = [Path(home) if home else Path.home() / ".config"]
    system = os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg"
    for entry in system.split(":"):
        if entry and Path(entry).is_absolute():
            dirs.append(Path(entry))
    return dirs
