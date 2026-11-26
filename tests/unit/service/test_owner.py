# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the service Runtime's owner task, its handlers driven directly in
an order the inbox can deliver but timing cannot pin down."""

import sys
from typing import Any
from unittest.mock import MagicMock, patch

from appinfra.runtime import Chan, TaskDone
from appinfra.service import Runner, Runtime, Service, State
from appinfra.service.runtime.owner import GiveUp, Owner, Ready, StopService
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
    service.stopping = owner._root.child()
    owner._runners[runner.name] = runner
    if state != State.RUNNING:
        owner._deps.wait(service)
    return runner


def test_a_health_check_outliving_its_run_does_not_pass_the_next_one() -> None:
    """The run ended while its health check blocked in is_healthy(). The
    check's late True belongs to that run: a later start of the service,
    STARTING again, does not run on it."""
    owner = Runtime(MagicMock())._owner
    runner = _admit(owner, SimpleService("slow-check"), State.RUNNING)
    runner._state = State.STARTING  # Private: the owner moves it
    runner._task = MagicMock(id=9)  # its run
    owner._health[runner.name] = 5  # its check, blocked

    owner._on_run(runner, TaskDone(9, "slow-check/run", None, RuntimeError("x")))
    owner._runners[runner.name] = runner  # started again, as a restart does
    runner._state = State.STARTING
    owner._on_health(runner, TaskDone(5, "slow-check/health", True, None))

    assert runner.state == State.STARTING


def test_a_health_result_after_its_run_was_ended_promotes_nothing() -> None:
    """A ready() gave up and ended the run, whose thread has not returned yet;
    the health check reports healthy meanwhile. The run is ending: the start
    is not promoted, and the run's end settles it."""
    owner = Runtime(MagicMock())._owner
    runner = _admit(owner, SimpleService("ending"), State.RUNNING)
    runner._state = State.STARTING  # Private: the owner moves it
    owner._health[runner.name] = 5
    runner.service.stopping.stop()  # as _end_run() leaves it

    owner._on_health(runner, TaskDone(5, "ending/health", True, None))

    assert runner.state == State.STARTING


def test_services_that_leave_without_running_leave_no_token_behind() -> None:
    """A waiter failed as its dependency leaves never reaches a run, which is
    what detaches a token otherwise: leaving does, so the root holds none."""
    owner = Runtime(MagicMock())._owner
    db = _admit(owner, Named("db"), State.RUNNING)
    _admit(owner, Named("api", "db"), State.CREATED)
    db.service.stopping.detach()  # as its run did when it ended

    owner._forget(db)

    assert owner._root._children is None


def test_a_ready_given_up_on_leaves_no_registration() -> None:
    """A ready() on a service still waiting registers its reply channel; once
    the caller gives up, that channel is gone, so repeated waits do not pile
    up."""
    owner = Runtime(MagicMock())._owner
    runner = _admit(owner, Named("api", "db"), State.CREATED)
    waited: Chan[Any] = Chan(1)

    owner._on_ready(Ready(runner, waited))
    assert owner._ready == {runner: [waited]}
    owner._on_give_up(GiveUp(runner, waited, Chan(1)))

    assert owner._ready == {}


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
    runner = _admit(owner, SimpleService("restarting"), State.RUNNING)
    runner._state = State.FAILED  # Private: the owner moves it
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
