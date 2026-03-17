"""Integration tests for ProcessRunner with real subprocesses."""

import time

import pytest

from appinfra.log import Logger
from appinfra.service import ProcessRunner, Service, State


class SimpleProcessService(Service):
    """Simple service for multiprocessing tests."""

    def __init__(self, lg: Logger, name: str = "mp-test") -> None:
        self._lg = lg
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def execute(self) -> None:
        self._lg.info("service started")
        # Wait for shutdown signal (injected by ProcessRunner)
        if hasattr(self, "_shutdown_event") and self._shutdown_event:
            self._shutdown_event.wait()
        else:
            time.sleep(10)
        self._lg.info("service stopping")

    def is_healthy(self) -> bool:
        return True


@pytest.mark.integration
class TestProcessRunnerIntegration:
    """Integration tests for ProcessRunner with real subprocesses."""

    @pytest.fixture
    def lg(self):
        """Create a logger for tests."""
        return Logger(name="test")

    def test_full_lifecycle(self, lg):
        """Test full start -> healthy -> stop lifecycle."""
        svc = SimpleProcessService(lg)
        runner = ProcessRunner(svc)

        runner.start()
        runner.wait_healthy(timeout=5.0)

        assert runner.state == State.RUNNING
        assert runner.is_alive()
        assert runner.pid is not None

        runner.stop()

        assert runner.state == State.STOPPED
        assert not runner.is_alive()

    def test_subprocess_logging(self, lg):
        """Test that subprocess logs are captured via queue."""
        import logging

        # Use a custom handler to capture logs (LogQueueListener dispatches to handlers,
        # not to logger methods, so spying on lg.info() won't work)
        logged_messages: list[str] = []

        class CaptureHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                logged_messages.append(record.getMessage())

        handler = CaptureHandler()
        lg.addHandler(handler)

        try:
            svc = SimpleProcessService(lg, name="log-test")
            runner = ProcessRunner(svc)

            runner.start()
            runner.wait_healthy(timeout=5.0)

            # Give subprocess time to log
            time.sleep(0.2)

            runner.stop()

            # Verify log forwarding worked - subprocess should have logged "service started"
            assert runner.state == State.STOPPED
            assert any("started" in msg for msg in logged_messages), (
                f"Expected 'service started' log, got: {logged_messages}"
            )
        finally:
            lg.removeHandler(handler)
