# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Relative links in appinfra's Markdown resolve, anchors included.

The docs are standard Markdown (CommonMark), parsed here by a CommonMark parser: links in code
are not links, and a relative link resolves from the file that holds it. Links to other sites
are not followed. CommonMark defines no heading anchors; a #fragment must match a heading under
GitHub's anchor convention, so that links also work where GitHub renders the docs. GitHub's
extensions to Markdown (explicit `<a id>` anchors, for one) are not modeled.

The docs and examples are read mostly from the installed package (`appinfra docs`), where
the repo root and its symlinks don't exist: a link from a file inside the package must
resolve inside the package. Files outside it, such as the changelog, take a URL.
"""

import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

from markdown_it import MarkdownIt
from markdown_it.token import Token

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE = _REPO_ROOT / "appinfra"

_MD = MarkdownIt("commonmark")


def _markdown_files() -> list[Path]:
    files = [*(_PACKAGE / "docs").rglob("*.md"), *(_PACKAGE / "examples").rglob("*.md")]
    return sorted(files) + [_REPO_ROOT / "README.md", _REPO_ROOT / "CHANGELOG.md"]


def _tokens(path: Path) -> list[Token]:
    return _MD.parse(path.read_text(encoding="utf-8"))


def _plain_text(inline: Token) -> str:
    """The text an inline token renders: link text, code as written, no markup."""
    children = inline.children or []
    return "".join(c.content for c in children if c.type in ("text", "code_inline"))


def _anchor(text: str) -> str:
    """The anchor of heading text, GitHub's convention: lowercase, punctuation dropped, spaces
    to hyphens."""
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def _slug(heading: str) -> str:
    """The anchor of a heading written as Markdown."""
    return _anchor(_plain_text(_MD.parseInline(heading)[0]))


def _anchors(path: Path) -> set[str]:
    """The anchors of the headings of ``path``; a repeated one gets a -1, -2 ... suffix."""
    anchors: set[str] = set()
    seen: Counter[str] = Counter()
    tokens = _tokens(path)
    for i, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        slug = _anchor(_plain_text(tokens[i + 1]))
        anchors.add(f"{slug}-{seen[slug]}" if seen[slug] else slug)
        seen[slug] += 1
    return anchors


def _link_targets(path: Path) -> list[str]:
    """The targets of the links and images in the prose of ``path``."""
    targets = []
    for token in _tokens(path):
        for child in token.children or []:
            if child.type == "link_open":
                targets.append(unquote(str(child.attrGet("href"))))
            elif child.type == "image":
                targets.append(unquote(str(child.attrGet("src"))))
    return targets


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
                "",
                "Runs pair only with runs as long: `unclosed [linked](linked.md)``",
            ]
        ),
        encoding="utf-8",
    )
    assert _link_targets(doc) == ["real.md", "after.md", "linked.md"]


def test_slug_follows_the_rendered_heading():
    """An anchor comes from the text a heading renders, not from its markup."""
    cases = {
        "_Setup_": "setup",
        "**Bold** text": "bold-text",
        "`_private`": "_private",
        "load_file": "load_file",
        "See [the guide](guide.md) first": "see-the-guide-first",
        "`[label](file.md)`": "labelfilemd",
        "[`App`](app.md)": "app",
        "Reading `app.etc_dir`": "reading-appetc_dir",
        "6. `--config` and `--etc-dir` are user-authoritative": (
            "6---config-and---etc-dir-are-user-authoritative"
        ),
    }
    assert {heading: _slug(heading) for heading in cases} == cases


def test_link_targets_skip_fenced_blocks(tmp_path: Path):
    """A block ends only at a bare fence of its own character, at least as long."""
    doc = tmp_path / "doc.md"
    doc.write_text(
        "\n".join(
            [
                "[one](1.md)",
                "````markdown",
                "```python",
                "[code](c1.md)",
                "```",
                "~~~",
                "````",
                "[two](2.md)",
                "```",
                "```text",
                "[code](c2.md)",
                "```",
                "[three](3.md)",
                "~~~",
                "```",
                "[code](c3.md)",
                "~~~",
                "[four](4.md)",
            ]
        ),
        encoding="utf-8",
    )
    assert _link_targets(doc) == ["1.md", "2.md", "3.md", "4.md"]
