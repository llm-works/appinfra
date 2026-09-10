# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Config-source block for AppBuilder.

Declares where the app's config comes from (a ``ConfigSpec``), the
programmatic layer above the loaded file, and whether the resolved file is
watched for hot reload. App-only concerns; there is no standalone builder
behind this block.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self, TypedDict, Unpack

from ....config import AUTO, Auto, ConfigSpec
from ....config.spec import _resolve_origin
from ....dot_dict import DotDict
from .block import check_fields, close_on_error

if TYPE_CHECKING:
    from ..app import AppBuilder


class ConfigFields(TypedDict, total=False):
    """Keyword form of the config block; see ``ConfigConfigurer.__call__``."""

    namespace: str
    name: str
    origin: str | Path
    etc_dir: str
    filename: str
    path: str | Path
    overrides: Mapping[str, Any]
    hot_reload: bool
    debounce_ms: int


class ConfigConfigurer:
    """Config-source block: spec, programmatic overrides, hot reload.

    Two spellings write the same state. Chained::

        AppBuilder("myapp").config.with_spec("myorg", "myapp").with_hot_reload().done()
        AppBuilder("myapp").config.with_value("logging.level", "debug").done()

    Keyword, returning the AppBuilder directly::

        AppBuilder("myapp").config(namespace="myorg", name="myapp", hot_reload=True)
    """

    block_name = "config"

    def __init__(self, app_builder: AppBuilder):
        """Bind the block to its parent builder."""
        self._app_builder = app_builder

    def with_spec(
        self,
        namespace: str,
        name: str,
        *,
        origin: str | Path | Auto = AUTO,
        etc_dir: str = "etc",
        filename: str | Auto = AUTO,
        path: str | Path | None = None,
    ) -> Self:
        """Declare the config source per the config protocol.

        Builds a ``ConfigSpec`` from the same arguments: the base is
        ``<origin dir>/<etc_dir>/<filename>``, each part defaulting to rule 2
        (the module named after the config or the calling script, ``etc``,
        ``<name>.yaml``); ``path`` names the file outright. An explicit
        ``origin`` is also the include boundary, so a base whose includes
        climb above its ``etc/`` passes the directory they may reach. A
        relative ``origin`` anchors to this call's own file (``".."`` is
        one dir above it); an absolute path is used as-is. At setup the
        App resolves the spec against ``--etc-dir`` and ``--config`` (when
        exposed via ``.cli(config_file=True)``), the project-local
        walk-up, XDG overlays and the packaged base. See ``ConfigSpec``.
        """
        if origin is not None and not isinstance(origin, Auto):
            origin = _resolve_origin(origin, frame_depth=1)
        self._app_builder._config_spec = ConfigSpec(
            namespace,
            name,
            origin=origin,
            etc_dir=etc_dir,
            filename=filename,
            path=path,
        )
        return self

    def with_overrides(self, values: Mapping[str, Any]) -> Self:
        """Merge a mapping into the programmatic config layer.

        The layer sits above the loaded file and below CLI arguments, and is
        the whole config for apps built without a file source (tests,
        in-process hosts). Any mapping works, a plain ``dict`` included;
        repeated calls deep-merge.
        """
        self._app_builder._merge_overrides(values)
        return self

    def with_value(self, key: str, value: Any) -> Self:
        """Set one value in the programmatic layer by dotted path.

        ``with_value("logging.level", "debug")`` is
        ``with_overrides({"logging": {"level": "debug"}})``.
        """
        nested: Any = value
        for part in reversed(key.split(".")):
            nested = {part: nested}
        return self.with_overrides(nested)

    def with_hot_reload(self, enabled: bool = True, debounce_ms: int = 500) -> Self:
        """Watch the resolved config file and re-apply logging on change.

        Reloads log levels, display options and topic rules without a
        restart. Requires the ``watchdog`` extra (``appinfra[hotreload]``)
        and a config source declared on this builder.

        Raises:
            ValueError: if no config source has been declared.
        """
        builder = self._app_builder
        if builder._config_spec is None:
            raise ValueError(
                "with_hot_reload requires a config source: call with_spec() first"
            )
        if builder._config is None:
            builder._config = DotDict()
        config = builder._config
        if not hasattr(config, "logging"):
            config.logging = DotDict()  # type: ignore[attr-defined]
        # LifecycleManager reads logging.hot_reload from the merged config.
        config.logging.hot_reload = DotDict(  # type: ignore[attr-defined]
            enabled=enabled, debounce_ms=debounce_ms
        )
        return self

    def done(self) -> AppBuilder:
        """Return to the AppBuilder."""
        self._app_builder._close(self)
        return self._app_builder

    def __call__(self, **fields: Unpack[ConfigFields]) -> AppBuilder:
        """Keyword form of the block; returns the AppBuilder.

        ``namespace`` and ``name`` are required together and accept the
        same anchors as ``with_spec``; ``overrides`` and ``hot_reload`` map
        to the methods of the same name; ``debounce_ms`` only with
        ``hot_reload``.
        """
        with close_on_error(self._app_builder, self):
            check_fields("config", fields, ConfigFields.__annotations__)
            spec_keys = {"namespace", "name", "origin", "etc_dir", "filename", "path"}
            if spec_keys & fields.keys():
                if "namespace" not in fields or "name" not in fields:
                    raise ValueError("namespace and name are required together")
                origin: str | Path | Auto = fields.get("origin", AUTO)
                if origin is not None and not isinstance(origin, Auto):
                    origin = _resolve_origin(origin, frame_depth=1)
                self.with_spec(
                    fields["namespace"],
                    fields["name"],
                    origin=origin,
                    etc_dir=fields.get("etc_dir", "etc"),
                    filename=fields.get("filename", AUTO),
                    path=fields.get("path"),
                )
            if "overrides" in fields:
                self.with_overrides(fields["overrides"])
            if "debounce_ms" in fields and "hot_reload" not in fields:
                raise ValueError("debounce_ms requires hot_reload")
            if "hot_reload" in fields:
                self.with_hot_reload(
                    fields["hot_reload"], fields.get("debounce_ms", 500)
                )
        return self.done()
