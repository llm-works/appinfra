# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The SIGALRM timeouts of the database log handler, the regex helpers and the
shutdown phases, with real signal state: the timer they arm, the handler they
leave behind, and calls from a worker thread, where no signal handler can be set.

No signal is delivered: expiry is exercised by calling the installed handler.
"""

import logging
import signal
import threading
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from unittest.mock import Mock

import pytest

from appinfra.app.core.lifecycle import LifecycleManager
from appinfra.dot_dict import DotDict
from appinfra.log.builder.database.config import DatabaseHandlerConfig
from appinfra.log.builder.database.handler import DatabaseHandler
from appinfra.log.config import LogConfig
from appinfra.log.logger import Logger
from appinfra.regex_utils import safe_compile, safe_match

pytestmark = pytest.mark.skipif(
    not hasattr(signal, "SIGALRM"), reason="Requires SIGALRM (Unix only)"
)


@pytest.fixture(autouse=True)
def _restore_sigalrm() -> Iterator[None]:
    """Leave SIGALRM's handler and timer as each test found them."""
    before = signal.getsignal(signal.SIGALRM)
    yield
    signal.setitimer(signal.ITIMER_REAL, 0)
    signal.signal(signal.SIGALRM, before)


def _in_thread(fn: Any) -> list[Any]:
    """Run fn in a worker thread; return [its result] or [the exception it raised]."""
    out: list[Any] = []

    def run() -> None:
        try:
            out.append(fn())
        except BaseException as e:
            out.append(e)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    return out


def _db_handler(**options: Any) -> tuple[DatabaseHandler, Mock]:
    """A DatabaseHandler on a mock database; returns it and the mock session."""
    db = Mock()
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    db.session.return_value = session
    config = DatabaseHandlerConfig(table_name="logs", db_interface=db, **options)
    log_config = LogConfig.from_params(level="info", location=0, micros=False)
    return DatabaseHandler(Mock(), config, log_config), session


def _logged_record(extra: dict[str, Any]) -> logging.LogRecord:
    """Return the record appinfra's Logger produces for an error with *extra*."""
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    lg = Logger(name="sigalrm")
    lg.addHandler(Capture())
    lg.error("Error", extra=extra)
    return records[0]


class TestDatabaseHandlerCriticalFlush:
    def test_write_runs_under_a_sub_second_timeout(self) -> None:
        """The write runs with the timer armed to the configured 0.5 s; the timer
        and handler are back to their prior state afterwards."""
        handler, session = _db_handler(critical_flush_timeout=0.5)
        before = signal.getsignal(signal.SIGALRM)
        armed: list[float] = []
        session.execute.side_effect = lambda *a: armed.append(
            signal.getitimer(signal.ITIMER_REAL)[0]
        )

        handler._critical_flush({"timestamp": datetime.now(), "message": "CRITICAL"})

        assert len(armed) == 1 and 0.0 < armed[0] <= 0.5
        assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
        assert signal.getsignal(signal.SIGALRM) == before

    def test_record_from_a_worker_thread_is_written(self) -> None:
        handler, session = _db_handler(
            critical_flush_enabled=True, critical_trigger_fields=["critical"]
        )
        record = _logged_record({"critical": "disk full"})

        _in_thread(lambda: handler.emit(record))

        session.execute.assert_called_once()
        assert handler.batch == []


class TestRegexTimeout:
    def test_default_handler_restored_after_compile(self) -> None:
        """SIG_DFL, SIGALRM's usual handler, is put back."""
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
        safe_compile(r"^a+$")
        assert signal.getsignal(signal.SIGALRM) == signal.SIG_DFL

    def test_sub_second_timeout_arms_the_timer(self) -> None:
        """A 0.2 s timeout is not rounded up to 1 s."""
        armed: list[float] = []

        class Probe:
            """A precompiled pattern that records the timer when it matches."""

            def match(self, string: str) -> None:
                armed.append(signal.getitimer(signal.ITIMER_REAL)[0])

        safe_match(Probe(), "aaa", timeout=0.2)  # type: ignore[arg-type]

        assert len(armed) == 1 and 0.0 < armed[0] <= 0.2

    def test_match_from_a_worker_thread(self) -> None:
        result = _in_thread(lambda: safe_match(r"^a+$", "aaa").group())
        assert result == ["aaa"]


class TestShutdownPhaseTimeout:
    def _manager(self, **timeouts: float) -> LifecycleManager:
        manager = LifecycleManager(Mock())
        config = DotDict(
            logging=DotDict(level="info", location=0, micros=False),
            shutdown_timeouts=timeouts,
        )
        manager.initialize(config)
        return manager

    def test_phase_runs_under_a_sub_second_timeout(self) -> None:
        manager = self._manager(test=0.5)
        armed: list[float] = []

        manager._execute_phase(
            "test", lambda: armed.append(signal.getitimer(signal.ITIMER_REAL)[0])
        )

        assert len(armed) == 1 and 0.0 < armed[0] <= 0.5
        assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)

    def test_expired_phase_is_logged(self) -> None:
        manager = self._manager()
        manager._lifecycle_logger = Mock()

        def phase() -> None:
            signal.getsignal(signal.SIGALRM)(signal.SIGALRM, None)

        manager._execute_phase("test", phase)

        manager._lifecycle_logger.warning.assert_called_once()
        assert manager._lifecycle_logger.warning.call_args.args[0] == "shutdown timeout"

    def test_critical_log_flush_keeps_the_phase_timer(self) -> None:
        """A critical database write inside a phase does not cancel the phase's
        timeout: the phase's timer is still armed after the write."""
        manager = self._manager(test=30.0)
        handler, _ = _db_handler(critical_flush_timeout=1.0)
        after_write: list[float] = []

        def phase() -> None:
            handler._critical_flush({"timestamp": datetime.now(), "message": "x"})
            after_write.append(signal.getitimer(signal.ITIMER_REAL)[0])

        manager._execute_phase("test", phase)

        assert len(after_write) == 1 and after_write[0] > 1.0
