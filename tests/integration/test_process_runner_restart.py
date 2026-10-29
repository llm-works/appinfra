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


def run_fail_once(method: str, failure: str, counter: str) -> None:
    """Run FailOnceService under the monitor; print its runs and the runner's state."""
    mp.set_start_method(method, force=True)
    runner = ProcessRunner(
        FailOnceService(Logger(name="test"), counter, failure),
        policy=RestartPolicy(max_retries=3, backoff=0.1),
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


def _run_parent(method: str, failure: str, counter: Path) -> str:
    """Run run_fail_once in its own interpreter, since the start method is process-wide."""
    code = (
        "from tests.integration.test_process_runner_restart import run_fail_once; "
        f"run_fail_once({method!r}, {failure!r}, {str(counter)!r})"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{method}/{failure}: the parent did not exit within 60 s")
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.mark.parametrize("failure", ["exception", "exit"])
@pytest.mark.parametrize("method", mp.get_all_start_methods())
def test_monitor_restarts_a_failed_service(
    method: str, failure: str, tmp_path: Path
) -> None:
    """A service that raised or exited non-zero is restarted and runs again."""
    out = _run_parent(method, failure, tmp_path / "runs")
    assert "runs=2 state=RUNNING" in out, out


@pytest.mark.parametrize("method", mp.get_all_start_methods())
def test_monitor_does_not_restart_an_interrupted_service(
    method: str, tmp_path: Path
) -> None:
    """KeyboardInterrupt, as from Ctrl-C, is a shutdown: the runner ends DONE."""
    out = _run_parent(method, "interrupt", tmp_path / "runs")
    assert "runs=1 state=DONE" in out, out
