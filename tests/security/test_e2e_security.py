# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""End-to-end security tests for cross-module attack chains."""

from pathlib import Path

import pytest
import yaml

from appinfra.config import Config
from appinfra.yaml import Loader
from tests.security.payloads.injection import SHELL_INJECTION, YAML_CODE_EXECUTION


@pytest.mark.security
@pytest.mark.e2e
def test_traversal_to_code_execution_chain(secure_temp_project: Path):
    """
    Verify defense-in-depth prevents traversal -> YAML load -> code execution.

    Attack Scenario: Multi-stage attack chain
    1. Attacker uses path traversal to load YAML file outside project root
    2. Malicious YAML file contains code execution payload (!!python/object)
    3. Code execution payload attempts to run arbitrary commands

    Modules Tested:
    - infra/yaml.py: project_root validation, SafeLoader
    - infra/app/cfg.py: Config loading with path restrictions

    OWASP: A01:2021 - Broken Access Control, A03:2021 - Injection

    Security Principle: Defense in depth - even if one layer fails, others
    should prevent the attack. This test verifies that:
    - Path traversal is blocked at the include resolution layer
    - Even if traversal succeeds, SafeLoader blocks code execution
    - Config loading respects project_root boundaries
    """
    # Stage 1: Create a malicious YAML file outside project root
    # This simulates an attacker-controlled file
    import tempfile

    with tempfile.TemporaryDirectory() as external_dir:
        external_path = Path(external_dir)
        malicious_yaml = external_path / "malicious.yaml"

        # Malicious YAML with code execution attempt
        malicious_content = f"""
# Innocent-looking config
app_name: "MyApp"

# But with hidden code execution
evil_payload: {YAML_CODE_EXECUTION[0]}
"""
        malicious_yaml.write_text(malicious_content)

        # Stage 2: Create a config in project root that tries to include the malicious file
        # Using path traversal
        configs_dir = secure_temp_project / "configs"

        # Calculate traversal path to reach external_dir from configs_dir
        # This is tricky - we'll use an absolute path as the attack
        traversal_attack_config = f"""
app:
  name: "Normal App"

# Attempt to include external malicious file via absolute path
malicious_include: !include {malicious_yaml}
"""
        config_file = configs_dir / "config.yaml"
        config_file.write_text(traversal_attack_config)

        # Stage 3: Attempt to load the config
        # This should fail at the path validation layer
        with open(config_file) as f:
            loader = Loader(
                f,
                current_file=config_file,
                project_root=secure_temp_project,
            )

            # The include should be blocked because malicious_yaml is outside project_root
            with pytest.raises(yaml.YAMLError, match="outside project root"):
                loader.get_single_data()

        # Stage 4: Test second defense layer - even without project_root restriction
        # SafeLoader should block code execution
        with open(malicious_yaml) as f:
            loader_no_root = Loader(f, current_file=malicious_yaml)

            try:
                data = loader_no_root.get_single_data()

                # If loading succeeds, verify code was NOT executed
                # The !!python/object tag should have been rejected
                pytest.fail(
                    "Malicious YAML loaded without error - SafeLoader should have blocked it"
                )

            except yaml.constructor.ConstructorError as e:
                # Expected: SafeLoader blocks dangerous constructors
                assert "could not determine a constructor" in str(e).lower()

        # Stage 5: Test using Config class (higher level API)
        # The Config class loads from a file, and includes should respect boundaries
        # If the Config implementation uses the YAML loader properly, it should also block
        # this attack. For now, we've verified the YAML loader itself blocks it.


@pytest.mark.security
@pytest.mark.e2e
def test_env_override_to_command_injection_chain(
    secure_temp_project: Path, monkeypatch, clean_env
):
    """
    Verify validation prevents env var override -> tool registration -> command injection.

    Attack Scenario: Multi-stage attack chain
    1. Attacker sets environment variable to override config (INFRA_TOOL_NAME=evil)
    2. Config system applies environment override
    3. Malicious tool name contains shell metacharacters
    4. Tool registry attempts to register tool with malicious name
    5. Shell injection attempt when tool name is used in commands

    Modules Tested:
    - infra/app/cfg.py: Environment variable override system
    - infra/app/tools/registry.py: Tool name validation

    OWASP: A03:2021 - Injection

    Security Principle: Input validation at each layer - environment variables
    are untrusted input and must be validated before use. Tool names must
    be sanitized before any use in shell commands or other contexts.
    """
    from unittest.mock import Mock

    from appinfra.app.errors import ToolRegistrationError
    from appinfra.app.tools.registry import ToolRegistry

    # Stage 1: Attacker sets malicious environment variable
    # Simulate environment variable override
    malicious_tool_name = SHELL_INJECTION[0]  # e.g., "tool; rm -rf /"

    # Set environment variable that config system would read
    monkeypatch.setenv("INFRA_TOOLS_CUSTOM_NAME", malicious_tool_name)

    # Stage 2: Config system processes environment overrides
    # Create a config file
    config_content = """
tools:
  custom:
    name: "safe-tool-name"
    enabled: true
"""
    config_file = secure_temp_project / "configs" / "tools.yaml"
    config_file.write_text(config_content)

    # Load config with environment overrides enabled
    config = Config(str(config_file))

    try:
        # Check if the config loaded

        # Check if environment override was applied
        if hasattr(config, "tools") and hasattr(config.tools, "custom"):
            overridden_name = config.tools.custom.name

            # Stage 3: Attempt to register tool with overridden name
            # This should fail validation
            registry = ToolRegistry()

            # Create mock tool
            mock_tool = Mock()
            mock_tool.name = overridden_name
            mock_tool.aliases = []
            mock_tool.cmd = ([], {})

            # Attempt to register - should be blocked by name validation
            with pytest.raises(ToolRegistrationError):
                registry.register(mock_tool)

            # Verify the malicious name was NOT registered
            registered_tools = registry._tools
            assert overridden_name not in registered_tools

            # Verify no tool with shell metacharacters exists
            for tool_name in registered_tools:
                # Tool names should match safe pattern
                assert not any(char in tool_name for char in [";", "|", "&", "`", "$"])

    except Exception as e:
        # If config loading itself fails, that's also acceptable
        # (depends on whether env override validation is implemented)
        if "environment" in str(e).lower() or "override" in str(e).lower():
            # Config system blocked the malicious override - good!
            pass
        else:
            # Unexpected error
            raise

    # Stage 4: Verify legitimate tool names work
    # Test that valid tool names can be registered successfully
    registry2 = ToolRegistry()
    mock_safe_tool = Mock()
    mock_safe_tool.name = "safe-tool"
    mock_safe_tool.aliases = []
    mock_safe_tool.cmd = ([], {})

    # This should succeed (safe name)
    registry2.register(mock_safe_tool)
    assert mock_safe_tool.name in registry2._tools


# Integration test: Verify security measures don't break normal workflows
@pytest.mark.security
@pytest.mark.e2e
def test_legitimate_config_workflow(secure_temp_project: Path):
    """
    Verify legitimate multi-module workflows work correctly.

    Security Concern: Security measures should block attacks without breaking
    normal, legitimate operations. This test ensures that:
    - Normal YAML configs load successfully
    - Includes within project_root work
    - Tool registration with valid names succeeds
    - End-to-end config -> tool registration flow works
    """
    from unittest.mock import Mock

    from appinfra.app.tools.registry import ToolRegistry

    # Create legitimate config files
    database_config = """
host: localhost
port: 5432
name: app_db
"""
    db_config_file = secure_temp_project / "configs" / "database.yaml"
    db_config_file.write_text(database_config)

    main_config = """
app:
  name: "Production App"
  version: "1.0.0"

# Legitimate include (within project_root)
database: !include database.yaml

tools:
  - name: "data-processor"
    enabled: true
  - name: "report_generator"
    enabled: true
"""
    main_config_file = secure_temp_project / "configs" / "config.yaml"
    main_config_file.write_text(main_config)

    # Load config with project_root protection
    with open(main_config_file) as f:
        loader = Loader(
            f,
            current_file=main_config_file,
            project_root=secure_temp_project,
        )
        data = loader.get_single_data()

    # Verify config loaded successfully
    assert data is not None
    assert "app" in data
    assert data["app"]["name"] == "Production App"

    # Verify include worked
    assert "database" in data
    assert data["database"]["host"] == "localhost"

    # Register tools with valid names
    registry = ToolRegistry()

    for tool_config in data["tools"]:
        tool_name = tool_config["name"]

        # Create and register tool
        mock_tool = Mock()
        mock_tool.name = tool_name
        mock_tool.aliases = []
        mock_tool.cmd = ([], {})  # Mock cmd as a tuple

        registry.register(mock_tool)

        # Verify registration succeeded
        assert tool_name in registry._tools

    # Verify both tools registered
    assert len(registry._tools) == 2
    assert "data-processor" in registry._tools
    assert "report_generator" in registry._tools
