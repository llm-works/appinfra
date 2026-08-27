# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.log.__init__ module."""

import logging

import pytest

from appinfra.log import (
    InvalidLogLevelError,
    Logger,
    create_lg,
    create_root_lg,
    derive_lg,
    resolve_level,
)


@pytest.mark.unit
class TestResolveLevel:
    """Test resolve_level function."""

    def test_resolve_level_with_bool_true(self):
        """Test resolve_level with True."""
        assert resolve_level(True) is True

    def test_resolve_level_with_bool_false(self):
        """Test resolve_level with False."""
        assert resolve_level(False) is False

    def test_resolve_level_with_numeric_string(self):
        """Test resolve_level with numeric string."""
        assert resolve_level("10") == 10
        assert resolve_level("20") == 20

    def test_resolve_level_with_valid_level_name(self):
        """Test resolve_level with valid level names."""
        assert resolve_level("debug") == logging.DEBUG
        assert resolve_level("info") == logging.INFO
        assert resolve_level("warning") == logging.WARNING
        assert resolve_level("error") == logging.ERROR

    def test_resolve_level_with_custom_levels(self):
        """Test resolve_level with custom trace levels."""
        trace_level = resolve_level("trace")
        trace2_level = resolve_level("trace2")
        assert isinstance(trace_level, int)
        assert isinstance(trace2_level, int)
        assert trace2_level < trace_level < logging.DEBUG

    def test_resolve_level_with_invalid_level(self):
        """Test resolve_level with invalid level raises error."""
        with pytest.raises(InvalidLogLevelError):
            resolve_level("invalid_level")

    def test_resolve_level_with_int(self):
        """Test resolve_level with integer converts to string and resolves."""
        # Integer that's not in numeric range will be looked up as string
        result = resolve_level(123)
        assert result == 123


@pytest.mark.unit
class TestConvenienceFunctions:
    """Test convenience functions for logger creation."""

    def test_create_root_lg(self):
        """Test create_root_lg function."""
        lg = create_root_lg(level="debug", location=True, micros=True)
        assert isinstance(lg, Logger)
        # Root logger has "/" as name in this system
        assert lg.name in ["/", "root"]

    def test_create_root_lg_defaults(self):
        """Test create_root_lg with defaults."""
        lg = create_root_lg()
        assert isinstance(lg, Logger)

    def test_create_lg(self):
        """Test create_lg function."""
        lg = create_lg("testlogger", level="info", location=1, micros=False)
        assert isinstance(lg, Logger)
        assert lg.name == "testlogger"

    def test_derive_lg(self):
        """Test derive_lg function."""
        parent = create_root_lg("info")
        child = derive_lg(parent, "subsystem")
        assert isinstance(child, Logger)

    def test_derive_lg_with_none_cls(self):
        """Test derive_lg with None class (uses parent's class)."""
        parent = create_root_lg("info")
        child = derive_lg(parent, "test", cls=None)
        assert isinstance(child, Logger)
        assert type(child) is type(parent)

    def test_derive_lg_with_explicit_cls(self):
        """Test derive_lg with explicit class."""
        parent = create_root_lg("info")
        child = derive_lg(parent, ["tag1", "tag2"], cls=Logger)
        assert isinstance(child, Logger)
