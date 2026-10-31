# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/builder/configurer/logging.py that write log files.

Handlers declared on a LoggingScope reach the app's root logger and write through it.
"""

import logging

from appinfra.app.builder.app import AppBuilder


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
