# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Dependencies: which services wait on which, and who may start when one of
them comes to run or leaves the runtime."""

from __future__ import annotations

from collections.abc import Mapping

from ..base import Service
from ..state import State
from .runner import Runner


class Dependencies:
    """The waiting services of a runtime and what each waits on.

    It reads *runners*, the runtime's services by name, for which exist and
    which run; what waits is its own. It starts and fails nothing: it says
    who may start and who no longer can.
    """

    def __init__(self, runners: Mapping[str, Runner]) -> None:
        self._runners = runners
        self._waiting: dict[str, tuple[str, ...]] = {}  # waiter -> its depends_on
        self._waiters: dict[str, set[str]] = {}  # dependency -> who waits on it

    def cycle(self, service: Service) -> list[str] | None:
        """The services a dependency cycle through *service* would pass, from
        *service* on; None if its dependencies lead back to it nowhere."""
        stack = [(dep, [service.name, dep]) for dep in service.depends_on]
        seen: set[str] = set()
        while stack:
            name, path = stack.pop()
            if name == service.name:
                return path[:-1]
            if name in seen or name not in self._runners:
                continue
            seen.add(name)
            deps = self._runners[name].service.depends_on
            stack.extend((dep, [*path, dep]) for dep in deps)
        return None

    def all_run(self, service: Service) -> bool:
        """True if every dependency of *service* runs."""
        return all(self._runs(dep) for dep in service.depends_on)

    def down(self, service: Service) -> str | None:
        """A dependency of *service* that does not run, whether it left the
        runtime or is in it but not RUNNING; None if every one runs."""
        return next((d for d in service.depends_on if not self._runs(d)), None)

    def missing(self, service: Service) -> str:
        """The first dependency of *service* that does not run; all of them if
        every one does."""
        for dep in service.depends_on:
            if not self._runs(dep):
                return dep
        return ", ".join(service.depends_on)

    def wait(self, service: Service) -> None:
        """*service* waits for its dependencies to run."""
        self._waiting[service.name] = tuple(service.depends_on)
        for dep in service.depends_on:
            self._waiters.setdefault(dep, set()).add(service.name)

    def is_waiting(self, name: str) -> bool:
        return name in self._waiting

    def waiting(self) -> list[str]:
        """The services waiting, in the order they began to."""
        return list(self._waiting)

    def awaited(self, name: str) -> bool:
        """True if a service waits on *name*."""
        return name in self._waiters

    def released(self, name: str) -> list[str]:
        """*name* runs: the services waiting on it whose dependencies all run
        now. They wait no more."""
        released = [
            waiter
            for waiter in list(self._waiters.get(name, ()))
            if self.all_run(self._runners[waiter].service)
        ]
        for waiter in released:
            self._unwait(waiter)
        return released

    def drop(self, name: str) -> list[str]:
        """*name* leaves the runtime: it waits no more, and the services still
        waiting on it are returned, as it will not run for them. They are
        still waiting: dropping each is the caller's."""
        self._unwait(name)
        return [w for w in self._waiters.pop(name, ()) if w in self._waiting]

    def _runs(self, name: str) -> bool:
        runner = self._runners.get(name)
        return runner is not None and runner.state == State.RUNNING

    def _unwait(self, name: str) -> None:
        for dep in self._waiting.pop(name, ()):
            waiters = self._waiters.get(dep)
            if waiters is not None:
                waiters.discard(name)
                if not waiters:
                    del self._waiters[dep]
