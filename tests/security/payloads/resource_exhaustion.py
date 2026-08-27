# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Resource exhaustion attack payloads for DoS testing."""

from pathlib import Path

# Billion Laughs Attack (XML/YAML Bomb)
# Exponential entity expansion to exhaust memory
BILLION_LAUGHS_YAML = """
a: &a ["lol","lol","lol","lol","lol","lol","lol","lol","lol"]
b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a]
c: &c [*b,*b,*b,*b,*b,*b,*b,*b,*b]
d: &d [*c,*c,*c,*c,*c,*c,*c,*c,*c]
e: &e [*d,*d,*d,*d,*d,*d,*d,*d,*d]
f: &f [*e,*e,*e,*e,*e,*e,*e,*e,*e]
g: &g [*f,*f,*f,*f,*f,*f,*f,*f,*f]
"""


def generate_deep_yaml_includes(depth: int, base_dir: Path) -> dict[str, str]:
    """
    Generate nested YAML include structure to test depth limits.

    Args:
        depth: Number of nesting levels to create
        base_dir: Directory where YAML files will be created

    Returns:
        Dictionary mapping file paths to their YAML content
    """
    files = {}

    for i in range(depth):
        if i == depth - 1:
            # Leaf file - no includes
            content = f"data: 'level_{i}'\n"
        else:
            # Include the next level
            next_file = f"level_{i + 1}.yaml"
            content = f"!include {next_file}\n"

        file_path = str(base_dir / f"level_{i}.yaml")
        files[file_path] = content

    return files


def generate_large_config(size_mb: int) -> str:
    """
    Generate a configuration file of specified size in megabytes.

    Args:
        size_mb: Target size in megabytes

    Returns:
        String containing the generated config content
    """
    # Generate repetitive YAML content to reach target size
    # Each entry is approximately 50 bytes
    entries_needed = (size_mb * 1024 * 1024) // 50

    lines = ["config:", "  large_data:"]
    for i in range(entries_needed):
        lines.append(f"    key_{i}: 'value_{i}_padding_data_here'")

    return "\n".join(lines)


def generate_circular_includes(base_dir: Path) -> dict[str, str]:
    """
    Generate circular YAML includes (A includes B, B includes A).

    Args:
        base_dir: Directory where YAML files will be created

    Returns:
        Dictionary mapping file paths to their YAML content
    """
    file_a = str(base_dir / "circular_a.yaml")
    file_b = str(base_dir / "circular_b.yaml")

    return {
        file_a: "data_a: 'from_a'\ndata_b: !include circular_b.yaml\n",
        file_b: "data_b: 'from_b'\ndata_a: !include circular_a.yaml\n",
    }


# Large String Payloads
# Strings designed to exhaust memory or cause buffer overflows
LARGE_STRING_PAYLOADS = {
    "1mb": "X" * (1024 * 1024),
    "10mb": "Y" * (10 * 1024 * 1024),
    "100mb": "Z" * (100 * 1024 * 1024),
}


# Tool Count Bomb
# For testing MAX_TOOL_COUNT limits
def generate_many_tool_names(count: int) -> list[str]:
    """
    Generate list of valid tool names to test count limits.

    Args:
        count: Number of tool names to generate

    Returns:
        List of valid tool name strings
    """
    return [f"tool-{i}" for i in range(count)]
