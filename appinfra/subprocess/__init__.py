# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Subprocess infrastructure for child processes.

This module provides utilities for subprocess lifecycle management,
including signal handling, config hot-reload, and graceful shutdown.
"""

from .context import SubprocessContext
from .lazy import Lazy

__all__ = ["Lazy", "SubprocessContext"]
