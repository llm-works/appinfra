# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Runtimes by name, from a config's runtime section."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..log import Logger
from .config import Config
from .runtime import Runtime


class Factory:
    """Runtimes by name, from the runtime section of a config: each
    runtime.<name> holds the fields of a Config, a key left out
    keeping its default. An INFRA_RUNTIME_<NAME>_... variable overrides a key
    the config declares, when *config* is an appinfra.config.Config, which
    applies the overrides as it loads.

    Example:
        # runtime:
        #   default: {}
        #   compute:
        #     process: {method: spawn, grace: 5s}
        #     stop_timeout: 30s
        rt = Factory(lg, config).create("compute")
    """

    def __init__(self, lg: Logger, config: Mapping[str, Any]) -> None:
        """Runtimes logging to *lg*, configured from *config*'s runtime section."""
        self._lg = lg
        self._section: Mapping[str, Any] | None = config.get("runtime")

    def config(self, name: str = "default") -> Config:
        """The config of the runtime named *name*, as a service runtime takes
        it too.

        Raises:
            KeyError: If the config has no runtime of that name.
            ValueError: If its section is invalid.
        """
        if self._section is None:
            raise KeyError(f"no runtime section in the config, for runtime {name!r}")
        if name not in self._section:
            known = ", ".join(repr(k) for k in sorted(self._section))
            raise KeyError(f"no runtime {name!r} in the config; it has {known}")
        return Config.from_config(self._section[name] or {})

    def create(self, name: str = "default") -> Runtime:
        """A runtime, not started, configured as the one named *name*.

        Raises:
            KeyError: If the config has no runtime of that name.
            ValueError: If its section is invalid.
        """
        return Runtime(self._lg, self.config(name))
