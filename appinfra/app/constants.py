# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Application-wide constants and resource limits.

This module defines resource limits to prevent DoS attacks and ensure
system stability.

Note: MAX_CONFIG_SIZE_BYTES has moved to appinfra.config.constants
"""

# Resource limits for security and stability
MAX_TOOL_COUNT = 1000  # Maximum number of tools that can be registered
MAX_TRACE_DEPTH = 1000  # Maximum depth for attribute tracing to prevent stack overflow
MAX_TOOL_NAME_LENGTH = 255  # Maximum length for tool names
MAX_ALIAS_COUNT = 100  # Maximum number of aliases per tool
