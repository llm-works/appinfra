# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Hierarchical attribute access.

This module provides the Traceable base class that enables hierarchical
attribute lookup through parent-child relationships.
"""

from .traceable import Traceable

__all__ = ["Traceable"]
