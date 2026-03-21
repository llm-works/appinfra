"""
Configuration resolution tool for the appinfra CLI.

Displays fully resolved configuration with includes expanded,
environment variables applied, and variable substitutions completed.
"""

import json
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from ...app.tools import Tool, ToolConfig
from ...app.tracing.traceable import Traceable
from ...config import Config


class ConfigTool(Tool):
    """
    CLI tool to display fully resolved configuration.

    Supports three output formats:
    - yaml: YAML format (default, human-readable)
    - json: JSON format (for programmatic consumption)
    - flat: key=value format (for shell scripts, grep, etc.)
    """

    def __init__(self, parent: Traceable | None = None):
        """Initialize the config tool."""
        config = ToolConfig(
            name="config",
            aliases=["c", "cfg"],
            help_text="Display fully resolved configuration",
            description=(
                "Load and display the fully resolved configuration file "
                "with all includes expanded, environment variables applied, "
                "and variable substitutions completed. "
                "Supports YAML, JSON, and flat (key=value) output formats."
            ),
        )
        super().__init__(parent, config)

    def add_args(self, parser: Any) -> None:
        """Add command-line arguments."""
        parser.add_argument(
            "config_file",
            nargs="?",
            default=None,
            help="Path to config file (default: etc/infra.yaml)",
        )
        parser.add_argument(
            "--format",
            "-f",
            choices=["yaml", "json", "flat"],
            default="yaml",
            help="Output format (default: yaml)",
        )
        parser.add_argument(
            "--no-env",
            action="store_true",
            help="Disable environment variable overrides",
        )
        parser.add_argument(
            "--section",
            "-s",
            default=None,
            help="Show only a specific section (e.g., 'logging' or 'dbs.main')",
        )

    def run(self, **kwargs: Any) -> int:
        """Execute the config resolution."""
        config_data = self._load_config()
        if config_data is None:
            return 1

        config_data = self._filter_section(config_data)
        if config_data is None:
            return 1

        output = self._format_output(config_data)
        print(output)
        return 0

    def _load_config(self) -> dict[str, Any] | None:
        """Load and resolve configuration file."""
        config_path = self.args.config_file

        if config_path is None:
            config_path = "etc/infra.yaml"

        path = Path(config_path)
        if not path.exists():
            self.lg.error("config file not found", extra={"path": config_path})  # type: ignore[union-attr]
            return None

        try:
            enable_env = not getattr(self.args, "no_env", False)
            cfg = Config(str(path), enable_env_overrides=enable_env)
            data = cfg.to_dict()
            # Filter out internal Config attributes (start with underscore)
            return {k: v for k, v in data.items() if not k.startswith("_")}
        except yaml.YAMLError as e:
            self.lg.error("YAML parse error", extra={"exception": e})  # type: ignore[union-attr]
            return None
        except Exception as e:
            self.lg.error("failed to load config", extra={"exception": e})  # type: ignore[union-attr]
            return None

    def _filter_section(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Filter to a specific section if requested."""
        section = getattr(self.args, "section", None)
        if section is None:
            return data

        current: Any = data
        for part in section.split("."):
            if not isinstance(current, dict) or part not in current:
                self.lg.error("section not found", extra={"section": section})  # type: ignore[union-attr]
                return None
            current = current[part]

        if isinstance(current, dict):
            return current
        else:
            return {section.split(".")[-1]: current}

    def _format_output(self, data: dict[str, Any]) -> str:
        """Format data according to selected format."""
        output_format = self.args.format

        if output_format == "json":
            return self._format_json(data)
        elif output_format == "flat":
            return self._format_flat(data)
        else:
            return self._format_yaml(data)

    def _format_yaml(self, data: dict[str, Any]) -> str:
        """Format data as YAML."""
        result: str = yaml.dump(
            data,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            indent=2,
        )
        return result.rstrip()

    def _format_json(self, data: dict[str, Any]) -> str:
        """Format data as JSON."""
        return json.dumps(data, indent=2, sort_keys=False)

    def _format_flat(self, data: dict[str, Any]) -> str:
        """Format data as flat key=value lines."""
        pairs = self._flatten_dict(data)
        return "\n".join(f"{key}={value}" for key, value in pairs)

    def _flatten_dict(
        self, data: dict[str, Any], prefix: str = ""
    ) -> list[tuple[str, str]]:
        """Recursively flatten a dictionary to key=value pairs."""
        result: list[tuple[str, str]] = []

        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key

            if isinstance(value, dict):
                result.extend(self._flatten_dict(value, full_key))
            elif isinstance(value, list):
                result.append((full_key, self._format_list_value(value)))
            elif value is None:
                result.append((full_key, ""))
            elif isinstance(value, bool):
                result.append((full_key, str(value).lower()))
            else:
                result.append((full_key, str(value)))

        return result

    def _format_list_value(self, value: list[Any]) -> str:
        """Format a list value for flat output."""
        if all(isinstance(v, (str, int, float, bool)) for v in value):
            return ",".join(str(v) for v in value)
        return json.dumps(value)
