# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Enhanced argument parsing utilities.

This module provides custom argument parsing formatters and utilities
that extend the standard argparse functionality with improved help formatting.
"""

import argparse


class DefaultsHelpFormatter(argparse.HelpFormatter):
    """
    Custom help formatter that automatically displays default values.

    Extends the standard argparse HelpFormatter to automatically append
    default values to help text, making it easier for users to understand
    the default behavior of command-line arguments.
    """

    def _get_help_string(self, action: argparse.Action) -> str:
        """
        Get the help string for an action with default value appended.

        Automatically appends the default value to the help text unless
        the default is suppressed or None, providing better user experience.

        Args:
            action: ArgumentParser action object

        Returns:
            str: Help string with default value appended if applicable
        """
        help_text = action.help or ""
        # Only show default if it's not suppressed and not None
        if action.default is not argparse.SUPPRESS and action.default is not None:
            return help_text + f" (default: {action.default})"
        return help_text
