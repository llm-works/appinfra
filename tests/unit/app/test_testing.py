# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.app.testing module."""

import argparse
from unittest.mock import Mock

import pytest

from appinfra.app.testing import MockApp


@pytest.mark.unit
class TestMockApp:
    """Test MockApp class."""

    def test_mock_app_with_no_args(self):
        """Test MockApp with no arguments."""
        app = MockApp()
        assert isinstance(app.args, argparse.Namespace)
        assert isinstance(app.lg, Mock)
        assert isinstance(app.config, Mock)

    def test_mock_app_with_args_dict(self):
        """Test MockApp with args dictionary."""
        app = MockApp(args={"name": "test", "verbose": True})
        assert app.args.name == "test"
        assert app.args.verbose is True
        assert isinstance(app.lg, Mock)
        assert isinstance(app.config, Mock)

    def test_mock_app_with_custom_logger(self):
        """Test MockApp with custom logger."""
        custom_logger = Mock()
        app = MockApp(logger=custom_logger)
        assert app.lg is custom_logger

    def test_mock_app_with_custom_config(self):
        """Test MockApp with custom config."""
        custom_config = Mock()
        app = MockApp(config=custom_config)
        assert app.config is custom_config

    def test_mock_app_complete(self):
        """Test MockApp with all parameters."""
        custom_logger = Mock()
        custom_config = Mock()
        app = MockApp(
            args={"file": "data.txt", "output": "result.txt"},
            logger=custom_logger,
            config=custom_config,
        )
        assert app.args.file == "data.txt"
        assert app.args.output == "result.txt"
        assert app.lg is custom_logger
        assert app.config is custom_config
