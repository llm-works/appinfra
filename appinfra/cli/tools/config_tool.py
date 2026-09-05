# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Configuration inspection tool for the appinfra CLI.

Parent tool ``config`` with two sub-tools:

- ``dump`` (default): render the fully resolved configuration content
  (YAML, JSON, or flat key=value), with includes expanded, environment
  variables applied, and variable substitutions completed.
- ``source``: report where the config was resolved from, which
  precedence rule fired, and which XDG candidates were checked.

Bare ``appinfra config`` runs ``dump``.
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from ...app.tools import Tool, ToolConfig
from ...app.tracing.traceable import Traceable
from ...config import Config, find_project_local, xdg_candidates

_PRECEDENCE_EPILOG = """\
config-source precedence (v1, checked top-down; first match wins):

  1. --config /abs.yaml | ./rel | ../rel | ~/x     (direct path)
     project_root = the file's parent; --etc-dir is ignored.

  2. --config bare.yaml + --etc-dir /foo           (bare + etc-dir)
     resolves to /foo/bare.yaml; without --etc-dir, to cwd/bare.yaml.

  3. --etc-dir /foo alone                          (etc-dir default)
     resolves to /foo/<package>.yaml.

  4. Project-local walk-up                         (repo checkout)
     walks up from cwd looking for etc/<base-filename>; first hit wins.
     Stops before $HOME and filesystem root, so home dotfiles and
     system /etc are never picked up.

  5. First existing XDG candidate                  (user overlay)
     searched in $XDG_CONFIG_HOME then $XDG_CONFIG_DIRS, per-file first:
       <dir>/<namespace>/<package>.yaml
       <dir>/<namespace>/config.yaml

  6. Packaged base                                 (fallback)
     the file registered via .with_config_spec(...).

--config always bypasses project-local, XDG discovery, and the packaged base.

For the canonical spec and rationale, see the config-protocol guide:
  appinfra docs show config-protocol
"""


class ConfigDumpTool(Tool):
    """Render the fully resolved configuration content."""

    def __init__(self, parent: Traceable | None = None):
        """Initialize the dump sub-tool."""
        config = ToolConfig(
            name="dump",
            aliases=["d"],
            help_text="Render the fully resolved configuration content",
            description=(
                "Load and display the fully resolved configuration file "
                "with all includes expanded, environment variables applied, "
                "and variable substitutions completed. "
                "Supports YAML, JSON, and flat (key=value) output formats."
            ),
        )
        super().__init__(parent, config)

    def add_args(self, parser: Any) -> None:
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
        """Load, filter, format, and print the resolved config."""
        config_data = self._load_config()
        if config_data is None:
            return 1

        config_data = self._filter_section(config_data)
        if config_data is None:
            return 1

        print(self._format_output(config_data))
        return 0

    def _load_config(self) -> dict[str, Any] | None:
        """Load and resolve configuration file."""
        config_path = getattr(self.args, "config_file", None) or "etc/infra.yaml"

        path = Path(config_path)
        if not path.exists():
            self.lg.error("config file not found", extra={"path": config_path})  # type: ignore[union-attr]
            return None

        try:
            enable_env = not getattr(self.args, "no_env", False)
            cfg = Config(str(path), enable_env_overrides=enable_env)
            data = cfg.to_dict()
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
        return {section.split(".")[-1]: current}

    def _format_output(self, data: dict[str, Any]) -> str:
        """Format data according to selected format."""
        output_format = getattr(self.args, "format", "yaml")
        if output_format == "json":
            return self._format_json(data)
        if output_format == "flat":
            return self._format_flat(data)
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


class ConfigSourceTool(Tool):
    """Report which precedence rule chose the loaded config."""

    def __init__(self, parent: Traceable | None = None):
        """Initialize the source sub-tool."""
        config = ToolConfig(
            name="source",
            aliases=["s"],
            help_text="Report config source + precedence chain",
            description=(
                "Print where the config was resolved from, which precedence "
                "rule fired, and which XDG candidates were checked. Reports "
                "provenance, not content — use `dump` for the resolved YAML."
            ),
        )
        super().__init__(parent, config)

    def add_args(self, parser: Any) -> None:
        """Show the precedence-chain reference at the top of --help output."""
        parser.description = f"{parser.description or ''}\n\n{_PRECEDENCE_EPILOG}"
        parser.formatter_class = argparse.RawDescriptionHelpFormatter

    def run(self, **kwargs: Any) -> int:
        """Print the source-report."""
        print(self._render_source_report())
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
        """Identify which precedence rule (1-6) produced the loaded path."""
        if custom_cfg is not None:
            if self._is_direct_path(custom_cfg):
                return "1 (--config direct path)"
            where = "--etc-dir" if custom_etc else "cwd"
            return f"2 (--config bare + {where})"
        if custom_etc is not None:
            return "3 (--etc-dir alone)"
        project_local = find_project_local(spec.base_config)
        if (
            loaded_path is not None
            and project_local is not None
            and str(project_local) == str(loaded_path)
        ):
            return "4 (project-local)"
        candidates = xdg_candidates(spec.namespace, spec.package)
        if loaded_path is not None and any(
            str(c) == str(loaded_path) for c in candidates
        ):
            return "5 (XDG overlay)"
        return "6 (packaged base)"

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
        project-local and XDG lines the winner is marked ``[x]``,
        existing-but-not-chosen entries get ``[·]``, missing entries stay
        ``[ ]``.
        """
        won = {str(i): False for i in range(1, 7)}
        won[winning[:1]] = True
        mark = lambda r: "[x]" if won[r] else "[ ]"  # noqa: E731
        cfg = custom_cfg or ""
        etc = custom_etc or ""
        loaded_str = str(loaded_path) if loaded_path else ""

        out = [
            f"  {mark('1')} 1. --config direct path"
            + (f" ({cfg})" if won["1"] else ""),
            f"  {mark('2')} 2. --config bare filename"
            + (f" ({cfg})" if won["2"] else ""),
            f"  {mark('3')} 3. --etc-dir alone"
            + (f" ({etc}/{spec.package}.yaml)" if won["3"] else ""),
            self._project_local_line(spec, won["4"], loaded_str),
            "  5. XDG candidates:",
        ]
        out.extend(self._xdg_lines(spec, won["5"], loaded_str))
        base = Path(str(spec.base_config)).expanduser().resolve()
        out.append(f"  {mark('6')} 6. packaged base ({base})")
        return out

    def _project_local_line(self, spec: Any, won: bool, loaded_str: str) -> str:
        """Format the rule-4 project-local line for the chain rendering."""
        project_local = find_project_local(spec.base_config)
        if project_local is None:
            return "  [ ] 4. project-local (no etc/<base-filename> above cwd)"
        glyph = "[x]" if (won and str(project_local) == loaded_str) else "[·]"
        return f"  {glyph} 4. project-local ({project_local})"

    def _xdg_lines(self, spec: Any, won: bool, loaded_str: str) -> list[str]:
        """Format the rule-5 XDG candidate lines for the chain rendering."""
        lines: list[str] = []
        for c in xdg_candidates(spec.namespace, spec.package):
            matched = won and str(c) == loaded_str
            glyph = "[x]" if matched else ("[·]" if c.exists() else "[ ]")
            lines.append(f"       {glyph} {c}")
        return lines


class ConfigTool(Tool):
    """
    Parent tool for configuration inspection.

    Bare ``appinfra config`` (aka ``c``, ``cfg``) runs ``dump``; ``source``
    reports which precedence rule fired instead of the resolved content.
    """

    def __init__(self, parent: Traceable | None = None):
        """Initialize the parent + register sub-tools."""
        config = ToolConfig(
            name="config",
            aliases=["c", "cfg"],
            help_text="Inspect configuration (dump content or report source)",
            description=(
                "Configuration inspection. `dump` (default) renders the "
                "fully resolved YAML/JSON/flat content; `source` reports "
                "which precedence rule fired and which candidates got checked."
            ),
        )
        super().__init__(parent, config)

        # `dump` registered first so it becomes the group default —
        # bare `appinfra c` runs it instead of printing help.
        self.add_tool(ConfigDumpTool(self), default="dump")
        self.add_tool(ConfigSourceTool(self))

    def add_args(self, parser: Any) -> None:
        """Point to the source sub-tool + docs guide for further reading."""
        parser.description = (
            f"{parser.description or ''}\n\n"
            "For deeper reference:\n"
            "  config source --help              precedence chain reference\n"
            "  appinfra docs show config-protocol  full guide + rationale"
        )
        parser.formatter_class = argparse.RawDescriptionHelpFormatter

    def run(self, **kwargs: Any) -> int:
        """Dispatch to the selected sub-tool (defaults to `dump`)."""
        return self.group.run(**kwargs)
