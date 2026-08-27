# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Common parameter sets for parametrized tests.

Provides reusable parameter sets that can be used across multiple
test modules to reduce duplication.
"""

from typing import Any

import pytest

# =============================================================================
# Invalid Input Parameters
# =============================================================================

INVALID_TYPES = [
    pytest.param(None, id="None"),
    pytest.param([], id="empty_list"),
    pytest.param({}, id="empty_dict"),
    pytest.param(123, id="int"),
    pytest.param(True, id="bool"),
]

INVALID_STRINGS = [
    pytest.param("", id="empty_string"),
    pytest.param("   ", id="whitespace"),
    pytest.param("\n\t", id="newlines_tabs"),
]

INVALID_NUMBERS = [
    pytest.param(-1, id="negative"),
    pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="infinity"),
    pytest.param(float("-inf"), id="neg_infinity"),
]


# =============================================================================
# Security Test Parameters
# =============================================================================

SQL_INJECTION_PAYLOADS = [
    pytest.param("'; DROP TABLE users; --", id="drop_table"),
    pytest.param("1' OR '1'='1", id="always_true"),
    pytest.param("admin' --", id="comment_out"),
    pytest.param("1' UNION SELECT * FROM passwords--", id="union_select"),
]

PATH_TRAVERSAL_PAYLOADS = [
    pytest.param("../../../etc/passwd", id="unix_passwd"),
    pytest.param("..\\..\\..\\windows\\system32", id="windows_system"),
    pytest.param("....//....//....//etc/passwd", id="double_dot_slash"),
    pytest.param("/etc/passwd", id="absolute_path"),
]

XSS_PAYLOADS = [
    pytest.param("<script>alert('XSS')</script>", id="script_tag"),
    pytest.param("<img src=x onerror=alert('XSS')>", id="img_onerror"),
    pytest.param("javascript:alert('XSS')", id="javascript_protocol"),
]


# =============================================================================
# Duration Test Parameters
# =============================================================================

DURATION_VALID_CASES = [
    pytest.param(0, "0s", id="zero"),
    pytest.param(1, "1s", id="one_second"),
    pytest.param(60, "1m", id="one_minute"),
    pytest.param(3600, "1h00m", id="one_hour"),
    pytest.param(86400, "1d00h00m", id="one_day"),
    pytest.param(1.5, "1.500s", id="fractional_seconds"),
    pytest.param(0.001, "1ms", id="one_millisecond"),
    pytest.param(3661.5, "1h01m01.500s", id="complex"),
]

DURATION_INVALID_CASES = [
    pytest.param(-1, id="negative"),
    pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="infinity"),
    pytest.param("not_a_number", id="string"),
]


# =============================================================================
# Configuration Test Parameters
# =============================================================================

CONFIG_VALID_LOG_LEVELS = [
    pytest.param("debug", id="debug"),
    pytest.param("info", id="info"),
    pytest.param("warning", id="warning"),
    pytest.param("error", id="error"),
    pytest.param("critical", id="critical"),
]

CONFIG_INVALID_LOG_LEVELS = [
    pytest.param("invalid", id="invalid_level"),
    pytest.param("", id="empty_string"),
    pytest.param("DEBUG", id="uppercase"),  # Should be lowercase
    pytest.param(123, id="numeric"),
]


# =============================================================================
# Database Test Parameters
# =============================================================================

DB_VALID_PORTS = [
    pytest.param(5432, id="postgresql_default"),
    pytest.param(3306, id="mysql_default"),
    pytest.param(1521, id="oracle_default"),
    pytest.param(8000, id="custom_port"),
]

DB_INVALID_PORTS = [
    pytest.param(-1, id="negative"),
    pytest.param(0, id="zero"),
    pytest.param(65536, id="above_max"),
    pytest.param(70000, id="way_above_max"),
]


# =============================================================================
# Helper Functions
# =============================================================================


def parametrize_with_ids(
    argnames: str, argvalues: list[tuple[Any, ...]], ids: list[str]
) -> pytest.mark.parametrize:
    """
    Create a parametrize decorator with explicit IDs.

    Args:
        argnames: Comma-separated argument names
        argvalues: List of argument value tuples
        ids: List of test IDs

    Returns:
        pytest.mark.parametrize decorator
    """
    return pytest.mark.parametrize(argnames, argvalues, ids=ids)
