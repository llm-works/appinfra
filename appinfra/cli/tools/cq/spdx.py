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

The license is the [project] license SPDX expression of ./pyproject.toml
(Apache-2.0 when it has none) unless --license is passed. For --fix, package
attribution is auto-derived from ./pyproject.toml [project] name unless
--package is passed. Year defaults to the current year unless --year is passed.

Exit Codes:
    0: All files carry required markers (check) or apply succeeded (fix)
    1: One or more files missing markers (check), a file declaring another
       license (fix), or apply failed
"""

from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ....app.tools import Tool, ToolConfig

LICENSE_MARKER = "SPDX-License-Identifier:"
COPYRIGHT_MARKER = "SPDX-FileCopyrightText:"
DEFAULT_LICENSE = "Apache-2.0"
"""License used when pyproject.toml declares none."""
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


@dataclass
class ApplyResult:
    """What `apply_headers` did: files changed, already fine, left alone, or failed."""

    modified: int = 0
    skipped: int = 0
    conflicts: list[Path] = field(default_factory=list)
    """Files whose header declares another license; left unchanged."""
    error: Path | None = None
    """The file a read or write failed on; nothing after it was processed."""


def apply_headers(
    files: list[Path], header: str, license_expr: str, dry_run: bool
) -> ApplyResult:
    """Prepend ``header`` to files missing the markers for ``license_expr``.

    A file whose header already declares a different license is left as is and
    listed in ``conflicts``: prepending would give it two license lines.
    """
    result = ApplyResult()
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            result.error = path
            return result
        head = text.splitlines()[:HEADER_SCAN_LINES]
        declared = _declared_licenses(head)
        if declared and license_expr not in declared:
            result.conflicts.append(path)
        elif not _missing(head, license_expr):
            result.skipped += 1
        else:
            if not dry_run and not _write(path, apply_header_to_text(text, header)):
                result.error = path
                return result
            result.modified += 1
    return result


def _write(path: Path, text: str) -> bool:
    """Write ``text`` to ``path``; False if the write failed."""
    try:
        path.write_text(text, encoding="utf-8")
    except OSError:
        return False
    return True


def _declared_licenses(head: list[str]) -> list[str]:
    """Return the license expressions that ``SPDX-License-Identifier`` lines declare."""
    return [
        line.split(LICENSE_MARKER, 1)[1].strip()
        for line in head
        if LICENSE_MARKER in line
    ]


def _missing(head: list[str], license_expr: str) -> list[str]:
    """Return the markers ``head`` lacks; the license must match ``license_expr`` exactly."""
    missing = []
    if license_expr not in _declared_licenses(head):
        missing.append(f"{LICENSE_MARKER} {license_expr}")
    if not any(COPYRIGHT_MARKER in line for line in head):
        missing.append(COPYRIGHT_MARKER)
    return missing


def missing_markers(path: Path, license_expr: str) -> list[str]:
    """Return the SPDX markers for ``license_expr`` not present in path's first N lines.

    The license line must declare exactly ``license_expr``: ``MIT-0`` does not
    satisfy ``MIT``, nor ``Apache-2.0 WITH LLVM-exception`` satisfy ``Apache-2.0``.
    """
    try:
        head = path.read_text(encoding="utf-8").splitlines()[:HEADER_SCAN_LINES]
    except (OSError, UnicodeDecodeError) as e:
        return [f"read error: {e}"]
    return _missing(head, license_expr)


def collect_offenders(
    files: list[Path], license_expr: str
) -> list[tuple[Path, list[str]]]:
    """Return (path, missing_markers) pairs for files missing any marker."""
    return [(p, m) for p in files if (m := missing_markers(p, license_expr))]


def build_header(package: str, year: int, license_expr: str) -> str:
    """Return the 2-line SPDX header plus one trailing blank line."""
    return (
        f"# {LICENSE_MARKER} {license_expr}\n"
        f"# {COPYRIGHT_MARKER} Copyright {year} The {package} Authors\n"
        "\n"
    )


def check_license(value: object, source: str) -> str:
    """Return ``value`` stripped if it can be a header's license; raise ValueError if not.

    It must be a non-empty, one-line string: it is written into every header.
    """
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\n" in value
        or "\r" in value
    ):
        raise ValueError(f"{source} must be a one-line SPDX expression, got {value!r}")
    return value.strip()


def derive_license(cwd: Path | None = None) -> str:
    """Return the [project] license SPDX expression of ./pyproject.toml.

    Without pyproject.toml or the field, the license is :data:`DEFAULT_LICENSE`.

    Raises:
        ValueError: pyproject.toml is not valid TOML, or the field is not a
            one-line SPDX expression (the older ``{text = ...}`` / ``{file = ...}``
            table form included).
        OSError: pyproject.toml exists but cannot be read.
    """
    path = (cwd or Path.cwd()) / "pyproject.toml"
    try:
        with path.open("rb") as f:
            project = tomllib.load(f).get("project")
    except FileNotFoundError:
        return DEFAULT_LICENSE
    value = project.get("license") if isinstance(project, dict) else None
    if value is None:
        return DEFAULT_LICENSE
    if isinstance(value, dict):
        raise ValueError(
            "pyproject.toml [project] license is a table, not an SPDX expression; "
            'set it to one (license = "MIT") or pass --license'
        )
    return check_license(value, "pyproject.toml [project] license")


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


def _print_offenders(
    offenders: list[tuple[Path, list[str]]], license_expr: str
) -> None:
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
        f"    # {LICENSE_MARKER} {license_expr}\n"
        f"    # {COPYRIGHT_MARKER} Copyright <year> The <package> Authors\n"
        "    <blank line>",
        file=sys.stderr,
    )


def _print_conflicts(conflicts: list[Path], license_expr: str) -> None:
    """Print the files --fix left alone because they declare another license."""
    print(
        f"FAIL: {len(conflicts)} source file(s) declare a license other than "
        f"{license_expr}; left unchanged:",
        file=sys.stderr,
    )
    for path in conflicts:
        print(f"  {path}", file=sys.stderr)
    print(
        f"\nCorrect their {LICENSE_MARKER.rstrip(':')} line by hand if they belong "
        f"under {license_expr}.",
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
                "License and package name auto-derived from ./pyproject.toml "
                "(license: Apache-2.0 when it declares none); year defaults to current."
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
        parser.add_argument(
            "--license",
            default=None,
            help=(
                "SPDX license expression for the headers (default: [project] "
                f"license of pyproject.toml, {DEFAULT_LICENSE} when it has none)"
            ),
        )

    def run(self, **kwargs: Any) -> int:
        """Execute the SPDX header check or fix."""
        license_expr = self._license()
        if license_expr is None:
            return 1
        try:
            files = tracked_source_files()
        except subprocess.CalledProcessError as e:
            self.lg.warning("git ls-files failed", extra={"exception": e})
            return 1

        if self.args.fix:
            return self._run_fix(files, license_expr)
        return self._run_check(files, license_expr)

    def _license(self) -> str | None:
        """Return --license, else the pyproject.toml license; None (logged) if invalid."""
        try:
            if self.args.license is not None:
                return check_license(self.args.license, "--license")
            return derive_license()
        except (OSError, ValueError) as e:
            self.lg.warning("could not determine the license", extra={"exception": e})
            return None

    def _run_check(self, files: list[Path], license_expr: str) -> int:
        """Check mode: report offenders, exit 1 if any."""
        offenders = collect_offenders(files, license_expr)
        if not offenders:
            self.lg.info(
                "SPDX headers OK",
                extra={"files_checked": len(files), "license": license_expr},
            )
            return 0
        self.lg.warning(
            "SPDX headers missing",
            extra={
                "missing_count": len(offenders),
                "total": len(files),
                "license": license_expr,
            },
        )
        _print_offenders(offenders, license_expr)
        return 1

    def _run_fix(self, files: list[Path], license_expr: str) -> int:
        """Fix mode: prepend headers to files missing them."""
        try:
            package = self.args.package or derive_package_name()
        except (OSError, KeyError, TypeError, ValueError) as e:  # ValueError: bad TOML
            self.lg.warning("could not derive package name", extra={"exception": e})
            return 1
        year = self.args.year or _dt.datetime.now().year
        header = build_header(package, year, license_expr)
        result = self._apply_headers_to_files(files, header, license_expr)
        if result is None:
            return 1
        self.lg.info(
            "SPDX headers " + ("(dry-run)" if self.args.dry_run else "applied"),
            extra={
                "package": package,
                "year": year,
                "license": license_expr,
                "modified": result.modified,
                "skipped": result.skipped,
                "conflicts": len(result.conflicts),
                "dry_run": self.args.dry_run,
            },
        )
        if result.conflicts:
            _print_conflicts(result.conflicts, license_expr)
            return 1
        return 0

    def _apply_headers_to_files(
        self, files: list[Path], header: str, license_expr: str
    ) -> ApplyResult | None:
        """Thin wrapper around `apply_headers` that logs the first read or write error."""
        result = apply_headers(files, header, license_expr, self.args.dry_run)
        if result.error is not None:
            self.lg.warning(
                "could not read or write file", extra={"path": str(result.error)}
            )
            return None
        return result
