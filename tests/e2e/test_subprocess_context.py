"""
E2E test for SubprocessContext hot-reload across multiple processes.

This test validates that config hot-reload works correctly in child processes
using SubprocessContext. It spawns multiple processes and verifies that config
changes are detected and applied in each subprocess independently.
"""

import multiprocessing as mp
import tempfile
import time
from pathlib import Path

import pytest


def _worker_loop(
    config_path: str,
    result_queue: mp.Queue,
    ready_event: mp.Event,
    check_event: mp.Event,
    done_event: mp.Event,
    worker_id: int,
) -> None:
    """
    Worker process that uses SubprocessContext.

    Creates its own logger and reports its holder's location value
    to the result queue when signaled.
    """
    import logging

    from appinfra.log import LoggerFactory
    from appinfra.log.config import LogConfig
    from appinfra.subprocess import SubprocessContext

    # Clear any forked logger from parent process (fork inherits loggerDict)
    if "/" in logging.root.manager.loggerDict:
        del logging.root.manager.loggerDict["/"]

    # Create a fresh logger for this subprocess
    config = LogConfig.from_params(level="debug", location=1)
    lg = LoggerFactory.create_root(config)

    with SubprocessContext(lg=lg, config_files=[config_path]) as ctx:
        # Signal that we're ready
        ready_event.set()

        # Wait for check signal, then report location
        while ctx.running and not done_event.is_set():
            if check_event.wait(timeout=0.1):
                # Report current location from the holder
                holder = getattr(lg, "_holder", None)
                location = holder.location if holder else -1
                result_queue.put((worker_id, location))
                check_event.clear()  # Reset for next check

            if done_event.is_set():
                break

    # Cleanup
    lg.handlers.clear()


@pytest.mark.e2e
class TestSubprocessContextHotReload:
    """E2E tests for SubprocessContext hot-reload in multiple processes."""

    @pytest.fixture(autouse=True)
    def check_watchdog_installed(self):
        """Skip tests if watchdog is not installed."""
        try:
            import watchdog  # noqa: F401

            return True
        except ImportError:
            pytest.skip("watchdog not installed - skipping subprocess context tests")

    def test_two_processes_see_config_change(self):
        """Test that both subprocess workers see config hot-reload changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text("logging:\n  level: debug\n  location: 1\n")

            # Create shared communication primitives
            result_queue: mp.Queue = mp.Queue()
            ready_events = [mp.Event(), mp.Event()]
            check_events = [mp.Event(), mp.Event()]
            done_event = mp.Event()

            # Start two worker processes
            workers = []
            for i in range(2):
                p = mp.Process(
                    target=_worker_loop,
                    args=(
                        str(config_path),
                        result_queue,
                        ready_events[i],
                        check_events[i],
                        done_event,
                        i,
                    ),
                )
                p.start()
                workers.append(p)

            try:
                # Wait for both workers to be ready
                for i, event in enumerate(ready_events):
                    assert event.wait(timeout=5.0), f"Worker {i} did not become ready"

                # Give watchers time to start
                time.sleep(0.3)

                # Signal both workers to report location
                for event in check_events:
                    event.set()

                # Collect initial locations
                initial_locations = {}
                for _ in range(2):
                    worker_id, location = result_queue.get(timeout=2.0)
                    initial_locations[worker_id] = location

                # Both should have location=1
                assert initial_locations[0] == 1, (
                    f"Worker 0 initial location: expected 1, got {initial_locations[0]}"
                )
                assert initial_locations[1] == 1, (
                    f"Worker 1 initial location: expected 1, got {initial_locations[1]}"
                )

                # Change config to location=3
                config_path.write_text("logging:\n  level: debug\n  location: 3\n")

                # Wait for watchers to detect and apply change
                time.sleep(0.8)

                # Signal both workers to report location again
                for event in check_events:
                    event.set()

                # Collect updated locations
                updated_locations = {}
                for _ in range(2):
                    worker_id, location = result_queue.get(timeout=2.0)
                    updated_locations[worker_id] = location

                # Both should now have location=3
                assert updated_locations[0] == 3, (
                    f"Worker 0 updated location: expected 3, got {updated_locations[0]}"
                )
                assert updated_locations[1] == 3, (
                    f"Worker 1 updated location: expected 3, got {updated_locations[1]}"
                )

            finally:
                # Clean up
                done_event.set()
                for p in workers:
                    p.join(timeout=2.0)
                    if p.is_alive():
                        p.terminate()
                        p.join()

    def test_subprocess_context_handles_missing_config(self):
        """Test that SubprocessContext works without config_files (no watcher)."""
        from appinfra.log import LoggerFactory
        from appinfra.log.config import LogConfig
        from appinfra.subprocess import SubprocessContext

        config = LogConfig.from_params(level="info", location=0)
        lg = LoggerFactory.create_root(config)

        # Should not raise - just skip watcher setup
        with SubprocessContext(lg=lg) as ctx:
            assert ctx.running is True
            assert ctx._watcher is None

        lg.handlers.clear()

    def test_subprocess_context_handles_invalid_config(self):
        """Test that SubprocessContext handles invalid config path gracefully."""
        from appinfra.log import LoggerFactory
        from appinfra.log.config import LogConfig
        from appinfra.subprocess import SubprocessContext

        config = LogConfig.from_params(level="info", location=0)
        lg = LoggerFactory.create_root(config)

        # Should not raise - log warning and continue
        with SubprocessContext(lg=lg, config_files=["/nonexistent/config.yaml"]) as ctx:
            assert ctx.running is True
            # Watcher may or may not be set depending on error handling

        lg.handlers.clear()

    def test_subprocess_context_signal_handling(self):
        """Test that SubprocessContext properly sets running=False on signal."""
        import signal

        from appinfra.log import LoggerFactory
        from appinfra.log.config import LogConfig
        from appinfra.subprocess import SubprocessContext

        config = LogConfig.from_params(level="info", location=0)
        lg = LoggerFactory.create_root(config)

        with SubprocessContext(lg=lg) as ctx:
            assert ctx.running is True

            # Simulate SIGTERM
            ctx._handle_stop_signal(signal.SIGTERM, None)

            assert ctx.running is False

        lg.handlers.clear()

    def test_subprocess_context_no_signal_handling(self):
        """Test that SubprocessContext skips signal handling when disabled."""
        import signal
        from unittest.mock import patch

        from appinfra.log import LoggerFactory
        from appinfra.log.config import LogConfig
        from appinfra.subprocess import SubprocessContext

        config = LogConfig.from_params(level="info", location=0)
        lg = LoggerFactory.create_root(config)

        with patch.object(signal, "signal") as mock_signal:
            with SubprocessContext(lg=lg, handle_signals=False) as ctx:
                # Signal handlers should not be installed
                mock_signal.assert_not_called()
                assert ctx.running is True

        lg.handlers.clear()

    def test_subprocess_context_lg_property(self):
        """Test that SubprocessContext exposes lg property."""
        from appinfra.log import LoggerFactory
        from appinfra.log.config import LogConfig
        from appinfra.subprocess import SubprocessContext

        config = LogConfig.from_params(level="info", location=0)
        lg = LoggerFactory.create_root(config)

        ctx = SubprocessContext(lg=lg)
        assert ctx.lg is lg

        lg.handlers.clear()

    def test_hot_reload_location_appears_in_log_output(self):
        """Test that location info appears in log output after hot-reload.

        This test verifies that when location config changes from 0 to 1,
        the actual formatted log output includes file:line information.

        This test uses setup_logging_from_config() which is the real app code
        path. This path clears the factory-created handlers and creates new
        ones via the handler registry - which is where the bug exists.

        This is different from test_two_processes_see_config_change which
        only checks that holder.location value changes - it doesn't verify
        that the formatter actually uses the new value.
        """
        import io
        import logging
        import re

        from appinfra.app.core.logging_utils import setup_logging_from_config
        from appinfra.config import Config, ConfigWatcher
        from appinfra.log import LogConfigReloader

        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir)
            config_file = "config.yaml"
            config_path = etc_dir / config_file

            # Start with location=0 (no file:line in output)
            config_path.write_text("logging:\n  level: debug\n  location: 0\n")

            # Create logger using the app's setup path (this is where the bug is)
            # setup_logging_from_config clears factory handlers and creates new
            # ones via the registry - those handlers have their own holders
            app_config = Config(str(config_path))
            lg, _ = setup_logging_from_config(app_config)

            # Capture log output
            log_capture = io.StringIO()
            # Replace the handler's stream with our capture
            for handler in lg.handlers:
                if hasattr(handler, "stream"):
                    handler.stream = log_capture

            # Set up hot-reload watcher
            reloader = LogConfigReloader(lg, section="logging")
            watcher = ConfigWatcher(lg=lg, etc_dir=str(etc_dir))
            watcher.configure(config_file, on_change=reloader)
            watcher.start()

            try:
                # Give watcher time to start
                time.sleep(0.2)

                # Log before config change - should NOT have file:line
                lg.info("before_reload_marker")

                # Change config to location=1
                config_path.write_text("logging:\n  level: debug\n  location: 1\n")

                # Wait for watcher to detect and apply change
                time.sleep(0.8)

                # Log after config change - SHOULD have file:line
                lg.info("after_reload_marker")
                log_after = log_capture.getvalue()

                # Extract the line with after_reload_marker
                after_lines = [
                    line
                    for line in log_after.split("\n")
                    if "after_reload_marker" in line
                ]
                assert len(after_lines) == 1, (
                    f"Expected 1 line with marker, got: {after_lines}"
                )
                after_line = after_lines[0]

                # Verify location info appears (pattern like [./path/to/file.py:123])
                # The location pattern appears after the logger name [/]
                location_pattern = r"\[\./.+\.py:\d+\]"
                assert re.search(location_pattern, after_line), (
                    f"Expected file:line location info in log output after "
                    f"hot-reload to location=1, but got:\n{after_line}"
                )

            finally:
                watcher.stop()
                lg.handlers.clear()
                # Clean up logger from registry
                if "/" in logging.root.manager.loggerDict:
                    del logging.root.manager.loggerDict["/"]


@pytest.mark.unit
class TestSubprocessContextUnit:
    """Unit tests for SubprocessContext that run in-process (for coverage)."""

    def test_start_config_watcher_no_files(self):
        """Test _start_config_watcher returns early when no config files."""
        from appinfra.log import LoggerFactory
        from appinfra.log.config import LogConfig
        from appinfra.subprocess import SubprocessContext

        config = LogConfig.from_params(level="info", location=0)
        lg = LoggerFactory.create_root(config)

        try:
            ctx = SubprocessContext(lg=lg, config_files=[])
            # Call directly to cover early return
            ctx._start_config_watcher()
            assert ctx._watcher is None
        finally:
            lg.handlers.clear()

    def test_start_config_watcher_with_valid_files(self):
        """Test _start_config_watcher sets up watcher with config files."""
        from appinfra.log import LoggerFactory
        from appinfra.log.config import LogConfig
        from appinfra.subprocess import SubprocessContext

        config = LogConfig.from_params(level="info", location=0)
        lg = LoggerFactory.create_root(config)

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text("logging:\n  level: debug\n")

            try:
                ctx = SubprocessContext(lg=lg, config_files=[str(config_path)])
                ctx._start_config_watcher()
                assert ctx._watcher is not None
                ctx._watcher.stop()
            finally:
                lg.handlers.clear()
