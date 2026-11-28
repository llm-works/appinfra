# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""What a runtime is configured with, in code or from a config section."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Any

from ..time.delta import InvalidDurationError, delta_to_secs

# The start methods a process task's child may use. Not fork: a running
# runtime always has threads, and a forked child can inherit a lock one of
# them held
METHODS = ("forkserver", "spawn")


@dataclass(frozen=True)
class ProcessConfig:
    """How a runtime's process tasks start and are made to end.

    Attributes:
        method: The multiprocessing start method of each child: forkserver
            forks it from a server that imported the main module once, spawn
            starts a fresh interpreter that imports it again.
        grace: Seconds a child that outlived its stop gets after SIGTERM, and
            again after SIGKILL.
    """

    method: str = "forkserver"
    grace: float = 2.0

    def __post_init__(self) -> None:
        """Refuse a method the runtime cannot start children with, and a
        grace that is not a positive number of seconds.

        Raises:
            ValueError: If either is invalid.
        """
        if self.method == "fork":
            raise ValueError(
                "method 'fork' is not supported: a running runtime has threads, "
                "and a forked child can deadlock on a lock one of them held"
            )
        if self.method not in METHODS:
            raise ValueError(f"method must be one of {METHODS}, not {self.method!r}")
        _check_positive("grace", self.grace)


@dataclass(frozen=True)
class Config:
    """What a runtime is configured with; every field has a default.

    Attributes:
        process: How its process tasks start and are made to end.
        stop_timeout: Seconds stop() waits for the tasks when called without
            a timeout.
    """

    process: ProcessConfig = field(default_factory=ProcessConfig)
    stop_timeout: float = 5.0

    def __post_init__(self) -> None:
        """Refuse a stop_timeout that is not a positive number of seconds.

        Raises:
            ValueError: If it is not.
        """
        _check_positive("stop_timeout", self.stop_timeout)

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> Config:
        """The config a section gives, a key left out keeping its default:
        process.method, process.grace and stop_timeout, durations as seconds
        or strings such as "500ms", "2s" or "1m30s".

        Raises:
            ValueError: If a key is unknown, or a value invalid.
        """
        _check_keys("runtime", section, {f.name for f in fields(cls)})
        process = section.get("process") or {}
        _check_keys("runtime process", process, {f.name for f in fields(ProcessConfig)})
        given: dict[str, Any] = {}
        if "method" in process:
            given["method"] = process["method"]
        if "grace" in process:
            given["grace"] = _seconds("grace", process["grace"])
        if "stop_timeout" not in section:
            return cls(process=ProcessConfig(**given))
        stop_timeout = _seconds("stop_timeout", section["stop_timeout"])
        return cls(process=ProcessConfig(**given), stop_timeout=stop_timeout)


def _check_positive(name: str, value: float) -> None:
    """Refuse *value*, the field *name*, unless it is a positive number: a
    bool is not one."""
    if isinstance(value, bool) or not value > 0:
        raise ValueError(f"{name} must be a positive number of seconds, not {value!r}")


def _check_keys(where: str, section: Mapping[str, Any], known: set[str]) -> None:
    """Refuse a key of *section* outside *known*: a misspelt one would
    otherwise leave its default in place without a word."""
    unknown = sorted(set(section) - known)
    if unknown:
        raise ValueError(f"unknown {where} keys {unknown}; known: {sorted(known)}")


def _seconds(name: str, value: Any) -> float:
    """*value* in seconds: a number, or a duration string such as "2s"."""
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be seconds or a duration, not {value!r}")
    if isinstance(value, int | float):
        return float(value)
    try:
        return delta_to_secs(str(value))
    except InvalidDurationError as e:
        raise ValueError(f"{name} must be seconds or a duration, not {value!r}") from e


# The config of a runtime given none; frozen, so one instance serves every one
DEFAULT_CONFIG = Config()
