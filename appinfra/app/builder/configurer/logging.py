"""
Logging configuration builder for AppBuilder.

This module provides focused builder for configuring logging.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from ..app import AppBuilder, LoggingConfig


class LoggingConfigurer:
    """
    Focused builder for logging configuration.

    This class extracts logging-related configuration from AppBuilder,
    following the Single Responsibility Principle.
    """

    def __init__(self, app_builder: AppBuilder):
        """
        Initialize the logging configurer.

        Args:
            app_builder: Parent AppBuilder instance
        """
        self._app_builder = app_builder

    def with_config(self, config: LoggingConfig) -> Self:
        """
        Set the logging configuration.

        Args:
            config: LoggingConfig instance

        Returns:
            Self for method chaining
        """
        self._app_builder._logging_config = config
        return self

    def with_level(self, level: str) -> Self:
        """
        Set the log level.

        Args:
            level: Log level (debug, info, warning, error, critical)

        Returns:
            Self for method chaining
        """
        from ..app import LoggingConfig

        if self._app_builder._logging_config is None:
            self._app_builder._logging_config = LoggingConfig()
        self._app_builder._logging_config.level = level
        return self

    def with_location(self, depth: int) -> Self:
        """
        Set the location depth for log messages.

        Args:
            depth: Depth of file locations to show in logs

        Returns:
            Self for method chaining
        """
        from ..app import LoggingConfig

        if self._app_builder._logging_config is None:
            self._app_builder._logging_config = LoggingConfig()
        self._app_builder._logging_config.location = depth
        return self

    def with_micros(self, enabled: bool = True) -> Self:
        """
        Enable or disable microsecond timestamps.

        Args:
            enabled: Whether to show microseconds in timestamps

        Returns:
            Self for method chaining
        """
        from ..app import LoggingConfig

        if self._app_builder._logging_config is None:
            self._app_builder._logging_config = LoggingConfig()
        self._app_builder._logging_config.micros = enabled
        return self

    def with_format(self, format_string: str) -> Self:
        """
        Set custom log format string.

        Args:
            format_string: Custom format string for log messages

        Returns:
            Self for method chaining
        """
        from ..app import LoggingConfig

        if self._app_builder._logging_config is None:
            self._app_builder._logging_config = LoggingConfig()
        self._app_builder._logging_config.format_string = format_string
        return self

    def with_topic_level(self, pattern: str, level: str) -> Self:
        """
        Set log level for a specific topic pattern.

        Topic patterns support glob-style matching:
        - '*' matches single path segment (e.g., '/infra/db/*')
        - '**' matches any depth (e.g., '/infra/**')
        - Exact paths for precise matching (e.g., '/infra/db/queries')

        Rules added via API have highest priority (10), overriding CLI and YAML.

        Args:
            pattern: Topic pattern (must start with '/')
            level: Log level (trace, debug, info, warning, error, critical)

        Returns:
            Self for method chaining

        Example:
            app = (AppBuilder("myapp")
                .logging
                    .with_topic_level("/infra/db/*", "debug")
                    .done()
                .build())
        """
        from ....log.level_manager import LogLevelManager

        manager = LogLevelManager.get_instance()
        manager.add_rule(pattern, level, source="api", priority=10)
        return self

    def with_topic_levels(self, levels: dict[str, str]) -> Self:
        """
        Set log levels for multiple topic patterns at once.

        Topic patterns support glob-style matching:
        - '*' matches single path segment
        - '**' matches any depth
        - Exact paths for precise matching

        Rules added via API have highest priority (10), overriding CLI and YAML.

        Args:
            levels: Dictionary mapping patterns to levels

        Returns:
            Self for method chaining

        Example:
            app = (AppBuilder("myapp")
                .logging
                    .with_topic_levels({
                        "/infra/db/*": "debug",
                        "/infra/api/*": "warning",
                        "/myapp/**": "info"
                    })
                    .done()
                .build())
        """
        from ....log.level_manager import LogLevelManager

        manager = LogLevelManager.get_instance()
        manager.add_rules_from_dict(levels, source="api", priority=10)
        return self

    def with_runtime_updates(self, enabled: bool = True) -> Self:
        """
        Enable or disable runtime updates to existing loggers.

        When enabled, subsequent topic level changes will immediately update
        all matching existing loggers. When disabled (default), topic levels
        only apply to newly created loggers.

        Warning:
            Runtime updates should be enabled before creating loggers for
            consistent behavior.

        Args:
            enabled: Whether to enable runtime updates (default: True)

        Returns:
            Self for method chaining

        Example:
            app = (AppBuilder("myapp")
                .logging
                    .with_runtime_updates(True)  # Opt-in to runtime changes
                    .with_topic_level("/infra/db/*", "debug")
                    .done()
                .build())
        """
        from ....log.level_manager import LogLevelManager

        manager = LogLevelManager.get_instance()
        if enabled:
            manager.enable_runtime_updates()
        else:
            manager.disable_runtime_updates()
        return self

    def with_hot_reload(
        self,
        enabled: bool = True,
        debounce_ms: int = 500,
    ) -> Self:
        """
        Enable hot-reload of logging configuration from config file.

        When enabled, changes to the config file are automatically detected
        and applied to all existing loggers without restart. Supports reloading:
        - Log levels
        - Display options (colors, location, location_color, micros)
        - Topic-based level rules

        Note:
            Requires watchdog package. Install with: pip install appinfra[hotreload]
            Requires calling with_config_file() first to set the config path.

        Args:
            enabled: Whether to enable hot-reload (default: True)
            debounce_ms: Milliseconds to wait before applying changes (default: 500)

        Returns:
            Self for method chaining

        Example:
            app = (AppBuilder("myapp")
                .with_config_file("app.yaml")
                .logging
                    .with_hot_reload(True)
                    .done()
                .build())

        Raises:
            ImportError: If watchdog is not installed
            ValueError: If with_config_file() was not called first
        """
        from ....dot_dict import DotDict

        # Require config files from with_config_file()
        if not self._app_builder._config_files:
            raise ValueError(
                "with_config_file() must be called before with_hot_reload(). "
                "Example: AppBuilder('app').with_config_file('app.yaml').logging.with_hot_reload()"
            )

        # Ensure config exists
        if self._app_builder._config is None:
            self._app_builder._config = DotDict()

        config = self._app_builder._config

        # Ensure logging section exists
        if not hasattr(config, "logging"):
            config.logging = DotDict()  # type: ignore[attr-defined]

        # Write hot_reload config directly to config.logging.hot_reload
        # This ensures LifecycleManager will see it during initialization
        config.logging.hot_reload = DotDict(  # type: ignore[attr-defined]
            enabled=enabled,
            debounce_ms=debounce_ms,
        )

        return self

    def done(self) -> AppBuilder:
        """
        Finish logging configuration and return to main builder.

        Returns:
            Parent AppBuilder instance for continued chaining
        """
        return self._app_builder
