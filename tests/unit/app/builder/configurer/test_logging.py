# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/builder/configurer/logging.py.

LoggingScope is the standalone LoggingBuilder bound to an AppBuilder.
done() folds explicit options, handlers and extra fields into the
builder's programmatic config layer under ``logging``.
"""

import io
import logging
from dataclasses import fields
from unittest.mock import patch

import pytest

from appinfra.app.builder.app import AppBuilder
from appinfra.app.builder.configurer.logging import LoggingFields, LoggingScope
from appinfra.log.builder.builder import LoggingBuilder
from appinfra.log.config import LogConfig

LEVEL_MANAGER = "appinfra.log.level_manager.LogLevelManager.get_instance"


def _logging_section(builder: AppBuilder) -> dict:
    assert builder._config is not None
    return builder._config.to_dict()["logging"]


# =============================================================================
# The scope is the standalone builder
# =============================================================================


class TestLoggingScopeIsABuilder:
    """LoggingScope inherits LoggingBuilder and is memoized per AppBuilder."""

    def test_is_logging_builder(self):
        """Every LoggingBuilder method is available through inheritance."""
        assert isinstance(AppBuilder("test").logging, LoggingBuilder)
        assert isinstance(AppBuilder("test").logging, LoggingScope)

    def test_same_instance_per_builder(self):
        """State lives on the scope, so the builder hands out one instance."""
        builder = AppBuilder("test")
        block = builder.logging
        block.done()

        assert builder.logging is block

    def test_build_raises_pointing_at_done(self):
        """The app's lifecycle builds the logger, not the scope."""
        with pytest.raises(TypeError, match=r"done\(\)"):
            AppBuilder("test").logging.build()

    def test_done_returns_builder(self):
        """done() closes the block."""
        builder = AppBuilder("test")

        assert builder.logging.done() is builder

    def test_inherited_setters_return_scope(self):
        """Chaining stays inside the block until done()."""
        scope = AppBuilder("test").logging

        assert scope.with_level("debug").with_micros() is scope


# =============================================================================
# done() folds into the programmatic layer
# =============================================================================


class TestDoneFoldsIntoConfig:
    """Explicit options, handlers and extra reach builder._config.logging."""

    def test_explicit_options_reach_programmatic_layer(self):
        """Set options are written under logging."""
        builder = AppBuilder("test").logging.with_level("debug").with_location(2).done()

        assert _logging_section(builder) == {"level": "debug", "location": 2}

    def test_untouched_options_are_not_written(self):
        """A builder default never overrides the config file."""
        builder = AppBuilder("test").logging.with_level("debug").done()

        assert "micros" not in _logging_section(builder)
        assert "colors" not in _logging_section(builder)

    def test_nothing_set_writes_nothing(self):
        """An empty block leaves the programmatic layer absent."""
        builder = AppBuilder("test").logging.done()

        assert builder._config is None

    def test_merges_with_existing_programmatic_config(self):
        """The fold deep-merges with overrides declared on the config block."""
        builder = (
            AppBuilder("test")
            .config.with_overrides({"logging": {"micros": True}, "db": {"host": "x"}})
            .done()
            .logging.with_level("warning")
            .done()
        )

        config = builder._config.to_dict()
        assert config["logging"] == {"micros": True, "level": "warning"}
        assert config["db"] == {"host": "x"}

    def test_done_is_idempotent(self):
        """Closing the block twice writes the same values once."""
        builder = AppBuilder("test")
        builder.logging.with_level("debug").done()

        builder.logging.done()

        assert _logging_section(builder) == {"level": "debug"}

    @pytest.mark.integration
    def test_handlers_serialize_to_handlers_section(self, tmp_path):
        """Handlers become logging.handlers entries in config form."""
        log_file = tmp_path / "app.log"
        builder = (
            AppBuilder("test")
            .logging.with_console_handler()
            .with_file_handler(log_file)
            .done()
        )

        handlers = _logging_section(builder)["handlers"]
        assert handlers["builder_0"]["type"] == "console"
        assert handlers["builder_1"] == {
            "type": "file",
            "filename": str(log_file),
            "mode": "a",
            "delay": False,
        }

    def test_extra_reaches_extra_section(self):
        """with_extra fields go to logging.extra."""
        builder = AppBuilder("test").logging.with_extra(service="api").done()

        assert _logging_section(builder)["extra"] == {"service": "api"}

    def test_handler_without_config_form_raises_at_done(self):
        """A handler that cannot be expressed as config fails instead of vanishing."""
        block = AppBuilder("test").logging.with_console_handler(stream=io.StringIO())

        with pytest.raises(ValueError, match="cannot be expressed as config"):
            block.done()

    def test_build_raises_when_block_not_closed(self):
        """An open block fails at build(), naming the block and where it was opened."""
        builder = AppBuilder("test")
        builder.logging.with_level("error")

        with pytest.raises(
            ValueError,
            match=r"logging block opened at .*test_logging.py:\d+ is still open",
        ):
            builder.build()

    def test_build_raises_when_held_scope_changes_after_done(self):
        """Changes on a held scope after done() need another done()."""
        builder = AppBuilder("test")
        scope = builder.logging
        scope.with_level("error").done()
        scope.with_micros(True)

        with pytest.raises(ValueError, match="changes made after done"):
            builder.build()

    def test_build_accepts_held_scope_without_changes(self):
        """Re-setting the same value on a held scope after done() is not a change."""
        builder = AppBuilder("test")
        scope = builder.logging
        scope.with_level("error").done()
        scope.with_level("error")

        app = builder.build()

        assert app.config.logging.level == "error"

    def test_config_write_after_done_wins(self):
        """done() is the only fold, so a later .config write to the key wins."""
        builder = (
            AppBuilder("test")
            .logging.with_level("debug")
            .done()
            .config.with_value("logging.level", "info")
            .done()
        )

        app = builder.build()

        assert app.config.logging.level == "info"


@pytest.mark.integration
class TestHandlersReachRootLogger:
    """Serialized handlers feed the app's handler registry unchanged."""

    def test_file_handler_from_scope_writes_log_file(self, tmp_path):
        """A handler declared on the scope is the root logger's handler."""
        from appinfra.app.core.logging_utils import setup_logging_from_config

        log_file = tmp_path / "app.log"
        builder = (
            AppBuilder("test")
            .logging.with_level("info")
            .with_file_handler(log_file)
            .done()
        )
        logging.root.manager.loggerDict.pop("/", None)

        logger, registry = setup_logging_from_config(
            builder._config, {"log_level": "info"}
        )
        try:
            logger.info("written through the scope's handler")

            assert [h._handler_name for h in registry.iter_enabled_handlers()] == [
                "builder_0"
            ]
            assert "written through the scope's handler" in log_file.read_text()
        finally:
            for handler in logger.handlers:
                handler.close()
            logger.handlers.clear()


# =============================================================================
# Scope-only and inherited topic methods
# =============================================================================


class TestTopicAndRuntimeMethods:
    """with_runtime_updates is scope-only; topic levels are inherited."""

    def test_with_runtime_updates_enables(self):
        """Default argument enables runtime updates."""
        with patch(LEVEL_MANAGER) as get:
            scope = AppBuilder("test").logging
            assert scope.with_runtime_updates() is scope

        get.return_value.enable_runtime_updates.assert_called_once()

    def test_with_runtime_updates_disables(self):
        """False disables runtime updates."""
        with patch(LEVEL_MANAGER) as get:
            AppBuilder("test").logging.with_runtime_updates(False)

        get.return_value.disable_runtime_updates.assert_called_once()

    def test_topic_level_is_inherited(self):
        """The standalone builder's topic rule registration works on the scope."""
        with patch(LEVEL_MANAGER) as get:
            AppBuilder("test").logging.with_topic_level("/db/*", "debug")

        get.return_value.add_rule.assert_called_once_with(
            "/db/*", "debug", source="api", priority=10
        )


# =============================================================================
# Keyword form
# =============================================================================


class TestKeywordForm:
    """Calling the block sets fields, folds them, and returns the AppBuilder."""

    def test_call_unknown_keyword_raises(self):
        """A misspelled key fails instead of being ignored."""
        with pytest.raises(TypeError, match="unknown logging field\\(s\\): levl"):
            AppBuilder("test").logging(levl="debug")

    def test_call_rejects_none(self):
        """None is not a value; an unset argument must be left out."""
        with pytest.raises(TypeError, match="level cannot be None"):
            AppBuilder("test").logging(level=None)

    def test_call_rejects_non_boolean_runtime_updates(self):
        """A truthy string must not switch the level manager into runtime mode."""
        with pytest.raises(TypeError, match="runtime_updates must be a boolean"):
            AppBuilder("test").logging(runtime_updates="false")

    def test_call_sets_options_and_returns_builder(self):
        """Display options land in the programmatic layer."""
        builder = AppBuilder("test")

        result = builder.logging(level="debug", micros=True)

        assert result is builder
        assert _logging_section(builder) == {"level": "debug", "micros": True}

    def test_call_routes_topic_levels_and_runtime_updates(self):
        """The scope-only keys go to the level manager."""
        with patch(LEVEL_MANAGER) as get:
            AppBuilder("test").logging(
                topic_levels={"/a": "debug"}, runtime_updates=True
            )

        get.return_value.add_rules_from_dict.assert_called_once_with(
            {"/a": "debug"}, source="api", priority=10
        )
        get.return_value.enable_runtime_updates.assert_called_once()

    def test_fields_match_log_config(self):
        """LoggingFields keys equal LogConfig's fields plus the scope-only keys."""
        assert set(LoggingFields.__annotations__) == {
            f.name for f in fields(LogConfig)
        } | {"topic_levels", "runtime_updates"}
