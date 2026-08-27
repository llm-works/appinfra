# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Observability module for monitoring and instrumentation.

This module provides simple callback-based hooks for monitoring framework
operations without requiring external dependencies like OpenTelemetry.
"""

from .hooks import HookContext, HookEvent, ObservabilityHooks

__all__ = ["ObservabilityHooks", "HookEvent", "HookContext"]
