# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for one service's lifecycle under the Runtime: start, health, end,
teardown, restart, and what its runner records of it."""

import threading
from unittest.mock import MagicMock

import pytest

from appinfra.service import (
    HealthTimeoutError,
    RestartPolicy,
    RunError,
    Runtime,
    ScheduledService,
    Service,
    SetupError,
    State,
    StopToken,
)
from tests.helpers.service.runner import SimpleService, wait_until

NO_RESTART = RestartPolicy(restart_on_failure=False)


class CountsTeardowns(Service):
    """run() returns at once, or fails if *fails*; counts its teardowns."""

    def __init__(self, fails: bool = False) -> None:
        self._lg = MagicMock()
        self._fails = fails
        self.teardowns = 0
        self.torn_down = threading.Event()

    @property
    def name(self) -> str:
        return "counts-teardowns"

    def run(self) -> None:
        if self._fails:
            raise RuntimeError("run fails")

    def teardown(self) -> None:
        self.teardowns += 1
        self.torn_down.set()


class NeverHealthy(Service):
    """run() returns at once, or blocks until stopped if *blocks*; it is
    never healthy."""

    def __init__(self, blocks: bool = False) -> None:
        self._lg = MagicMock()
        self._blocks = blocks

    @property
    def name(self) -> str:
        return "never-healthy"

    def run(self) -> None:
        if self._blocks:
            self.stopping.wait()

    def is_healthy(self) -> bool:
        return False


class Failing(NeverHealthy):
    """run() fails at once, before it could be healthy."""

    def run(self) -> None:
        raise RuntimeError("intentional failure")


class DerivesThenFails(Service):
    """run() derives a token for its work from its own, then fails."""

    def __init__(self) -> None:
        self._lg = MagicMock()
        self.work: StopToken | None = None
        self.derived = threading.Event()

    @property
    def name(self) -> str:
        return "derives-then-fails"

    def run(self) -> None:
        self.work = self.stopping.child()
        self.derived.set()
        raise RuntimeError("run() fails")


class OutlivesStop(Service):
    """run() ignores its token and returns only once released."""

    def __init__(self) -> None:
        self._lg = MagicMock()
        self.release = threading.Event()

    @property
    def name(self) -> str:
        return "outlives-stop"

    def run(self) -> None:
        assert self.release.wait(5.0)  # the timeout is the failure path


class HealthyOnAnswer(SimpleService):
    """is_healthy() blocks until answered, then reports healthy."""

    def __init__(self) -> None:
        super().__init__("healthy-on-answer")
        self.asked = threading.Event()
        self.answer = threading.Event()

    def is_healthy(self) -> bool:
        self.asked.set()
        assert self.answer.wait(5.0)  # the timeout is the failure path
        return True


class FailsAfterFirstRun(Service):
    """Its first run is healthy until released, then fails; every later run
    fails before it could be healthy."""

    def __init__(self) -> None:
        self._lg = MagicMock()
        self.runs = 0
        self.up = threading.Event()
        self.release = threading.Event()

    @property
    def name(self) -> str:
        return "fails-after-first-run"

    def run(self) -> None:
        self.runs += 1
        if self.runs == 1:
            self.up.set()
            assert self.release.wait(5.0)  # the timeout is the failure path
        raise RuntimeError(f"run {self.runs} fails")

    def is_healthy(self) -> bool:
        return self.runs == 1 and self.up.is_set()


class HeldInSetup(SimpleService):
    """setup() waits until released, so a hook can be attached first."""

    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()

    def setup(self) -> None:
        assert self.release.wait(5.0)  # the timeout is the failure path


class TestLifecycle:
    def test_a_service_runs_once_healthy_and_stops(self, rt: Runtime) -> None:
        moves: list[tuple[State, State]] = []
        svc = HeldInSetup()
        runner = rt.spawn(svc)
        runner.on_state_change(lambda _name, old, new: moves.append((old, new)))
        svc.release.set()

        rt.ready(runner, timeout=5.0)
        assert runner.state == State.RUNNING
        assert runner.is_alive()
        rt.stop_service(runner)

        assert runner.state == State.STOPPED
        assert not runner.is_alive()
        assert "test" not in rt.services
        assert moves == [
            (State.CREATED, State.INITD),
            (State.INITD, State.STARTING),
            (State.STARTING, State.RUNNING),
            (State.RUNNING, State.STOPPING),
            (State.STOPPING, State.STOPPED),
        ]

    @pytest.mark.parametrize("fails", [False, True], ids=["returns", "raises"])
    def test_a_run_that_ends_on_its_own_is_torn_down_once(
        self, rt: Runtime, fails: bool
    ) -> None:
        """However run() ends, the service is torn down when it does, once,
        and leaves the runtime: stopping the runtime does not tear it down
        again."""
        svc = CountsTeardowns(fails=fails)
        rt.spawn(svc, NO_RESTART)

        assert svc.torn_down.wait(5.0)  # the timeout is the failure path
        assert wait_until(lambda: "counts-teardowns" not in rt.services)
        rt.stop()
        assert svc.teardowns == 1

    def test_a_run_failing_while_starting_fails_its_start(self, rt: Runtime) -> None:
        runner = rt.spawn(Failing())

        with pytest.raises(RunError, match="intentional failure"):
            rt.ready(runner, timeout=5.0)
        assert runner.state == State.FAILED
        assert "intentional failure" in str(runner.exception)

    def test_a_run_returning_while_starting_fails_its_start(self, rt: Runtime) -> None:
        runner = rt.spawn(NeverHealthy())

        with pytest.raises(RunError, match="exited during startup"):
            rt.ready(runner, timeout=5.0)
        assert runner.state == State.FAILED

    def test_a_service_not_healthy_in_time_fails(self, rt: Runtime) -> None:
        """ready() gives up on it, and its run ends: it fails and leaves."""
        runner = rt.spawn(NeverHealthy(blocks=True))

        with pytest.raises(HealthTimeoutError):
            rt.ready(runner, timeout=0.1)

        assert wait_until(lambda: "never-healthy" not in rt.services)
        assert runner.state == State.FAILED

    def test_a_run_that_ends_stops_its_token(self, rt: Runtime) -> None:
        """A run that ends without a stop, here by failing, stops its token,
        so work derived from it ends with the run instead of outliving it."""
        svc = DerivesThenFails()
        rt.spawn(svc, NO_RESTART)

        assert svc.derived.wait(5.0)  # the timeouts are the failure path
        assert svc.work is not None
        assert svc.work.wait(5.0)

    def test_a_ready_a_stop_overtook_raises(self, rt: Runtime) -> None:
        """The service looks healthy, but a stop ends its start before the
        check reports it: ready() learns of the stop, not of health."""
        svc = HealthyOnAnswer()
        runner = rt.spawn(svc)
        errors: list[BaseException] = []

        def wait() -> None:
            try:
                rt.ready(runner, timeout=5.0)
            except Exception as e:
                errors.append(e)

        waiter = threading.Thread(target=wait)
        waiter.start()
        assert svc.asked.wait(5.0)  # the timeout is the failure path
        rt.stop_service(runner)  # completes while the check holds a "healthy"
        svc.answer.set()
        waiter.join(5.0)

        assert runner.state == State.STOPPED
        assert len(errors) == 1 and isinstance(errors[0], RunError), errors

    def test_a_run_outliving_its_stop_is_stopping_until_it_ends(
        self, rt: Runtime
    ) -> None:
        svc = OutlivesStop()
        runner = rt.spawn(svc)
        rt.ready(runner, timeout=5.0)

        with pytest.raises(TimeoutError):
            rt.stop_service(runner, timeout=0.05)
        assert runner.state == State.STOPPING
        assert "outlives-stop" in rt.services
        svc.release.set()

        assert wait_until(lambda: "outlives-stop" not in rt.services)
        assert runner.state == State.STOPPED

    def test_hooks_cannot_call_the_runtime(self, rt: Runtime) -> None:
        """A state hook runs on the runtime's own task: a call back into the
        runtime would wait for itself, so it is refused, and the transitions
        go on as without it."""
        runner = rt.spawn(SimpleService())
        refused: list[State] = []

        def calls_back(_name: str, _old: State, new: State) -> None:
            try:
                rt.stop_service(runner)
            except RuntimeError:
                refused.append(new)

        runner.on_state_change(calls_back)
        rt.ready(runner, timeout=5.0)
        rt.stop_service(runner)

        assert refused == [State.RUNNING, State.STOPPING, State.STOPPED]
        assert runner.state == State.STOPPED

    def test_a_service_spawned_again_whose_setup_fails_fails(self, rt: Runtime) -> None:
        """Spawned again after a stop, a service whose setup() fails is a
        failed start, as on its first spawn: SetupError, and FAILED."""

        class SecondSetupFails(SimpleService):
            setups = 0

            def setup(self) -> None:
                SecondSetupFails.setups += 1
                if SecondSetupFails.setups > 1:
                    raise RuntimeError("no second setup")

        svc = SecondSetupFails()
        rt.ready(rt.spawn(svc), timeout=5.0)
        rt.stop_service(rt.services["test"])

        again = rt.spawn(svc)
        with pytest.raises(SetupError, match="no second setup"):
            rt.ready(again, timeout=5.0)
        assert again.state == State.FAILED


class TestRestart:
    def test_restarts_end_once_the_retries_are_used_up(self, rt: Runtime) -> None:
        """It ran, then failed: each restart fails before it is healthy,
        until max_retries attempts have; then it leaves the runtime."""
        svc = FailsAfterFirstRun()
        runner = rt.spawn(svc, RestartPolicy(max_retries=2, backoff=0.0))
        rt.ready(runner, timeout=5.0)

        svc.release.set()

        assert wait_until(lambda: "fails-after-first-run" not in rt.services)
        assert svc.runs == 3
        assert runner.retries == 2
        assert runner.state == State.FAILED
        assert "run 3 fails" in str(runner.exception)


class TestScheduledService:
    def test_it_ticks_until_stopped(self, rt: Runtime) -> None:
        ticks = 0
        two_ticks = threading.Event()

        class Counter(ScheduledService):
            interval = 0.01

            def __init__(self) -> None:
                self._lg = MagicMock()

            @property
            def name(self) -> str:
                return "counter"

            def tick(self) -> None:
                nonlocal ticks
                ticks += 1
                if ticks == 2:
                    two_ticks.set()

        runner = rt.spawn(Counter())
        rt.ready(runner, timeout=5.0)
        assert two_ticks.wait(5.0)  # the timeout is the failure path
        rt.stop_service(runner)

        assert runner.state == State.STOPPED

    def test_teardown_follows_the_last_tick(self, rt: Runtime) -> None:
        """A stop ends the loop first: teardown() never overlaps tick()."""
        ticked = threading.Event()
        calls: list[str] = []

        class Ticker(ScheduledService):
            interval = 5.0

            def __init__(self) -> None:
                self._lg = MagicMock()

            @property
            def name(self) -> str:
                return "ticker"

            def tick(self) -> None:
                calls.append("tick")
                ticked.set()

            def teardown(self) -> None:
                calls.append("teardown")

        runner = rt.spawn(Ticker())
        rt.ready(runner, timeout=5.0)
        assert ticked.wait(5.0)  # the timeout is the failure path

        rt.stop_service(runner)

        assert calls == ["tick", "teardown"]
        assert runner.state == State.STOPPED

    def test_teardown_runs_after_a_tick_fails(self, rt: Runtime) -> None:
        torn_down = threading.Event()

        class Boom(ScheduledService):
            def __init__(self) -> None:
                self._lg = MagicMock()

            @property
            def name(self) -> str:
                return "boom"

            def tick(self) -> None:
                raise RuntimeError("tick failed")

            def teardown(self) -> None:
                torn_down.set()

        runner = rt.spawn(Boom(), NO_RESTART)

        assert torn_down.wait(5.0)  # the timeout is the failure path
        assert wait_until(lambda: "boom" not in rt.services)
        assert "tick failed" in str(runner.exception)
