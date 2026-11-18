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
_FENCE = re.compile(r"\s*(`{3,}|~{3,})")
# A link written inside inline code is an example. A span may continue on the next line.
_CODE_SPAN = re.compile(r"(`+).+?\1", re.DOTALL)
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
_INLINE_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_EMPHASIS = re.compile(
    r"(?<!\w)[*_]+|[*_]+(?!\w)"
)  # markers, not underscores inside a word


def _markdown_files() -> list[Path]:
    files = [*(_PACKAGE / "docs").rglob("*.md"), *(_PACKAGE / "examples").rglob("*.md")]
    return sorted(files) + [_REPO_ROOT / "README.md", _REPO_ROOT / "CHANGELOG.md"]


def _prose_lines(path: Path) -> list[str]:
    """The lines of ``path`` outside fenced code blocks; each block leaves one blank line, as
    it ends the paragraph before it.

    A fence closes only on the character that opened it, at least as many times, with nothing
    after it (CommonMark), so a block can show another fence inside it.
    """
    lines: list[str] = []
    fence = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _FENCE.match(line)
        if match and not fence:
            fence = match.group(1)
            lines.append("")
        elif (
            match
            and match.group(1)[0] == fence[0]
            and len(match.group(1)) >= len(fence)
            and not line[match.end() :].strip()
        ):
            fence = ""
        elif not fence:
            lines.append(line)
    return lines


def _visible_text(heading: str) -> str:
    """The text a heading renders: link text only, code as written, no emphasis markers."""
    heading = _INLINE_LINK.sub(r"\1", heading)
    parts, pos = [], 0
    for span in _CODE_SPAN.finditer(heading):
        parts.append(_EMPHASIS.sub("", heading[pos : span.start()]))
        parts.append(span.group(0).strip("`"))
        pos = span.end()
    parts.append(_EMPHASIS.sub("", heading[pos:]))
    return "".join(parts)


def _slug(heading: str) -> str:
    """GitHub's anchor for a heading: its visible text, lowercase, punctuation dropped, spaces
    to hyphens."""
    text = _visible_text(heading).strip().lower()
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


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


def _link_targets(path: Path) -> list[str]:
    """The targets of the links in the prose of ``path``, code spans left out.

    Code spans are matched per paragraph, as a span may continue on the next line.
    """
    targets = []
    for paragraph in _PARAGRAPH_BREAK.split("\n".join(_prose_lines(path))):
        targets += _LINK.findall(_CODE_SPAN.sub("", paragraph))
    return targets


def test_relative_links_resolve():
    problems = []
    for path in _markdown_files():
        for target in _link_targets(path):
            if re.match(r"[a-z][a-z0-9+.-]*:", target):
                continue  # http:, mailto: and other schemes
            reason = _broken(path, target)
            if reason is not None:
                rel = path.relative_to(_REPO_ROOT)
                problems.append(f"{rel}: {target} ({reason})")
    assert not problems, "broken links:\n" + "\n".join(problems)


def test_link_targets_skip_code_spans_across_lines(tmp_path: Path):
    """A code span may continue on the next line; links inside it are examples."""
    doc = tmp_path / "doc.md"
    doc.write_text(
        "\n".join(
            [
                "Write `[example](missing.md) across",
                "two lines` and then see [real](real.md).",
                "",
                "A span may also `open here, then",
                "close` before [after](after.md) and `code`.",
            ]
        ),
        encoding="utf-8",
    )
    assert _link_targets(doc) == ["real.md", "after.md"]


def test_slug_follows_the_rendered_heading():
    """GitHub derives the anchor from the text a heading renders, not its markup."""
    cases = {
        "_Setup_": "setup",
        "**Bold** text": "bold-text",
        "`_private`": "_private",
        "load_file": "load_file",
        "See [the guide](guide.md) first": "see-the-guide-first",
        "Reading `app.etc_dir`": "reading-appetc_dir",
        "6. `--config` and `--etc-dir` are user-authoritative": (
            "6---config-and---etc-dir-are-user-authoritative"
        ),
    }
    assert {heading: _slug(heading) for heading in cases} == cases


def test_prose_lines_skips_fenced_blocks(tmp_path: Path):
    """A block ends only at a bare fence of its own character, at least as long."""
    doc = tmp_path / "doc.md"
    doc.write_text(
        "\n".join(
            [
                "prose 1",
                "````markdown",
                "```python",
                "```",
                "~~~",
                "````",
                "prose 2",
                "```",
                "```text",
                "still code",
                "```",
                "prose 3",
                "~~~",
                "```",
                "~~~",
                "prose 4",
            ]
        ),
        encoding="utf-8",
    )
    assert _prose_lines(doc) == ["prose 1", "", "prose 2", "", "prose 3", "", "prose 4"]
