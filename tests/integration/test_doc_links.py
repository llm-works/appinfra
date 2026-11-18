# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Relative links in appinfra's Markdown resolve, anchors included.

A link resolves the way GitHub renders it: the path is relative to the file that holds the
link, and a #fragment must match a heading of the target page under GitHub's anchor rules.
Links to other sites are not followed.

The docs and examples are read mostly from the installed package (`appinfra docs`), where
the repo root and its symlinks don't exist: a link from a file inside the package must
resolve inside the package. Files outside it, such as the changelog, take a URL.
"""

import re
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE = _REPO_ROOT / "appinfra"

_LINK = re.compile(r"\]\(([^)\s]+)")
_HEADING = re.compile(r"#{1,6}\s+(.*?)\s*#*\s*$")
_FENCE = ("```", "~~~")


def _markdown_files() -> list[Path]:
    files = [*(_PACKAGE / "docs").rglob("*.md"), *(_PACKAGE / "examples").rglob("*.md")]
    return sorted(files) + [_REPO_ROOT / "README.md", _REPO_ROOT / "CHANGELOG.md"]


def _prose_lines(path: Path) -> list[str]:
    """The lines of ``path`` outside fenced code blocks."""
    lines, fenced = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith(_FENCE):
            fenced = not fenced
        elif not fenced:
            lines.append(line)
    return lines


def _slug(heading: str) -> str:
    """GitHub's anchor for a heading: lowercase, punctuation dropped, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    """Every anchor GitHub generates for the headings of ``path``."""
    anchors: set[str] = set()
    seen: Counter[str] = Counter()
    for line in _prose_lines(path):
        match = _HEADING.match(line)
        if match is None:
            continue
        slug = _slug(match.group(1))
        anchors.add(f"{slug}-{seen[slug]}" if seen[slug] else slug)
        seen[slug] += 1
    return anchors


def _broken(path: Path, target: str) -> str | None:
    """Why ``target``, linked from ``path``, does not resolve, or None if it does."""
    file_part, _, fragment = target.partition("#")
    dest = (path.parent / file_part).resolve() if file_part else path
    if path.is_relative_to(_PACKAGE) and not dest.is_relative_to(_PACKAGE):
        return "outside the installed package"
    if not dest.exists():
        return "no such file"
    if fragment and dest.suffix == ".md" and fragment not in _anchors(dest):
        return "no such heading"
    return None


def test_relative_links_resolve():
    problems = []
    for path in _markdown_files():
        for line in _prose_lines(path):
            for target in _LINK.findall(line):
                if re.match(r"[a-z][a-z0-9+.-]*:", target):
                    continue  # http:, mailto: and other schemes
                reason = _broken(path, target)
                if reason is not None:
                    rel = path.relative_to(_REPO_ROOT)
                    problems.append(f"{rel}: {target} ({reason})")
    assert not problems, "broken links:\n" + "\n".join(problems)
