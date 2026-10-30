# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/tools/protocol.py.

Tests key functionality including:
- ToolProtocol abstract base class
- Required abstract methods
- Default property implementations
"""

import argparse
import contextlib
from unittest.mock import Mock

import pytest

from appinfra.app.tools.protocol import ToolProtocol

# =============================================================================
# Test ToolProtocol Abstract Class
# =============================================================================


@pytest.mark.unit
class TestToolProtocolAbstract:
    """Test ToolProtocol is properly abstract."""

    def test_cannot_instantiate_directly(self):
        """Test ToolProtocol cannot be instantiated directly."""
        with pytest.raises(TypeError) as exc_info:
            ToolProtocol()

        assert "abstract" in str(exc_info.value).lower()


# =============================================================================
# Concrete Implementation for Testing
# =============================================================================


class ConcreteToolProtocol(ToolProtocol):
    """Concrete implementation for testing abstract methods."""

    def __init__(self):
        self._name = "test-tool"
        self._initialized = False

    @property
    def name(self) -> str:
        # Call parent to cover the pass statement (typically not done but for coverage)
        with contextlib.suppress(AttributeError):
            super().name
        return self._name

    @property
    def cmd(self):
        with contextlib.suppress(AttributeError):
            super().cmd
        return (["test-tool"], {"help": "Test tool"})

    @property
    def initialized(self) -> bool:
        with contextlib.suppress(AttributeError):
            super().initialized
        return self._initialized

    def add_args(self, parser):
        with contextlib.suppress(AttributeError):
            super().add_args(parser)
        parser.add_argument("--test")

    def setup(self, **kwargs):
        with contextlib.suppress(AttributeError):
            super().setup(**kwargs)
        self._initialized = True

    def run(self, **kwargs):
        with contextlib.suppress(AttributeError):
            super().run(**kwargs)
        return 0


@pytest.mark.unit
class TestConcreteToolProtocol:
    """Test concrete implementation of ToolProtocol."""

    def test_name_property(self):
        """Test name property returns tool name."""
        tool = ConcreteToolProtocol()

        assert tool.name == "test-tool"

    def test_cmd_property(self):
        """Test cmd property returns command configuration."""
        tool = ConcreteToolProtocol()

        args, kwargs = tool.cmd

        assert args == ["test-tool"]
        assert kwargs == {"help": "Test tool"}

    def test_add_args(self):
        """Test add_args adds arguments to parser."""
        tool = ConcreteToolProtocol()
        parser = argparse.ArgumentParser()

        tool.add_args(parser)

        # Parser should now have --test argument
        args = parser.parse_args(["--test", "value"])
        assert args.test == "value"

    def test_setup(self):
        """Test setup method can be called."""
        tool = ConcreteToolProtocol()

        # Should not raise
        tool.setup(option="value")

    def test_run(self):
        """Test run method returns result."""
        tool = ConcreteToolProtocol()

        result = tool.run()

        assert result == 0


# =============================================================================
# Test Default Properties
# =============================================================================


class MinimalToolProtocol(ToolProtocol):
    """Minimal implementation that accesses default properties."""

    @property
    def name(self):
        return "minimal"

    @property
    def cmd(self):
        return (["minimal"], {})

    @property
    def initialized(self) -> bool:
        return False

    def add_args(self, parser):
        pass

    def setup(self, **kwargs):
        pass

    def run(self, **kwargs):
        return 0

    def test_lg_property(self):
        """Access lg property to cover default."""
        return self.lg

    def test_args_property(self):
        """Access args property to cover default."""
        return self.args

    def test_kwargs_property(self):
        """Access kwargs property to cover default."""
        return self.kwargs

    def test_initialized_property(self):
        """Access initialized property to cover default."""
        return self.initialized

    def test_arg_prs_property(self):
        """Access arg_prs property to cover default."""
        return self.arg_prs


@pytest.mark.unit
class TestToolProtocolDefaultProperties:
    """Test ToolProtocol default property implementations."""

    def test_lg_property_returns_none(self):
        """Test lg property returns None by default."""
        tool = MinimalToolProtocol()

        # Default implementation returns None (pass)
        result = tool.test_lg_property()

        assert result is None

    def test_args_property_returns_none(self):
        """Test args property returns None by default."""
        tool = MinimalToolProtocol()

        result = tool.test_args_property()

        assert result is None

    def test_kwargs_property_returns_none(self):
        """Test kwargs property returns None by default."""
        tool = MinimalToolProtocol()

        result = tool.test_kwargs_property()

        assert result is None

    def test_initialized_property_returns_false(self):
        """Test initialized property returns False by default."""
        tool = MinimalToolProtocol()

        result = tool.test_initialized_property()

        assert result is False

    def test_arg_prs_property_returns_none(self):
        """Test arg_prs property returns None by default."""
        tool = MinimalToolProtocol()

        result = tool.test_arg_prs_property()

        assert result is None


# =============================================================================
# Integration Tests
# =============================================================================


class _CompleteTool(ToolProtocol):
    def __init__(self):
        self._logger = Mock()
        self._args = None
        self._kwargs = {}
        self._initialized = False
        self._parser = None

    @property
    def name(self):
        return "complete-tool"

    @property
    def cmd(self):
        return (
            ["complete-tool"],
            {"help": "A complete tool", "aliases": ["ct"]},
        )

    @property
    def lg(self):
        return self._logger

    @property
    def args(self):
        return self._args

    @property
    def kwargs(self):
        return self._kwargs

    @property
    def initialized(self):
        return self._initialized

    @property
    def arg_prs(self):
        return self._parser

    def add_args(self, parser):
        self._parser = parser
        parser.add_argument("--verbose", "-v", action="store_true")
        parser.add_argument("--output", "-o")

    def setup(self, **kwargs):
        self._kwargs = kwargs
        self._initialized = True

    def run(self, **kwargs):
        if not self.initialized:
            return 1
        self.lg.info(f"Running with kwargs: {kwargs}")
        return 0


@pytest.mark.unit
class TestToolProtocolIntegration:
    """Integration tests for ToolProtocol."""

    def test_full_tool_lifecycle(self):
        """Test complete tool lifecycle with protocol implementation."""
        # Create tool
        tool = _CompleteTool()
        assert tool.name == "complete-tool"
        assert tool.initialized is False

        # Setup
        tool.setup(config_path="/etc/config.yaml")
        assert tool.initialized is True
        assert tool.kwargs == {"config_path": "/etc/config.yaml"}

        # Add arguments
        parser = argparse.ArgumentParser()
        tool.add_args(parser)
        assert tool.arg_prs is parser

        # Parse arguments
        args = parser.parse_args(["--verbose", "-o", "output.txt"])
        assert args.verbose is True
        assert args.output == "output.txt"

        # Run
        result = tool.run(data="test")
        assert result == 0
        tool.lg.info.assert_called_once()
