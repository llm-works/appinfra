# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""ProcessRunner's monitor restarts a service whose process failed, per start method."""

import multiprocessing as mp
import os
import subprocess
import sys
import time
from multiprocessing.synchronize import Event as MPEvent
from pathlib import Path

import pytest

from appinfra.log import Logger
from appinfra.service import ProcessRunner, RestartPolicy, Service, State

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[2]


class FailOnceService(Service):
    """Fails on its first run in the given way, then runs until shutdown."""

    def __init__(self, lg: Logger, counter: str, failure: str) -> None:
        self._lg = lg
        self._counter = Path(counter)
        self._failure = failure
        self._shutdown_event: MPEvent | None = None  # injected

    @property
    def name(self) -> str:
        return "fail-once"

    def execute(self) -> None:
        runs = _runs(self._counter) + 1
        self._counter.write_text(str(runs))
        if runs == 1:
            # Fail only once the parent has seen this run healthy, so the failure
            # reaches the monitor rather than wait_healthy()'s startup check
            while not _go(self._counter).exists():
                time.sleep(0.01)
            _fail(self._failure)
        assert self._shutdown_event is not None
        self._shutdown_event.wait()

    def is_healthy(self) -> bool:
        return True


class FailAlwaysService(Service):
    """Healthy only on its first run, which exits non-zero once told to; later runs
    exit at once, before reporting healthy, so every restart attempt fails."""

    def __init__(self, lg: Logger, counter: str) -> None:
        self._lg = lg
        self._counter = Path(counter)
        self._healthy = False

    @property
    def name(self) -> str:
        return "fail-always"

    def execute(self) -> None:
        runs = _runs(self._counter) + 1
        self._counter.write_text(str(runs))
        if runs == 1:
            self._healthy = True
            while not _go(self._counter).exists():
                time.sleep(0.01)
        os._exit(3)

    def is_healthy(self) -> bool:
        return self._healthy


def _fail(failure: str) -> None:
    if failure == "exception":
        raise RuntimeError("service failed")
    if failure == "exit":
        os._exit(3)
    raise KeyboardInterrupt  # what Ctrl-C delivers to the process group


def _runs(counter: Path) -> int:
    return int(counter.read_text()) if counter.exists() else 0


def _go(counter: Path) -> Path:
    return counter.with_suffix(".go")


def run_fail_once(
    method: str, failure: str, counter: str, runner_method: str | None = None
) -> None:
    """Run FailOnceService under the monitor; print its runs and the runner's state.

    *method* is the interpreter's default start method, *runner_method* the
    runner's own (None: the default).
    """
    mp.set_start_method(method, force=True)
    runner = ProcessRunner(
        FailOnceService(Logger(name="test"), counter, failure),
        policy=RestartPolicy(max_retries=3, backoff=0.1),
        start_method=runner_method,
    )
    runner.start()
    try:
        runner.wait_healthy(timeout=10.0)
        runner.start_monitor(interval=0.1)
        _go(Path(counter)).touch()
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            restarted = runner.state == State.RUNNING and _runs(Path(counter)) >= 2
            if restarted or runner.state == State.DONE:
                break
            time.sleep(0.05)
        print(f"runs={_runs(Path(counter))} state={runner.state.name}")
    finally:
        runner.stop()


def run_fail_always(counter: str, restart_on_failure: bool) -> None:
    """Run FailAlwaysService under the monitor with one restart allowed; print its
    runs and whether the monitor still runs once no restart can follow."""
    runner = ProcessRunner(
        FailAlwaysService(Logger(name="test"), counter),
        policy=RestartPolicy(
            max_retries=1, backoff=0.1, restart_on_failure=restart_on_failure
        ),
    )
    runner.start()
    try:
        runner.wait_healthy(timeout=10.0)
        runner.start_monitor(interval=0.1)
        _go(Path(counter)).touch()
        deadline = time.monotonic() + 10.0
        while runner.monitoring and time.monotonic() < deadline:
            time.sleep(0.05)
        print(f"runs={_runs(Path(counter))} monitoring={runner.monitoring}")
    finally:
        runner.stop()


def _run_parent(func: str, *args: object) -> subprocess.CompletedProcess[str]:
    """Run *func* from this module in its own interpreter, since the start method
    is process-wide.

    Every DeprecationWarning is printed: os.fork() drops its fork-from-thread
    warning when filters make it an error, so stderr is the only place to see it.
    """
    call = f"{func}({', '.join(repr(a) for a in args)})"
    code = f"from tests.integration.test_process_runner_restart import {func}; {call}"
    try:
        proc = subprocess.run(
            [sys.executable, "-W", "always::DeprecationWarning", "-c", code],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{call}: the parent did not exit within 60 s")
    assert proc.returncode == 0, proc.stderr
    return proc


@pytest.mark.parametrize("failure", ["exception", "exit"])
@pytest.mark.parametrize("method", mp.get_all_start_methods())
def test_monitor_restarts_a_failed_service(
    method: str, failure: str, tmp_path: Path
) -> None:
    """A service that raised or exited non-zero is restarted and runs again."""
    out = _run_parent("run_fail_once", method, failure, str(tmp_path / "runs")).stdout
    assert "runs=2 state=RUNNING" in out, out


@pytest.mark.parametrize("method", mp.get_all_start_methods())
def test_monitor_does_not_restart_an_interrupted_service(
    method: str, tmp_path: Path
) -> None:
    """KeyboardInterrupt, as from Ctrl-C, is a shutdown: the runner ends DONE."""
    proc = _run_parent("run_fail_once", method, "interrupt", str(tmp_path / "runs"))
    assert "runs=1 state=DONE" in proc.stdout, proc.stdout


@pytest.mark.parametrize("runner_method", ["forkserver", "spawn"])
def test_runner_start_method_restarts_without_forking_from_a_thread(
    runner_method: str, tmp_path: Path
) -> None:
    """A runner with its own start method restarts under a fork default, warning-free.

    The restart runs on the monitor thread. Under fork it forks from that thread,
    and Python 3.12+ warns "This process ... is multi-threaded" on stderr.
    """
    proc = _run_parent(
        "run_fail_once", "fork", "exit", str(tmp_path / "runs"), runner_method
    )
    assert "runs=2 state=RUNNING" in proc.stdout, proc.stdout
    assert "is multi-threaded" not in proc.stderr, proc.stderr


@pytest.mark.parametrize(
    ("restart_on_failure", "runs"), [(True, 2), (False, 1)], ids=["exhausted", "off"]
)
def test_monitor_stops_once_no_restart_can_follow(
    restart_on_failure: bool, runs: int, tmp_path: Path
) -> None:
    """The monitor ends once the process is dead and the policy allows no restart:
    after the last allowed attempt failed, or after a crash with restarts off."""
    out = _run_parent("run_fail_always", str(tmp_path / "runs"), restart_on_failure)
    assert f"runs={runs} monitoring=False" in out.stdout, out.stdout
