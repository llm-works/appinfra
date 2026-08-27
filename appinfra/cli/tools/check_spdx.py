# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""SPDX license header check and application.

Verifies every git-tracked source file (Python, shell, Makefile,
Dockerfile) carries required SPDX header markers in its first N lines.
All target file types share `#` line-comment syntax so a single header
template works across them.

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
import fnmatch
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

# Source file basenames the check covers. All target types share `#`
# line-comment syntax so a single header template covers them all.
DEFAULT_PATTERNS: tuple[str, ...] = (
    "*.py",
    "*.pyi",
    "*.sh",
    "*.bash",
    "Makefile",
    "Makefile.*",
    "*.mk",
    "Dockerfile",
    "*.Dockerfile",
    "*.dockerfile",
)

# Basenames excluded even if they match DEFAULT_PATTERNS. `.in` files are
# scaffolding templates — downstream projects generated from them supply
# their own copyright.
EXCLUDE_PATTERNS: tuple[str, ...] = ("*.in",)


def _filter_source_files(paths: list[str]) -> list[Path]:
    """Filter file paths to those matching DEFAULT_PATTERNS (basename fnmatch).

    Match is on basename so a pattern like `Makefile.*` picks up fragments
    in any subdirectory, not just at the repo root. EXCLUDE_PATTERNS takes
    precedence over DEFAULT_PATTERNS.
    """
    matched: list[Path] = []
    for line in paths:
        if not line:
            continue
        basename = Path(line).name
        if any(fnmatch.fnmatch(basename, pat) for pat in EXCLUDE_PATTERNS):
            continue
        if any(fnmatch.fnmatch(basename, pat) for pat in DEFAULT_PATTERNS):
            matched.append(Path(line))
    return matched


def tracked_source_files() -> list[Path]:
    """Return git-tracked source file paths matching DEFAULT_PATTERNS."""
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return _filter_source_files(result.stdout.splitlines())


def apply_headers(
    files: list[Path], header: str, dry_run: bool
) -> tuple[int, int, Path | None]:
    """Apply header to files missing it.

    Returns (modified, skipped, first_error_path). first_error_path is
    None on success, or the path where the read failed.
    """
    modified = 0
    skipped = 0
    for path in files:
        if not missing_markers(path):
            skipped += 1
            continue
        try:
            text = path.read_text(encoding="utf-8")
            new_text = apply_header_to_text(text, header)
            if not dry_run:
                path.write_text(new_text, encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return modified, skipped, path
        modified += 1
    return modified, skipped, None


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
        TypeError: [project] name is present but not a string.
    """
    root = cwd or Path.cwd()
    with (root / "pyproject.toml").open("rb") as f:
        data = tomllib.load(f)
    try:
        name = data["project"]["name"]
    except KeyError as e:
        raise KeyError(
            "pyproject.toml has no [project] name; pass --package explicitly"
        ) from e
    if not isinstance(name, str):
        raise TypeError(
            "pyproject.toml [project] name is not a string; pass --package explicitly"
        )
    return name


def _print_offenders(offenders: list[tuple[Path, list[str]]]) -> None:
    """Print offender list + fix guidance to stderr."""
    print(
        f"FAIL: {len(offenders)} source file(s) missing SPDX header:",
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
    """Tool for checking + applying SPDX license headers on source files."""

    def __init__(self, parent: Any = None):
        """Initialize the SPDX check tool."""
        config = ToolConfig(
            name="check-spdx",
            aliases=["spdx"],
            help_text="Check or apply SPDX license headers on tracked source files",
            description=(
                "Assert every git-tracked source file (Python, shell, "
                "Makefile, Dockerfile) carries the required "
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
            files = tracked_source_files()
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
        except (FileNotFoundError, KeyError, TypeError) as e:
            self.lg.warning(  # type: ignore[union-attr]
                "could not derive package name", extra={"exception": e}
            )
            return 1
        year = self.args.year or _dt.datetime.now().year
        header = build_header(package, year)
        counts = self._apply_headers_to_files(files, header)
        if counts is None:
            return 1
        modified, skipped = counts
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

    def _apply_headers_to_files(
        self, files: list[Path], header: str
    ) -> tuple[int, int] | None:
        """Thin wrapper around `apply_headers` that logs the first read error."""
        modified, skipped, err = apply_headers(files, header, self.args.dry_run)
        if err is not None:
            self.lg.warning(  # type: ignore[union-attr]
                "read error", extra={"path": str(err)}
            )
            return None
        return modified, skipped
