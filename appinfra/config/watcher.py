"""
File-based configuration watcher for hot-reload.

This module provides a file watcher that monitors configuration files for changes
and automatically reloads configuration when modifications are detected.
Uses the watchdog library for efficient file system monitoring.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..log import Logger


class ConfigWatcher:
    """
    Watches configuration file for changes and notifies callbacks.

    Uses watchdog for efficient file system monitoring with
    debouncing to avoid rapid re-reads on multiple write events.

    This is a generic watcher that calls the provided `on_change` callback
    when the config file changes. The callback receives the full config dict
    and is responsible for handling the update (e.g., updating logger config).

    Example:
        >>> from appinfra.config import ConfigWatcher
        >>> from appinfra.log import LogConfigReloader
        >>>
        >>> reloader = LogConfigReloader(root_logger)
        >>> watcher = ConfigWatcher(lg=logger, etc_dir="/etc/myapp")
        >>> watcher.configure("config.yaml", on_change=reloader)
        >>> watcher.start()
        >>> # File changes are now automatically detected
        >>> watcher.stop()

    For section-specific callbacks:
        >>> watcher.add_section_callback("proxy.plugins", on_plugins_changed)

    Note:
        Requires watchdog package. Install with: pip install appinfra[hotreload]
    """

    def __init__(self, lg: Logger, etc_dir: str | Path) -> None:
        """
        Initialize the watcher.

        Args:
            lg: Logger for watcher's own logging (debug messages, errors, etc.)
            etc_dir: Base directory for config files (from --etc-dir)
        """
        self._lg = lg
        self._etc_dir = Path(etc_dir).resolve()
        self._observer: Any = None  # watchdog Observer
        self._config_path: Path | None = None
        self._config_paths: list[
            Path
        ] = []  # All root config files (for layered configs)
        self._debounce_ms: int = 500
        self._debounce_timer: threading.Timer | None = None
        self._lock = threading.RLock()
        self._running = False
        self._on_change: Callable[[dict[str, Any]], None] | None = None
        self._watched_files: set[Path] = set()  # All files to watch (main + includes)
        self._watched_dirs: set[Path] = set()  # Directories being watched
        self._dir_watches: dict[Path, Any] = {}  # dir -> ObservedWatch handle
        self._file_handler: Any = None  # Shared handler instance
        self._last_config_hash: str | None = None  # For content-based change detection
        self._section_callbacks: dict[str, list[Callable[[Any], None]]] = {}

    def configure(
        self,
        config_file: str,
        debounce_ms: int = 500,
        on_change: Callable[[dict[str, Any]], None] | None = None,
    ) -> ConfigWatcher:
        """
        Configure the watcher callback and debounce settings.

        If no config files have been added via add_config_file(), this also
        sets the primary config file. Otherwise, this just configures the
        callback and debounce settings without modifying the file list.

        Args:
            config_file: Config filename relative to etc_dir (e.g., "config.yaml").
                        Used as primary config if no files were pre-added.
            debounce_ms: Milliseconds to wait before applying changes (default: 500)
            on_change: Callback called with full merged config dict when any
                      watched file changes.

        Returns:
            Self for method chaining

        Example:
            >>> reloader = LogConfigReloader(root_logger)
            >>> watcher.configure("config.yaml", on_change=reloader).start()
        """
        with self._lock:
            self._config_path = self._etc_dir / config_file
            # Only add if no files pre-configured (e.g., by create_config_watcher)
            if not self._config_paths:
                self._config_paths.append(self._config_path)
            self._debounce_ms = debounce_ms
            self._on_change = on_change
        return self

    def add_config_file(self, config_file: str | Path) -> ConfigWatcher:
        """
        Add an additional config file to watch (for layered configs).

        When multiple config files are registered, they are loaded and merged
        in order when any file changes. Later files override earlier ones.

        Can be called before or after configure(). Files added before configure()
        will be appended after the primary config.

        Args:
            config_file: Config filename (relative to etc_dir) or absolute path

        Returns:
            Self for method chaining

        Example:
            >>> watcher.configure("base.yaml", on_change=reloader)
            >>> watcher.add_config_file("env.yaml")  # Overlay
            >>> watcher.start()
        """
        with self._lock:
            path = Path(config_file)
            if not path.is_absolute():
                path = self._etc_dir / config_file
            path = path.resolve()
            if path not in self._config_paths:
                self._config_paths.append(path)
        return self

    def _is_watched_file(self, path: Path) -> bool:
        """Thread-safe check if a path is in the watched files set."""
        with self._lock:
            return path in self._watched_files

    def _create_file_handler(self) -> Any:  # pragma: no cover
        """Create watchdog event handler for config file changes."""
        from watchdog.events import FileSystemEventHandler

        watcher = self  # Closure reference

        class ConfigFileHandler(FileSystemEventHandler):  # type: ignore[misc]
            def on_modified(self, event: Any) -> None:
                if event.is_directory:
                    return
                modified_path = Path(event.src_path).resolve()
                # Trigger reload if ANY watched file changes (main or includes)
                if watcher._is_watched_file(modified_path):
                    watcher._on_file_changed()

        return ConfigFileHandler()

    def _get_source_files_from_config(self) -> set[Path]:
        """Load all configs and return all source files (mains + includes)."""
        if not self._config_paths:
            return set()

        all_files: set[Path] = set()
        for config_path in self._config_paths:
            try:
                from .config import Config

                config = Config(str(config_path))
                all_files.update(config.get_source_files())
            except Exception:
                # Fall back to just this config file
                all_files.add(config_path)
        return all_files

    def _update_watched_directories(self) -> None:
        """Update observer to watch all directories containing source files."""
        if self._observer is None:
            return

        # Get unique directories from watched files
        new_dirs = {f.parent for f in self._watched_files}

        # Remove watchers for directories no longer needed
        for dir_path in self._watched_dirs - new_dirs:
            watch = self._dir_watches.pop(dir_path, None)
            if watch is not None:
                self._observer.unschedule(watch)

        # Add watchers for new directories (reuse shared handler)
        for dir_path in new_dirs - self._watched_dirs:
            watch = self._observer.schedule(
                self._file_handler, str(dir_path), recursive=False
            )
            self._dir_watches[dir_path] = watch

        self._watched_dirs = new_dirs

    def start(self) -> None:
        """Start watching for file changes."""
        try:
            from watchdog.observers import Observer
        except ImportError:
            raise ImportError(
                "watchdog is required for hot-reload. "
                "Install with: pip install appinfra[hotreload]"
            ) from None

        with self._lock:  # pragma: no cover
            if self._running:
                return
            if self._config_path is None:
                raise ValueError("Config path not set. Call configure() first.")

            # Get all source files (main config + includes)
            self._watched_files = self._get_source_files_from_config()

            self._observer = Observer()
            # Create single shared handler instance
            self._file_handler = self._create_file_handler()
            # Watch all directories containing source files
            self._watched_dirs = {f.parent for f in self._watched_files}
            self._dir_watches = {}
            for dir_path in self._watched_dirs:
                watch = self._observer.schedule(
                    self._file_handler, str(dir_path), recursive=False
                )
                self._dir_watches[dir_path] = watch
            self._observer.start()
            self._running = True

    def stop(self) -> None:
        """Stop watching for file changes."""
        with self._lock:
            # Cancel pending debounce timer
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None
            if self._observer is not None:  # pragma: no cover
                self._observer.stop()
                self._observer.join(timeout=2.0)
                self._observer = None
            self._running = False
            self._watched_files = set()
            self._watched_dirs = set()
            self._dir_watches = {}
            self._file_handler = None
            self._last_config_hash = None

    def is_running(self) -> bool:
        """Check if watcher is active."""
        with self._lock:
            return self._running

    def _on_file_changed(self) -> None:
        """Handle file change event with trailing-edge debouncing.

        Uses trailing-edge debounce: waits for debounce_ms of quiet time before
        reloading. Each new event resets the timer. This ensures we reload the
        final state after rapid changes (e.g., editor save-all).
        """
        with self._lock:
            # Cancel any pending timer
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()

            # Schedule reload after debounce period
            self._debounce_timer = threading.Timer(
                self._debounce_ms / 1000.0,  # Convert ms to seconds
                self._reload_config,
            )
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _compute_config_hash(self, config_dict: dict[str, Any]) -> str:
        """Compute stable hash of config dict for change detection."""
        # Use json with sorted keys for stable serialization
        serialized = json.dumps(config_dict, sort_keys=True, default=str)
        return hashlib.md5(serialized.encode(), usedforsecurity=False).hexdigest()

    def _load_and_merge_configs(self) -> tuple[dict[str, Any], Any]:
        """Load all config files and merge them. Returns (merged_dict, last_config)."""
        from ..yaml import deep_merge
        from .config import Config

        merged_dict: dict[str, Any] = {}
        last_config: Any = None

        for config_path in self._config_paths:
            try:
                config = Config(str(config_path))
                merged_dict = deep_merge(merged_dict, config.dict())
                last_config = config
            except FileNotFoundError:
                self._lg.debug(
                    "config file not found during reload, skipping",
                    extra={"path": str(config_path)},
                )
        return merged_dict, last_config

    def _reload_config(self) -> None:
        """Reload configuration from file(s) and notify callbacks."""
        if not self._config_paths:
            return

        try:
            merged_dict, last_config = self._load_and_merge_configs()
            if not merged_dict:
                return

            # Content-based change detection: skip if unchanged
            new_hash = self._compute_config_hash(merged_dict)
            with self._lock:
                if new_hash == self._last_config_hash:
                    self._lg.debug("config unchanged, skipping reload")
                    return
                self._last_config_hash = new_hash

            self._invoke_on_change_callback(merged_dict)
            if last_config is not None:
                self._update_watched_sources(last_config)
            self._notify_section_callbacks_from_dict(merged_dict)

        except Exception as e:
            self._lg.error(
                "failed to reload config, keeping previous config",
                extra={"exception": e},
            )

    def _invoke_on_change_callback(self, config_dict: dict[str, Any]) -> None:
        """Invoke the on_change callback with error handling."""
        if self._on_change is None:
            return

        try:
            self._on_change(config_dict)
        except Exception as e:
            self._lg.error("on_change callback failed", extra={"exception": e})

    def _update_watched_sources(self, config: Any) -> None:
        """Update watched files in case includes changed."""
        # Get source files from all configs (handles includes)
        new_source_files = self._get_source_files_from_config()
        with self._lock:
            self._watched_files = new_source_files
            self._update_watched_directories()

    def _notify_section_callbacks(self, config: Any) -> None:
        """Notify all section callbacks with their respective section values.

        Each callback is wrapped in try/except to prevent one failure from
        breaking others.
        """
        with self._lock:
            section_callbacks = {
                section: list(callbacks)
                for section, callbacks in self._section_callbacks.items()
            }

        for section, callbacks in section_callbacks.items():
            section_value = config.get(section)
            if section_value is None:
                continue  # Section doesn't exist, skip callbacks

            for callback in callbacks:
                try:
                    callback(section_value)
                except Exception as e:
                    self._lg.warning(
                        "section callback failed",
                        extra={"section": section, "exception": e},
                    )

    def _notify_section_callbacks_from_dict(self, config_dict: dict[str, Any]) -> None:
        """Notify section callbacks using a merged config dict."""
        from ..dot_dict import DotDict

        with self._lock:
            section_callbacks = {
                section: list(callbacks)
                for section, callbacks in self._section_callbacks.items()
            }

        for section, callbacks in section_callbacks.items():
            # Navigate dot-notation path
            section_value = self._get_nested_value(config_dict, section)
            if section_value is None:
                continue

            # Wrap in DotDict for attribute access (matches original behavior)
            if isinstance(section_value, dict):
                section_value = DotDict(**section_value)

            for callback in callbacks:
                try:
                    callback(section_value)
                except Exception as e:
                    self._lg.warning(
                        "section callback failed",
                        extra={"section": section, "exception": e},
                    )

    def _get_nested_value(self, d: dict[str, Any], path: str) -> Any:
        """Get nested dict value using dot-notation path."""
        keys = path.split(".")
        value: Any = d
        for key in keys:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
            if value is None:
                return None
        return value

    def add_section_callback(
        self,
        section: str,
        callback: Callable[[Any], None],
    ) -> None:
        """Register callback for config section changes.

        Args:
            section: Dot-notation path to config section
                    (e.g., "proxy.plugins.foo.options")
            callback: Called with the section's new value when config reloads.
                     Receives DotDict or dict depending on section structure.
        """
        with self._lock:
            if section not in self._section_callbacks:
                self._section_callbacks[section] = []
            self._section_callbacks[section].append(callback)

    def remove_section_callback(
        self,
        section: str,
        callback: Callable[[Any], None],
    ) -> None:
        """Unregister a section callback.

        Args:
            section: Dot-notation path to config section
            callback: Previously registered callback to remove
        """
        with self._lock:
            if section in self._section_callbacks:
                try:
                    self._section_callbacks[section].remove(callback)
                    if not self._section_callbacks[section]:
                        del self._section_callbacks[section]
                except ValueError:
                    pass  # Callback not found, ignore

    def reload_now(self) -> None:
        """
        Force immediate config reload.

        Useful for testing or manual trigger without file modification.
        """
        self._reload_config()
