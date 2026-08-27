# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for log color management.

Tests key functionality including:
- ColorManager class methods
- Helper functions for backward compatibility
"""

import logging

import pytest

from appinfra.log.colors import (
    ColorManager,
    _create_color_256,
    _create_gray_level,
)
from appinfra.log.constants import LogConstants

# =============================================================================
# Test ColorManager Class
# =============================================================================


@pytest.mark.unit
class TestColorManager:
    """Test ColorManager class."""

    def test_get_color_for_level_debug(self):
        """Test get_color_for_level for DEBUG."""
        color = ColorManager.get_color_for_level(logging.DEBUG)
        assert color is not None
        assert "\x1b[38" in color

    def test_get_color_for_level_info(self):
        """Test get_color_for_level for INFO."""
        color = ColorManager.get_color_for_level(logging.INFO)
        assert color is not None

    def test_get_color_for_level_unknown(self):
        """Test get_color_for_level for unknown level."""
        color = ColorManager.get_color_for_level(999)
        assert color is None

    def test_create_gray_level_valid(self):
        """Test create_gray_level with valid level."""
        color = ColorManager.create_gray_level(5)
        assert f"\x1b[38;5;{LogConstants.GRAY_BASE + 5}" == color

    def test_create_gray_level_boundary_low(self):
        """Test create_gray_level with level below 0 (line 65)."""
        color = ColorManager.create_gray_level(-1)
        # Should clamp to 0
        assert f"\x1b[38;5;{LogConstants.GRAY_BASE + 0}" == color

    def test_create_gray_level_boundary_high(self):
        """Test create_gray_level with level above max (line 65)."""
        color = ColorManager.create_gray_level(30)  # Above GRAY_MAX_LEVELS (24)
        # Should clamp to max-1
        assert (
            f"\x1b[38;5;{LogConstants.GRAY_BASE + LogConstants.GRAY_MAX_LEVELS - 1}"
            == color
        )

    def test_create_color_256(self):
        """Test create_color_256."""
        color = ColorManager.create_color_256(200)
        assert color == "\x1b[38;5;200"

    def test_create_bold_color(self):
        """Test create_bold_color."""
        base = "\x1b[31"
        bold = ColorManager.create_bold_color(base)
        assert bold == "\x1b[31;1m"

    def test_from_name_basic_colors(self):
        """Test from_name with basic color names."""
        assert ColorManager.from_name("black") == ColorManager.BLACK
        assert ColorManager.from_name("red") == ColorManager.RED
        assert ColorManager.from_name("green") == ColorManager.GREEN
        assert ColorManager.from_name("yellow") == ColorManager.YELLOW
        assert ColorManager.from_name("blue") == ColorManager.BLUE
        assert ColorManager.from_name("magenta") == ColorManager.MAGENTA
        assert ColorManager.from_name("cyan") == ColorManager.CYAN
        assert ColorManager.from_name("white") == ColorManager.WHITE

    def test_from_name_case_insensitive(self):
        """Test from_name is case insensitive."""
        assert ColorManager.from_name("CYAN") == ColorManager.CYAN
        assert ColorManager.from_name("Yellow") == ColorManager.YELLOW
        assert ColorManager.from_name("RED") == ColorManager.RED

    def test_from_name_gray_levels(self):
        """Test from_name with gray levels."""
        assert ColorManager.from_name("gray-0") == ColorManager.create_gray_level(0)
        assert ColorManager.from_name("gray-12") == ColorManager.create_gray_level(12)
        assert ColorManager.from_name("gray-23") == ColorManager.create_gray_level(23)

    def test_from_name_grey_spelling(self):
        """Test from_name supports 'grey' spelling."""
        assert ColorManager.from_name("grey-10") == ColorManager.create_gray_level(10)
        assert ColorManager.from_name("GREY-15") == ColorManager.create_gray_level(15)

    def test_from_name_invalid_gray_level(self):
        """Test from_name with invalid gray level."""
        assert ColorManager.from_name("gray-99") is None
        assert ColorManager.from_name("gray--1") is None
        assert ColorManager.from_name("gray-abc") is None

    def test_from_name_unknown_color(self):
        """Test from_name with unknown color name."""
        assert ColorManager.from_name("purple") is None
        assert ColorManager.from_name("invalid") is None
        assert ColorManager.from_name("notacolor") is None

    def test_from_name_empty_string(self):
        """Test from_name with empty string."""
        assert ColorManager.from_name("") is None
        assert ColorManager.from_name("  ") is None

    def test_from_name_none(self):
        """Test from_name with None."""
        assert ColorManager.from_name(None) is None

    def test_from_name_with_whitespace(self):
        """Test from_name handles whitespace."""
        assert ColorManager.from_name("  cyan  ") == ColorManager.CYAN
        assert ColorManager.from_name(" gray-12 ") == ColorManager.create_gray_level(12)


# =============================================================================
# Test Helper Functions
# =============================================================================


@pytest.mark.unit
class TestHelperFunctions:
    """Test backward compatibility helper functions."""

    def test_create_gray_level_helper(self):
        """Test _create_gray_level helper (line 110)."""
        color = _create_gray_level(10)
        # Should delegate to ColorManager
        assert color == ColorManager.create_gray_level(10)

    def test_create_color_256_helper(self):
        """Test _create_color_256 helper (line 115)."""
        color = _create_color_256(100)
        # Should delegate to ColorManager
        assert color == ColorManager.create_color_256(100)
