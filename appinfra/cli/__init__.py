# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
CLI tools and utilities for appinfra.

This module provides command-line interface components including output
abstractions for testable CLI tools.
"""

from .output import BufferedOutput, ConsoleOutput, NullOutput

__all__ = [
    "ConsoleOutput",
    "BufferedOutput",
    "NullOutput",
]
