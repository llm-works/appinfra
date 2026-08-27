# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Color management for the logging system.

This module provides centralized ANSI color code management and color
selection logic for different log levels and formatting needs.
"""

import logging

from .constants import LogConstants


class ColorManager:
    """Centralized ANSI color code management."""

    # Basic ANSI color escape sequences
    BLACK = "\x1b[30"
    RED = "\x1b[31"
    GREEN = "\x1b[32"
    YELLOW = "\x1b[33"
    BLUE = "\x1b[34"
    MAGENTA = "\x1b[35"
    CYAN = "\x1b[36"
    WHITE = "\x1b[37"
    DEFAULT = "\x1b[38"

    # Reset sequence to clear formatting
    RESET = LogConstants.RESET

    # Color mapping for different log levels (will be populated after custom levels are defined)
    COLORS: dict[int, str] = {
        logging.DEBUG: "\x1b[38;5;32",  # Green for DEBUG
        logging.INFO: CYAN,  # Cyan for INFO
        logging.WARNING: YELLOW,  # Yellow for WARNING
        logging.ERROR: RED,  # Red for ERROR
        logging.CRITICAL: MAGENTA,  # Magenta for CRITICAL
    }

    @staticmethod
    def get_color_for_level(level: int) -> str | None:
        """
        Get appropriate color for log level.

        Args:
            level: Log level number

        Returns:
            Color escape sequence or None if not found
        """
        return ColorManager.COLORS.get(level)

    @staticmethod
    def create_gray_level(level: int) -> str:
        """
        Create gray color for trace levels.

        Args:
            level: Gray level (0-23 range)

        Returns:
            Gray color escape sequence
        """
        if level < 0 or level >= LogConstants.GRAY_MAX_LEVELS:
            level = max(0, min(level, LogConstants.GRAY_MAX_LEVELS - 1))
        return f"\x1b[38;5;{LogConstants.GRAY_BASE + level}"

    @staticmethod
    def create_color_256(color_code: int) -> str:
        """
        Create 256-color escape sequence.

        Args:
            color_code: Color code (0-255)

        Returns:
            256-color escape sequence
        """
        return f"\x1b[38;5;{color_code}"

    @staticmethod
    def _create_color_map() -> dict[str, str]:
        """Create basic color name to ANSI code mapping."""
        return {
            "black": ColorManager.BLACK,
            "red": ColorManager.RED,
            "green": ColorManager.GREEN,
            "yellow": ColorManager.YELLOW,
            "blue": ColorManager.BLUE,
            "magenta": ColorManager.MAGENTA,
            "cyan": ColorManager.CYAN,
            "white": ColorManager.WHITE,
            "default": ColorManager.DEFAULT,
        }

    @staticmethod
    def _parse_gray_level(name: str) -> str | None:
        """Parse gray/grey level from name (e.g., 'gray-12')."""
        if name.startswith("gray-") or name.startswith("grey-"):
            try:
                level_str = name.split("-", 1)[1]
                level = int(level_str)
                if 0 <= level < LogConstants.GRAY_MAX_LEVELS:
                    return ColorManager.create_gray_level(level)
            except (ValueError, IndexError):
                pass
        return None

    @staticmethod
    def from_name(color_name: str) -> str | None:
        """
        Convert color name to ANSI escape sequence.

        Supports:
        - Basic colors: "black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"
        - Gray levels: "gray-0" through "gray-23" (or "grey-0" through "grey-23")
        - Case insensitive

        Args:
            color_name: Color name string

        Returns:
            ANSI color escape sequence, or None if name is not recognized

        Examples:
            >>> ColorManager.from_name("cyan")
            "\\x1b[36"
            >>> ColorManager.from_name("gray-12")
            "\\x1b[38;5;244"
            >>> ColorManager.from_name("YELLOW")
            "\\x1b[33"
        """
        if not color_name:
            return None

        # Normalize to lowercase
        name = color_name.lower().strip()

        # Check basic colors
        color_map = ColorManager._create_color_map()
        if name in color_map:
            return color_map[name]

        # Check gray/grey levels
        return ColorManager._parse_gray_level(name)

    @staticmethod
    def create_bold_color(base_color: str) -> str:
        """
        Create bold version of a color.

        Args:
            base_color: Base color escape sequence

        Returns:
            Bold color escape sequence
        """
        return f"{base_color};1m"

    @staticmethod
    def add_custom_level_colors() -> None:
        """Add colors for custom log levels after they are defined."""
        from .constants import LogConstants

        ColorManager.COLORS.update(
            {
                LogConstants.CUSTOM_LEVELS["TRACE2"]: ColorManager.create_gray_level(
                    7
                ),  # Light gray for TRACE2
                LogConstants.CUSTOM_LEVELS["TRACE"]: ColorManager.create_color_256(
                    24
                ),  # Blue-gray for TRACE
            }
        )


# Helper functions for backward compatibility
def _create_gray_level(level: int) -> str:
    """Create gray level color (internal helper)."""
    return ColorManager.create_gray_level(level)


def _create_color_256(color_code: int) -> str:
    """Create 256-color (internal helper)."""
    return ColorManager.create_color_256(color_code)
