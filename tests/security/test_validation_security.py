# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Security tests for tool/alias validation (infra/app/tools/registry.py)."""

import pytest

from appinfra.app.constants import MAX_ALIAS_COUNT, MAX_TOOL_COUNT, MAX_TOOL_NAME_LENGTH
from appinfra.app.errors import DupToolError, ToolRegistrationError
from appinfra.app.tools.base import Tool, ToolConfig
from appinfra.app.tools.registry import ToolRegistry
from tests.security.payloads.injection import SHELL_INJECTION


class MockTool(Tool):
    """Mock tool for testing validation logic."""

    def __init__(self, name: str, aliases: list[str] | None = None):
        """Initialize mock tool with name and optional aliases."""
        config = ToolConfig(
            name=name,
            aliases=aliases or [],
            help_text="Mock tool for testing",
            description="Mock tool",
        )
        super().__init__(parent=None, config=config)

    @property
    def name(self) -> str:
        """Override to handle empty names without raising UndefNameError."""
        # Return the name from config even if empty (for testing)
        if self.config:
            return self.config.name
        # If no config, fall back to parent behavior
        return super().name


@pytest.mark.security
@pytest.mark.unit
@pytest.mark.parametrize("payload", SHELL_INJECTION)
def test_tool_name_shell_injection(payload: str):
    """
    Verify tool name validation blocks shell metacharacters.

    Attack Vector: Command injection via tool name
    Module: infra/app/tools/registry.py:32-37 (_validate_tool_name)
    OWASP: A03:2021 - Injection

    Security Concern: Tool names may be used in shell commands, logs, or
    file paths. Allowing shell metacharacters could enable command injection,
    log forgery, or path traversal attacks.

    The validation enforces the pattern: ^[a-z][a-z0-9_-]*$
    which blocks all shell metacharacters including: ; | & ` $ ( ) < > \n \r
    """
    registry = ToolRegistry()

    # Assert malicious payload is rejected
    with pytest.raises(
        ToolRegistrationError,
        match="Tool name must start with a lowercase letter",
    ):
        tool = MockTool(name=payload)
        registry.register(tool)

    # Assert legitimate names still work (positive case)
    valid_tool = MockTool(name="valid-tool_name")
    registry.register(valid_tool)
    assert "valid-tool_name" in registry.list_tools()


@pytest.mark.security
@pytest.mark.unit
@pytest.mark.parametrize(
    "invalid_name,reason",
    [
        ("Tool", "uppercase first letter"),
        ("TOOL", "all uppercase"),
        ("123tool", "starts with number"),
        ("tool name", "contains space"),
        ("tool@name", "special character @"),
        ("tool#name", "special character #"),
        ("tool.name", "special character ."),
        ("tool/name", "special character /"),
        ("tool\\name", "special character \\"),
        ("tool:name", "special character :"),
        ("_tool", "starts with underscore"),
        ("-tool", "starts with hyphen"),
        ("tööl", "unicode characters"),
        ("tool\x00name", "null byte"),
        ("   ", "whitespace only"),
    ],
)
def test_tool_name_format_validation(invalid_name: str, reason: str):
    """
    Verify tool name format validation enforces strict pattern.

    Attack Vector: Format bypass attempts
    Module: infra/app/tools/registry.py:32-37 (_validate_tool_name)
    OWASP: A03:2021 - Injection

    Security Concern: Tool names must conform to strict format requirements:
    - Must start with a lowercase letter (a-z)
    - Can only contain lowercase letters, numbers, underscores, and hyphens
    - No unicode, no special characters, no whitespace

    This prevents various attacks including injection, encoding bypass,
    and compatibility issues with different shell environments.
    """
    registry = ToolRegistry()

    # Assert invalid name is rejected
    with pytest.raises(ToolRegistrationError):
        tool = MockTool(name=invalid_name)
        registry.register(tool)


@pytest.mark.security
@pytest.mark.unit
def test_tool_name_empty_string():
    """
    Verify empty tool name is rejected.

    Attack Vector: Empty tool name causing undefined behavior
    Module: infra/app/tools/registry.py:23-24 (_validate_tool_name)
    OWASP: A03:2021 - Injection

    Security Concern: Empty tool names should be rejected as they can
    cause undefined behavior in tool lookup and command execution.
    """
    registry = ToolRegistry()

    # Empty string is rejected at validation level
    with pytest.raises(ToolRegistrationError, match="Tool must have a name"):
        tool = MockTool(name="")
        registry.register(tool)

    # Assert legitimate formats still work
    valid_formats = ["tool", "tool123", "tool-name", "tool_name", "t", "abc123-xyz_456"]
    for valid_name in valid_formats:
        registry_test = ToolRegistry()
        valid_tool = MockTool(name=valid_name)
        registry_test.register(valid_tool)
        assert valid_name in registry_test.list_tools()


@pytest.mark.security
@pytest.mark.unit
def test_tool_name_length_limit():
    """
    Verify MAX_TOOL_NAME_LENGTH enforcement prevents excessively long names.

    Attack Vector: Resource exhaustion via extremely long tool names
    Module: infra/app/tools/registry.py:26-30 (_validate_tool_name)
    OWASP: A05:2021 - Security Misconfiguration

    Security Concern: Extremely long tool names can:
    - Consume excessive memory in the registry
    - Cause buffer issues in downstream systems
    - Create unwieldy command-line interfaces
    - Enable DoS via memory exhaustion

    The MAX_TOOL_NAME_LENGTH limit (255 characters) prevents these issues
    while allowing reasonable tool names.
    """
    registry = ToolRegistry()

    # Generate name exceeding MAX_TOOL_NAME_LENGTH (255)
    long_name = "a" * (MAX_TOOL_NAME_LENGTH + 1)

    # Assert long name is rejected
    with pytest.raises(
        ToolRegistrationError,
        match=f"Tool name exceeds maximum length of {MAX_TOOL_NAME_LENGTH}",
    ):
        tool = MockTool(name=long_name)
        registry.register(tool)

    # Verify names at exactly MAX_TOOL_NAME_LENGTH are allowed
    exact_length_name = "a" * MAX_TOOL_NAME_LENGTH
    exact_tool = MockTool(name=exact_length_name)
    registry.register(exact_tool)
    assert exact_length_name in registry.list_tools()

    # Verify reasonable length names work
    normal_name = "normal_tool_name"
    normal_tool = MockTool(name=normal_name)
    registry.register(normal_tool)
    assert normal_name in registry.list_tools()


@pytest.mark.security
@pytest.mark.unit
@pytest.mark.parametrize("payload", SHELL_INJECTION)
def test_tool_alias_injection(payload: str):
    """
    Verify alias validation blocks shell metacharacters.

    Attack Vector: Command injection via tool aliases
    Module: infra/app/tools/registry.py:60-65 (_validate_and_register_aliases)
    OWASP: A03:2021 - Injection

    Security Concern: Tool aliases are subject to the same security risks
    as tool names. They may be used in shell commands, logs, or other
    contexts where shell metacharacters could enable injection attacks.

    The validation applies the same strict pattern to aliases: ^[a-z][a-z0-9_-]*$
    """
    registry = ToolRegistry()

    # Assert malicious alias is rejected
    with pytest.raises(
        ToolRegistrationError,
        match="(Alias .* must start with a lowercase letter|must start with a lowercase letter and contain only lowercase letters)",
    ):
        tool = MockTool(name="goodname", aliases=[payload])
        registry.register(tool)

    # Assert legitimate aliases still work (positive case)
    valid_tool = MockTool(name="tool1", aliases=["alias1", "alias-2", "alias_3"])
    registry.register(valid_tool)
    assert "tool1" in registry.list_tools()
    aliases = registry.list_aliases()
    assert "alias1" in aliases
    assert "alias-2" in aliases
    assert "alias_3" in aliases

    # Verify aliases can be used to retrieve tools
    assert registry.get_tool("alias1") is not None
    assert registry.get_tool("alias1") == valid_tool


@pytest.mark.security
@pytest.mark.unit
def test_tool_count_limit():
    """
    Verify MAX_TOOL_COUNT enforcement prevents DoS via registry exhaustion.

    Attack Vector: Resource exhaustion via excessive tool registration
    Module: infra/app/tools/registry.py:42-46 (_check_tool_count_limit)
    OWASP: A05:2021 - Security Misconfiguration

    Security Concern: Without limits on tool registration count, an attacker
    could:
    - Exhaust memory by registering thousands of tools
    - Slow down tool lookup operations
    - Create unwieldy command-line interfaces
    - Cause DoS via resource exhaustion

    The MAX_TOOL_COUNT limit (1000 tools) prevents these attacks while
    allowing reasonable application complexity.
    """
    registry = ToolRegistry()

    # Register tools up to the limit (MAX_TOOL_COUNT = 1000)
    # For test performance, we'll register close to limit and verify boundary
    # Register up to limit - 1 (should succeed)
    for i in range(MAX_TOOL_COUNT):
        tool = MockTool(name=f"tool{i}")
        registry.register(tool)

    # Verify we have MAX_TOOL_COUNT tools registered
    assert len(registry.list_tools()) == MAX_TOOL_COUNT

    # Attempt to register one more - should fail
    with pytest.raises(
        ToolRegistrationError,
        match=f"maximum tool count \\({MAX_TOOL_COUNT}\\) exceeded",
    ):
        overflow_tool = MockTool(name="overflow")
        registry.register(overflow_tool)

    # Verify count is still at limit
    assert len(registry.list_tools()) == MAX_TOOL_COUNT


# Additional security tests for completeness


@pytest.mark.security
@pytest.mark.unit
def test_duplicate_tool_name_rejected():
    """
    Verify duplicate tool names are rejected to prevent shadowing attacks.

    Attack Vector: Tool shadowing/replacement
    Module: infra/app/tools/registry.py:106-107 (register method)
    OWASP: A04:2021 - Insecure Design

    Security Concern: Allowing duplicate registrations could enable:
    - Tool shadowing (malicious tool replacing legitimate one)
    - Confused deputy attacks
    - Unpredictable behavior when tools are looked up
    """
    registry = ToolRegistry()

    # Register a tool
    tool1 = MockTool(name="mytool")
    registry.register(tool1)

    # Attempt to register another tool with the same name
    with pytest.raises(DupToolError, match="already registered"):
        tool2 = MockTool(name="mytool")
        registry.register(tool2)

    # Verify only the first tool is registered
    assert registry.get_tool("mytool") == tool1


@pytest.mark.security
@pytest.mark.unit
def test_duplicate_alias_rejected():
    """
    Verify duplicate aliases across tools are rejected.

    Attack Vector: Alias collision/shadowing
    Module: infra/app/tools/registry.py:67-71 (_validate_and_register_aliases)
    OWASP: A04:2021 - Insecure Design

    Security Concern: Allowing duplicate aliases across different tools
    creates ambiguity and could enable attacks where a malicious tool
    registers an alias that shadows a legitimate tool's alias.
    """
    registry = ToolRegistry()

    # Register first tool with an alias
    tool1 = MockTool(name="tool1", aliases=["shared"])
    registry.register(tool1)

    # Attempt to register second tool with the same alias
    with pytest.raises(
        ToolRegistrationError,
        match="Alias 'shared' already registered",
    ):
        tool2 = MockTool(name="tool2", aliases=["shared"])
        registry.register(tool2)


@pytest.mark.security
@pytest.mark.unit
def test_alias_count_limit():
    """
    Verify MAX_ALIAS_COUNT enforcement prevents excessive aliases per tool.

    Attack Vector: Resource exhaustion via excessive aliases
    Module: infra/app/tools/registry.py:53-57 (_validate_and_register_aliases)
    OWASP: A05:2021 - Security Misconfiguration

    Security Concern: Without limits on alias count per tool, an attacker
    could exhaust memory and create confusion by registering a tool with
    thousands of aliases.

    The MAX_ALIAS_COUNT limit (100 aliases per tool) prevents this.
    """
    registry = ToolRegistry()

    # Generate alias list exceeding MAX_ALIAS_COUNT (100)
    excessive_aliases = [f"alias{i}" for i in range(MAX_ALIAS_COUNT + 1)]

    # Assert excessive aliases are rejected
    with pytest.raises(
        ToolRegistrationError,
        match=f"exceeding maximum of {MAX_ALIAS_COUNT}",
    ):
        tool = MockTool(name="tool1", aliases=excessive_aliases)
        registry.register(tool)

    # Verify exactly MAX_ALIAS_COUNT aliases are allowed
    exact_count_aliases = [f"alias{i}" for i in range(MAX_ALIAS_COUNT)]
    exact_tool = MockTool(name="tool2", aliases=exact_count_aliases)
    registry.register(exact_tool)
    assert "tool2" in registry.list_tools()
    assert len(registry.list_aliases()) == MAX_ALIAS_COUNT
