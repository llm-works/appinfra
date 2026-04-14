"""Context manager for subprocess infrastructure.

Provides signal handling, config hot-reload, and graceful shutdown for child processes.
"""

from __future__ import annotations

import signal
from types import FrameType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import ConfigWatcher
    from ..log import Logger


class SubprocessContext:
    """
    Context manager for subprocess boilerplate.

    Handles common subprocess needs:
    - Signal handling (SIGTERM, SIGINT) for graceful shutdown
    - Config watcher for hot-reload support
    - Clean lifecycle management

    Supports two patterns:

    1. Loop-based (e.g., worker processes):
        ```python
        with SubprocessContext(lg=logger, config_files=["/etc/myapp/config.yaml"]) as ctx:
            while ctx.running:
                msg = queue.get(timeout=1.0)
                process(msg)
        ```

    2. Blocking call (e.g., uvicorn):
        ```python
        with SubprocessContext(lg=logger, config_files=paths, handle_signals=False):
            uvicorn.run(app)  # uvicorn handles its own signals
        ```

    Args:
        lg: Logger instance for this subprocess
        config_files: List of config file paths (absolute). First file is primary,
            rest are overlays merged in order. Required for hot-reload.
        handle_signals: Whether to install signal handlers (default: True).
            Set to False when the subprocess runs a framework that handles
            its own signals (e.g., uvicorn).
    """

    def __init__(
        self,
        lg: Logger,
        config_files: list[str] | None = None,
        handle_signals: bool = True,
    ) -> None:
        self._lg = lg
        self._config_files = config_files or []
        self._handle_signals = handle_signals
        self._running = True
        self._watcher: ConfigWatcher | None = None

    @property
    def running(self) -> bool:
        """Check if subprocess should continue running.

        Returns False after SIGTERM or SIGINT is received.
        """
        return self._running

    @property
    def lg(self) -> Logger:
        """Logger instance for this subprocess.

        Use this logger for all subprocess logging. It is wired to the
        config watcher for hot-reload support.
        """
        return self._lg

    def __enter__(self) -> SubprocessContext:
        """Set up subprocess infrastructure."""
        if self._handle_signals:
            signal.signal(signal.SIGTERM, self._handle_stop_signal)
            signal.signal(signal.SIGINT, self._handle_stop_signal)

        if self._config_files:
            self._start_config_watcher()

        return self

    def __exit__(self, *args: object) -> None:
        """Clean up subprocess infrastructure."""
        if self._watcher:
            try:
                self._watcher.stop()
            except Exception as e:
                self._lg.warning(
                    "failed to stop config watcher", extra={"error": str(e)}
                )
            self._watcher = None

    def _start_config_watcher(self) -> None:
        """Start config file watcher for hot-reload."""
        if not self._config_files:
            return

        try:
            from pathlib import Path

            from ..config import ConfigWatcher
            from ..log import LogConfigReloader

            first_path = Path(self._config_files[0])
            reloader = LogConfigReloader(self._lg, section="logging")
            self._watcher = ConfigWatcher(lg=self._lg, etc_dir=str(first_path.parent))

            for config_path in self._config_files:
                self._watcher.add_config_file(config_path)

            self._watcher.configure(first_path.name, on_change=reloader)
            self._watcher.start()
            self._lg.debug("subprocess config watcher started")
        except ImportError:
            self._lg.debug("watchdog not installed, hot-reload disabled")
        except Exception as e:
            self._lg.warning("failed to start config watcher", extra={"error": str(e)})

    def _handle_stop_signal(self, signum: int, frame: FrameType | None) -> None:
        """Handle SIGTERM/SIGINT by setting running to False."""
        sig_name = signal.Signals(signum).name
        self._lg.debug("received signal, stopping", extra={"signal": sig_name})
        self._running = False
