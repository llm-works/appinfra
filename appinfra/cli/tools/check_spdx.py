# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""SPDX license header check and application.

Verifies every git-tracked .py file carries required SPDX header markers
in its first N lines. Runs cross-repo when appinfra is installed as a
dependency — the check is repo-agnostic (asserts marker presence, not
attribution string).

Two modes:

    appinfra cq spdx           # check (default) — exits 1 if any file missing markers
    appinfra cq spdx --fix     # apply — prepend SPDX header to missing files

For --fix, package attribution is auto-derived from ./pyproject.toml
[project] name unless --package is passed. Year defaults to the current
year unless --year is passed.

Exit Codes:
    0: All files carry required markers (check) or apply succeeded (fix)
    1: One or more files missing markers (check) OR apply failed
"""

from __future__ import annotations

import argparse
import datetime as _dt
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

from ...app.tools import Tool, ToolConfig

REQUIRED_MARKERS: tuple[str, ...] = (
    "SPDX-License-Identifier: Apache-2.0",
    "SPDX-FileCopyrightText:",
)
HEADER_SCAN_LINES = 5


def tracked_py_files() -> list[Path]:
    """Return git-tracked .py file paths (relative to repo root)."""
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [Path(line) for line in result.stdout.splitlines() if line]


def missing_markers(path: Path) -> list[str]:
    """Return required SPDX markers not present in path's first N lines."""
    try:
        head = "\n".join(
            path.read_text(encoding="utf-8").splitlines()[:HEADER_SCAN_LINES]
        )
    except (OSError, UnicodeDecodeError) as e:
        return [f"read error: {e}"]
    return [m for m in REQUIRED_MARKERS if m not in head]


def collect_offenders(files: list[Path]) -> list[tuple[Path, list[str]]]:
    """Return (path, missing_markers) pairs for files missing any marker."""
    return [(p, m) for p in files if (m := missing_markers(p))]


def build_header(package: str, year: int) -> str:
    """Return the 2-line SPDX header plus one trailing blank line."""
    return (
        "# SPDX-License-Identifier: Apache-2.0\n"
        f"# SPDX-FileCopyrightText: Copyright {year} The {package} Authors\n"
        "\n"
    )


def apply_header_to_text(text: str, header: str) -> str:
    """Prepend `header` to `text`.

    Preserves shebang; inserts one blank line between shebang and header
    so the OS-level directive stays visually separate from license
    metadata. Dedupes any leading blank in the file body so we never
    emit two consecutive blanks after the header.
    """
    lines = text.splitlines(keepends=True)
    if lines and lines[0].startswith("#!"):
        shebang, rest = lines[0] + "\n", lines[1:]
    else:
        shebang, rest = "", lines
    if rest and rest[0].strip() == "":
        rest = rest[1:]
    return shebang + header + "".join(rest)


def derive_package_name(cwd: Path | None = None) -> str:
    """Return the [project] name field from ./pyproject.toml.

    Raises:
        FileNotFoundError: pyproject.toml not present.
        KeyError: [project] name field missing.
    """
    root = cwd or Path.cwd()
    with (root / "pyproject.toml").open("rb") as f:
        data = tomllib.load(f)
    try:
        return data["project"]["name"]
    except KeyError as e:
        raise KeyError(
            "pyproject.toml has no [project] name; pass --package explicitly"
        ) from e


def _print_offenders(offenders: list[tuple[Path, list[str]]]) -> None:
    """Print offender list + fix guidance to stderr."""
    print(
        f"FAIL: {len(offenders)} .py file(s) missing SPDX header:",
        file=sys.stderr,
    )
    for path, missing in offenders:
        print(f"  {path}: missing {missing}", file=sys.stderr)
    print(
        "\nApply headers with:\n"
        "    appinfra cq spdx --fix\n"
        "\nOr add manually to top of each file (after shebang if present):\n"
        "    # SPDX-License-Identifier: Apache-2.0\n"
        "    # SPDX-FileCopyrightText: Copyright <year> The <package> Authors\n"
        "    <blank line>",
        file=sys.stderr,
    )


class CheckSpdxTool(Tool):
    """Tool for checking + applying SPDX license headers on tracked .py files."""

    def __init__(self, parent: Any = None):
        """Initialize the SPDX check tool."""
        config = ToolConfig(
            name="check-spdx",
            aliases=["spdx"],
            help_text="Check or apply SPDX license headers on tracked .py files",
            description=(
                "Assert every git-tracked .py file carries the required "
                "SPDX-License-Identifier and SPDX-FileCopyrightText markers "
                f"in its first {HEADER_SCAN_LINES} lines. "
                "Default: check-only, exits 1 on missing headers. "
                "With --fix: prepend the header to missing files. "
                "Package name auto-derived from ./pyproject.toml; year defaults to current."
            ),
        )
        super().__init__(parent, config)

    def add_args(self, parser: argparse.ArgumentParser) -> None:
        """Add CLI arguments."""
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Apply headers to missing files (default: check only)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="With --fix, report changes without writing files",
        )
        parser.add_argument(
            "--package",
            default=None,
            help="Package name for attribution (default: derive from pyproject.toml)",
        )
        parser.add_argument(
            "--year",
            type=int,
            default=None,
            help="Copyright year (default: current year)",
        )

    def run(self, **kwargs: Any) -> int:
        """Execute the SPDX header check or fix."""
        try:
            files = tracked_py_files()
        except subprocess.CalledProcessError as e:
            self.lg.warning("git ls-files failed", extra={"exception": e})  # type: ignore[union-attr]
            return 1

        if self.args.fix:
            return self._run_fix(files)
        return self._run_check(files)

    def _run_check(self, files: list[Path]) -> int:
        """Check mode: report offenders, exit 1 if any."""
        offenders = collect_offenders(files)
        if not offenders:
            self.lg.info(  # type: ignore[union-attr]
                "SPDX headers OK", extra={"files_checked": len(files)}
            )
            return 0
        self.lg.warning(  # type: ignore[union-attr]
            "SPDX headers missing",
            extra={"missing_count": len(offenders), "total": len(files)},
        )
        _print_offenders(offenders)
        return 1

    def _run_fix(self, files: list[Path]) -> int:
        """Fix mode: prepend headers to files missing them."""
        try:
            package = self.args.package or derive_package_name()
        except (FileNotFoundError, KeyError) as e:
            self.lg.warning(  # type: ignore[union-attr]
                "could not derive package name", extra={"exception": e}
            )
            return 1
        year = self.args.year or _dt.datetime.now().year
        header = build_header(package, year)

        modified = 0
        skipped = 0
        for path in files:
            if not missing_markers(path):
                skipped += 1
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                self.lg.warning(  # type: ignore[union-attr]
                    "read error", extra={"path": str(path), "exception": e}
                )
                return 1
            new_text = apply_header_to_text(text, header)
            if not self.args.dry_run:
                path.write_text(new_text, encoding="utf-8")
            modified += 1

        self.lg.info(  # type: ignore[union-attr]
            "SPDX headers " + ("(dry-run)" if self.args.dry_run else "applied"),
            extra={
                "package": package,
                "year": year,
                "modified": modified,
                "skipped": skipped,
                "dry_run": self.args.dry_run,
            },
        )
        return 0
