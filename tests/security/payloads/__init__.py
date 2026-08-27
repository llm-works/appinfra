# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Security test payloads for testing attack prevention."""

from .injection import (
    ENV_VAR_INJECTION,
    LOG_INJECTION,
    SHELL_INJECTION,
    YAML_CODE_EXECUTION,
)
from .redos import (
    ALTERNATION_EXPLOSION,
    KNOWN_EVIL_PATTERNS,
    NESTED_QUANTIFIERS,
)
from .resource_exhaustion import (
    BILLION_LAUGHS_YAML,
    generate_deep_yaml_includes,
    generate_large_config,
)
from .traversal import (
    ABSOLUTE_PATH_ESCAPE,
    CLASSIC_TRAVERSAL,
    NULL_BYTE_BYPASS,
)

__all__ = [
    # Injection
    "YAML_CODE_EXECUTION",
    "SHELL_INJECTION",
    "ENV_VAR_INJECTION",
    "LOG_INJECTION",
    # Traversal
    "CLASSIC_TRAVERSAL",
    "ABSOLUTE_PATH_ESCAPE",
    "NULL_BYTE_BYPASS",
    # ReDoS
    "NESTED_QUANTIFIERS",
    "ALTERNATION_EXPLOSION",
    "KNOWN_EVIL_PATTERNS",
    # Resource Exhaustion
    "BILLION_LAUGHS_YAML",
    "generate_deep_yaml_includes",
    "generate_large_config",
]
