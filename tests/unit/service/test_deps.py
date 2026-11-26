# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for Dependencies: who waits on whom, and who may start or no longer
can as dependencies come to run or leave."""

from unittest.mock import MagicMock

from appinfra.service import Runner, Service, State
from appinfra.service.runtime.deps import Dependencies


class Named(Service):
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


def _add(
    runners: dict[str, Runner], name: str, *depends: str, running: bool = False
) -> Runner:
    """A runner of *name*, in *runners*; RUNNING if *running*."""
    runner = Runner(Named(name, *depends))
    if running:
        runner._state = State.RUNNING  # Private: the Runtime moves it
    runners[name] = runner
    return runner


class TestCycle:
    def test_the_service_that_closes_a_cycle_names_it(self):
        runners: dict[str, Runner] = {}
        _add(runners, "a", "b")
        _add(runners, "b", "c")

        assert Dependencies(runners).cycle(Named("c", "a")) == ["c", "a", "b"]

    def test_a_diamond_is_no_cycle(self):
        runners: dict[str, Runner] = {}
        _add(runners, "b", "a")
        _add(runners, "c", "a")
        _add(runners, "a")

        assert Dependencies(runners).cycle(Named("d", "b", "c")) is None

    def test_a_dependency_not_in_the_runtime_ends_the_search(self):
        assert Dependencies({}).cycle(Named("a", "b")) is None


class TestState:
    def test_all_run_only_once_every_dependency_runs(self):
        runners: dict[str, Runner] = {}
        _add(runners, "db", running=True)
        cache = _add(runners, "cache")
        deps = Dependencies(runners)
        api = Named("api", "db", "cache")

        assert not deps.all_run(api)
        assert deps.missing(api) == "cache"
        cache._state = State.RUNNING  # Private: the Runtime moves it
        assert deps.all_run(api)

    def test_down_names_a_dependency_gone_or_not_running(self):
        runners: dict[str, Runner] = {}
        _add(runners, "db", running=True)
        _add(runners, "cache")  # in the runtime, not RUNNING
        deps = Dependencies(runners)

        assert deps.down(Named("api", "db", "queue")) == "queue"
        assert deps.down(Named("api", "db", "cache")) == "cache"
        assert deps.down(Named("api", "db")) is None


class TestWaiting:
    def test_a_waiter_is_released_once_its_last_dependency_runs(self):
        runners: dict[str, Runner] = {}
        db = _add(runners, "db")
        cache = _add(runners, "cache")
        api = _add(runners, "api", "db", "cache")
        deps = Dependencies(runners)
        deps.wait(api.service)
        assert deps.awaited("db") and deps.awaited("cache")

        db._state = State.RUNNING  # Private: the Runtime moves it
        assert deps.released("db") == []
        assert deps.is_waiting("api")

        cache._state = State.RUNNING
        assert deps.released("cache") == ["api"]
        assert not deps.is_waiting("api")
        assert not deps.awaited("db") and not deps.awaited("cache")

    def test_a_dependency_leaving_returns_its_waiters_still_waiting(self):
        runners: dict[str, Runner] = {}
        _add(runners, "db")
        api = _add(runners, "api", "db")
        web = _add(runners, "web", "db")
        deps = Dependencies(runners)
        deps.wait(api.service)
        deps.wait(web.service)

        assert sorted(deps.drop("db")) == ["api", "web"]
        assert deps.is_waiting("api")  # failing and dropping them is the caller's
        assert not deps.awaited("db")

    def test_a_waiter_leaving_waits_no_more(self):
        runners: dict[str, Runner] = {}
        db = _add(runners, "db")
        api = _add(runners, "api", "db")
        deps = Dependencies(runners)
        deps.wait(api.service)

        assert deps.drop("api") == []
        db._state = State.RUNNING  # Private: the Runtime moves it

        assert not deps.is_waiting("api")
        assert deps.released("db") == []

    def test_waiting_lists_waiters_in_the_order_they_began(self):
        runners: dict[str, Runner] = {}
        deps = Dependencies(runners)
        for name in ("c", "a", "b"):
            deps.wait(_add(runners, name, "db").service)

        assert deps.waiting() == ["c", "a", "b"]
