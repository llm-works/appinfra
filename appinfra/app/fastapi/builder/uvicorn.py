# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Uvicorn configuration builder."""

from __future__ import annotations

from dataclasses import fields, replace
from typing import TYPE_CHECKING, Generic, Self, TypedDict, TypeVar, Unpack

from ..config.uvicorn import UvicornConfig

if TYPE_CHECKING:
    from .server import ServerBuilder

# The parent's concrete type, so done() on a subclass of ServerBuilder
# (the AppBuilder server scope) returns that subclass.
P = TypeVar("P", bound="ServerBuilder")


class UvicornFields(TypedDict, total=False):
    """Keyword form of the uvicorn block; keys mirror ``UvicornConfig``."""

    workers: int
    timeout_keep_alive: int
    limit_concurrency: int | None
    limit_max_requests: int | None
    backlog: int
    log_level: str
    access_log: bool
    ssl_keyfile: str | None
    ssl_certfile: str | None


_UVICORN_KEYS = frozenset(f.name for f in fields(UvicornConfig))


class UvicornConfigurer(Generic[P]):
    """
    Focused builder for Uvicorn configuration.

    Follows appinfra configurer pattern:
    - with_*() methods return self for chaining
    - done() returns parent builder
    - calling the block with keywords sets fields and returns the parent

    Example:
        server = (ServerBuilder(lg, "myapi")
            .uvicorn
                .with_workers(4)
                .with_log_level("info")
                .with_access_log()
                .done()
            .build())

        server = ServerBuilder(lg, "myapi").uvicorn(workers=4, access_log=True).build()
    """

    def __init__(self, parent: P) -> None:
        """
        Initialize configurer.

        Args:
            parent: Parent ServerBuilder instance
        """
        self._parent: P = parent
        self._config = parent._api.uvicorn  # the parent's, mutated in place

    def with_workers(self, workers: int) -> Self:
        """Set number of worker processes."""
        self._config.workers = workers
        return self

    def with_timeout_keep_alive(self, timeout: int) -> Self:
        """Set keep-alive timeout in seconds."""
        self._config.timeout_keep_alive = timeout
        return self

    def with_limit_concurrency(self, limit: int) -> Self:
        """Set max concurrent connections."""
        self._config.limit_concurrency = limit
        return self

    def with_limit_max_requests(self, limit: int) -> Self:
        """Set max requests per worker before restart."""
        self._config.limit_max_requests = limit
        return self

    def with_backlog(self, backlog: int) -> Self:
        """Set socket backlog size."""
        self._config.backlog = backlog
        return self

    def with_log_level(self, level: str) -> Self:
        """Set uvicorn log level (debug, info, warning, error, critical)."""
        self._config.log_level = level
        return self

    def with_access_log(self, enabled: bool = True) -> Self:
        """Enable/disable access logging."""
        self._config.access_log = enabled
        return self

    def with_ssl(self, keyfile: str, certfile: str) -> Self:
        """Configure SSL with key and certificate files."""
        self._config.ssl_keyfile = keyfile
        self._config.ssl_certfile = certfile
        return self

    def with_config(self, config: UvicornConfig) -> Self:
        """Set entire uvicorn config at once."""
        self._parent._api.uvicorn = replace(config)
        self._config = self._parent._api.uvicorn
        return self

    def done(self) -> P:
        """
        Finish uvicorn configuration and return to parent builder.

        Returns:
            Parent ServerBuilder instance for continued chaining
        """
        return self._parent

    def __call__(self, **fields: Unpack[UvicornFields]) -> P:
        """Keyword form of the block; sets ``UvicornConfig`` fields and returns the parent.

        Raises:
            TypeError: for a keyword that is not a ``UvicornConfig`` field.
        """
        unknown = set(fields) - _UVICORN_KEYS
        if unknown:
            raise TypeError(f"unknown uvicorn field(s): {', '.join(sorted(unknown))}")
        for key, value in fields.items():
            setattr(self._config, key, value)
        return self.done()
