# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Configuration resolution tool for the appinfra CLI.

Displays fully resolved configuration with includes expanded,
environment variables applied, and variable substitutions completed.
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from ...app.tools import Tool, ToolConfig
from ...app.tracing.traceable import Traceable
from ...config import Config, xdg_candidates

_PRECEDENCE_EPILOG = """\
config-source precedence (v1, checked top-down; first match wins):

  1. --config /abs.yaml | ./rel | ../rel | ~/x     (direct path)
     project_root = the file's parent; --etc-dir is ignored.

  2. --config bare.yaml + --etc-dir /foo           (bare + etc-dir)
     resolves to /foo/bare.yaml; without --etc-dir, to cwd/bare.yaml.

  3. --etc-dir /foo alone                          (etc-dir default)
     resolves to /foo/<package>.yaml.

  4. First existing XDG candidate                  (user overlay)
     searched in $XDG_CONFIG_HOME then $XDG_CONFIG_DIRS, per-file first:
       <dir>/<namespace>/<package>.yaml
       <dir>/<namespace>/config.yaml

  5. Packaged base                                 (fallback)
     the file registered via .with_config_spec(...).

--config always bypasses XDG discovery and the packaged base.
Run `<cli> config --source` to see which rule fired and what got loaded.
"""


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
        parser.epilog = _PRECEDENCE_EPILOG
        parser.formatter_class = argparse.RawDescriptionHelpFormatter
        self._add_content_args(parser)
        parser.add_argument(
            "--source",
            action="store_true",
            help=(
                "Print where the config was resolved from + which precedence "
                "rule fired + XDG candidates checked, instead of the content"
            ),
        )

    def _add_content_args(self, parser: Any) -> None:
        """Add args controlling what content gets dumped and how."""
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
        if getattr(self.args, "source", False) is True:
            print(self._render_source_report())
            return 0

        config_data = self._load_config()
        if config_data is None:
            return 1

        config_data = self._filter_section(config_data)
        if config_data is None:
            return 1

        output = self._format_output(config_data)
        print(output)
        return 0

    def _render_source_report(self) -> str:
        """Report what config was loaded and which precedence rule matched.

        Uses the App's tracked ``_config_spec`` + ``_loaded_config_paths``
        to name the rule; falls back to a bare loaded-paths listing when
        the App wasn't built with ``.with_config_spec(...)``.
        """
        app = self.app
        loaded = getattr(app, "_loaded_config_paths", [])
        spec = getattr(app, "_config_spec", None)

        lines: list[str] = []
        if loaded:
            for _etc, _name, full in loaded:
                lines.append(f"loaded: {full}")
        else:
            lines.append("loaded: <none>")

        custom_etc = getattr(app, "_parsed_args", None)
        custom_etc = getattr(custom_etc, "etc_dir", None) if custom_etc else None
        custom_cfg = getattr(app, "_parsed_args", None)
        custom_cfg = getattr(custom_cfg, "config", None) if custom_cfg else None
        loaded_path = Path(loaded[0][2]) if loaded else None

        if spec is not None:
            winning = self._determine_winner(spec, custom_etc, custom_cfg, loaded_path)
            lines.append(f"rule:   {winning}")
            lines.append("")
            lines.append("precedence chain (v1):")
            lines.extend(
                self._render_chain(spec, custom_etc, custom_cfg, loaded_path, winning)
            )
        else:
            lines.append("rule:   (app built without .with_config_spec — no chain)")
        return "\n".join(lines)

    def _determine_winner(
        self,
        spec: Any,
        custom_etc: str | None,
        custom_cfg: str | None,
        loaded_path: Path | None,
    ) -> str:
        """Identify which precedence rule (1-5) produced the loaded path."""
        if custom_cfg is not None:
            if self._is_direct_path(custom_cfg):
                return "1 (--config direct path)"
            where = "--etc-dir" if custom_etc else "cwd"
            return f"2 (--config bare + {where})"
        if custom_etc is not None:
            return "3 (--etc-dir alone)"
        candidates = xdg_candidates(spec.namespace, spec.package)
        if loaded_path is not None and any(
            str(c) == str(loaded_path) for c in candidates
        ):
            return "4 (XDG overlay)"
        return "5 (packaged base)"

    def _is_direct_path(self, s: str) -> bool:
        """Match paths treated as direct by the v1 spec."""
        return (
            os.path.isabs(s)
            or s.startswith("./")
            or s.startswith("../")
            or s == "~"
            or s.startswith("~/")
        )

    def _render_chain(
        self,
        spec: Any,
        custom_etc: str | None,
        custom_cfg: str | None,
        loaded_path: Path | None,
        winning: str,
    ) -> list[str]:
        """Format the checkbox-style precedence chain lines.

        Only the winning rule is marked ``[x]``; others are ``[ ]``. On the
        XDG line the winner is marked ``[x]``, existing-but-not-chosen
        candidates get ``[·]``, missing candidates stay ``[ ]``.
        """
        won = {"1": False, "2": False, "3": False, "4": False, "5": False}
        won[winning[:1]] = True

        def mark(rule: str) -> str:
            return "[x]" if won[rule] else "[ ]"

        rule1_shown = custom_cfg if custom_cfg is not None else ""
        rule2_shown = custom_cfg if custom_cfg is not None else ""
        rule3_shown = custom_etc if custom_etc is not None else ""

        out = [
            f"  {mark('1')} 1. --config direct path"
            + (f" ({rule1_shown})" if won["1"] else ""),
            f"  {mark('2')} 2. --config bare filename"
            + (f" ({rule2_shown})" if won["2"] else ""),
            f"  {mark('3')} 3. --etc-dir alone"
            + (f" ({rule3_shown}/{spec.package}.yaml)" if won["3"] else ""),
            "  4. XDG candidates:",
        ]
        loaded_str = str(loaded_path) if loaded_path else ""
        for c in xdg_candidates(spec.namespace, spec.package):
            exists = c.exists()
            matched = won["4"] and str(c) == loaded_str
            glyph = "[x]" if matched else ("[·]" if exists else "[ ]")
            out.append(f"       {glyph} {c}")
        base = Path(str(spec.base_config)).expanduser().resolve()
        out.append(f"  {mark('5')} 5. packaged base ({base})")
        return out

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
