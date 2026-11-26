# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the service Runtime's owner task, its handlers driven directly in
an order the inbox can deliver but timing cannot pin down."""

import sys
from typing import Any
from unittest.mock import MagicMock, patch

from appinfra.runtime import Chan, TaskDone
from appinfra.service import Runner, Runtime, Service, State
from appinfra.service.runtime.owner import Owner, StopService
from tests.helpers.service.runner import SimpleService


class Named(Service):
    """A service known by its name and dependencies only."""

    def __init__(self, name: str, *depends: str) -> None:
        self._lg = MagicMock()
        self._name = name
        self._depends = list(depends)

    @property
    def name(self) -> str:
        return self._name

    @property
    def depends_on(self) -> list[str]:
        return self._depends

    def run(self) -> None:
        raise AssertionError("never run by these tests")


def _admit(owner: Owner, service: Service, state: State) -> Runner:
    """Put a runner of *service* in *owner* as spawn() would, in *state*;
    one that does not run waits on its dependencies."""
    runner = Runner(service)
    runner._owner = owner
    runner._state = state  # Private: the owner moves it
    owner._runners[runner.name] = runner
    if state != State.RUNNING:
        owner._deps.wait(service)
    return runner


def test_a_chain_longer_than_the_recursion_limit_fails_to_its_end() -> None:
    """Each service waits on the one before it; when the first leaves, every
    one fails, however long the chain."""
    owner = Runtime(MagicMock())._owner
    length = sys.getrecursionlimit() * 3
    first = _admit(owner, Named("s0"), State.RUNNING)
    chain = [
        _admit(owner, Named(f"s{i}", f"s{i - 1}"), State.CREATED)
        for i in range(1, length)
    ]

    owner._forget(first)

    assert all(r.state == State.FAILED for r in chain)
    assert owner._runners == {}


def test_a_waiter_reached_twice_as_its_dependencies_leave_fails_once() -> None:
    """a waits on b and c, c on b. When b leaves, c is failed first: that
    fails a, which b's own walk then reaches again. Every waiter fails once,
    and none stays in the runtime."""
    owner = Runtime(MagicMock())._owner
    b = _admit(owner, Named("b"), State.RUNNING)
    c = _admit(owner, Named("c", "b"), State.CREATED)
    a = _admit(owner, Named("a", "b", "c"), State.CREATED)
    drop = owner._deps.drop

    def c_first(name: str) -> list[str]:
        return sorted(drop(name), key=lambda w: w != "c")

    with patch.object(owner._deps, "drop", side_effect=c_first):
        owner._forget(b)

    assert a.state == State.FAILED and c.state == State.FAILED
    assert owner._runners == {}


def test_a_stop_queued_before_a_finished_backoff_ends_the_restart() -> None:
    """The backoff had finished, its end still queued, when the owner handled
    a stop_service(): cancelling it did nothing, and its success must not
    restart the stopped service. The stop is answered instead."""
    owner = Runtime(MagicMock())._owner
    runner = Runner(SimpleService("restarting"))
    runner._owner = owner
    runner._state = State.FAILED  # Private: the owner moves it
    owner._runners[runner.name] = runner
    owner._restarting.add(runner.name)
    backoff = owner._backoffs[runner.name] = MagicMock(id=7)
    reply: Chan[Any] = Chan(1)

    with patch.object(owner, "_begin") as begin:
        owner._on_stop_service(StopService(runner, reply))
        owner._on_backoff(runner, TaskDone(7, "restarting/backoff", None, None))

    backoff.cancel.assert_called_once()
    begin.assert_not_called()
    assert reply.recv(timeout=0) is None
    assert runner.name not in owner._runners
