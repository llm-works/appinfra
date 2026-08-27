# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Core application framework components.

This module provides the fundamental building blocks for the application framework:
- Application lifecycle management
- Tool registration and discovery
- Configuration management
"""

from .app import App
from .config import ConfigLoader, create_config
from .lifecycle import LifecycleManager
from .logging_utils import setup_logging_from_config

__all__ = [
    "App",
    "LifecycleManager",
    "ConfigLoader",
    "setup_logging_from_config",
    "create_config",
]
