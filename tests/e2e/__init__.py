# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
End-to-End Test Suite for Infra Framework

This package contains end-to-end tests that validate complete system workflows
and user journeys across the entire infrastructure framework.

E2E tests are designed to:
- Test full system integration
- Validate complete user workflows
- Ensure all components work together correctly
- Provide comprehensive system validation

Test Types in this Package:
- CLI to Database workflows
- Logging pipeline validation
- Complete application lifecycles
- Error recovery scenarios
- Performance under realistic loads
"""

__version__ = "1.0.0"
__author__ = "Infra Framework Team"

# Export commonly used utilities
__all__ = []

# E2E test configuration
E2E_CONFIG = {
    "timeout": 300,  # 5 minutes default timeout for E2E tests
    "cleanup_on_success": True,
    "cleanup_on_failure": False,  # Keep artifacts for debugging
    "log_level": "INFO",
    "capture_screenshots": False,  # For future web UI testing
    "capture_logs": True,
    "parallel_execution": False,  # E2E tests should run sequentially
}


def get_e2e_config():
    """Get E2E test configuration."""
    return E2E_CONFIG.copy()
