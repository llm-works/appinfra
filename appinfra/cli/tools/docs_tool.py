# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Documentation browser for appinfra CLI.

Provides access to bundled documentation and examples without requiring
web access or external documentation sites.
"""

from pathlib import Path
from typing import Any

import yaml

from ...app.tools import Tool, ToolConfig
from ...app.tracing.traceable import Traceable
from ..output import ConsoleOutput, OutputWriter


def get_package_root() -> Path:
    """Get the appinfra package root directory."""
    return Path(__file__).parent.parent.parent


def get_docs_dir() -> Path:
    """Get the docs directory (bundled or development)."""
    return get_package_root() / "docs"


def get_examples_dir() -> Path:
    """Get the examples directory (bundled or development)."""
    return get_package_root() / "examples"


def find_doc(docs_dir: Path, topic: str) -> Path | None:
    """Find a documentation file by topic name."""
    if not docs_dir.exists():
        return None

    # Direct match in various locations
    candidates = [
        docs_dir / f"{topic}.md",
        docs_dir / "guides" / f"{topic}.md",
        docs_dir / "api" / f"{topic}.md",
        docs_dir / topic,  # For files without .md extension (e.g., LICENSE)
    ]

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    # Fuzzy match - normalize and search
    topic_normalized = topic.lower().replace("-", "").replace("_", "")
    for md_file in docs_dir.rglob("*.md"):
        name_normalized = md_file.stem.lower().replace("-", "").replace("_", "")
        if topic_normalized == name_normalized:
            return md_file

    return None


def _find_file_in_path(examples_dir: Path, name: str) -> Path | None:
    """Find file using path syntax like '02/app_with_tool.py'."""
    dir_part, file_part = name.split("/", 1)

    # Try direct path first
    direct = examples_dir / name
    if direct.exists() and direct.is_file():
        return direct

    # Try partial directory match (e.g., "02" -> "02_app_framework")
    for example_dir in sorted(examples_dir.iterdir()):
        if example_dir.is_dir() and example_dir.name.startswith(dir_part):
            candidate = example_dir / file_part
            if candidate.exists() and candidate.is_file():
                return candidate
            if not file_part.endswith(".py"):
                candidate_py = example_dir / f"{file_part}.py"
                if candidate_py.exists():
                    return candidate_py
            break
    return None


def _find_direct_match(examples_dir: Path, name: str) -> Path | None:
    """Find direct directory or file match."""
    direct = examples_dir / name
    if direct.exists():
        if direct.is_dir() or direct.is_file():
            return direct
    if not name.endswith(".py"):
        direct_py = examples_dir / f"{name}.py"
        if direct_py.exists() and direct_py.is_file():
            return direct_py
    return None


def _find_partial_dir_match(examples_dir: Path, name: str) -> Path | None:
    """Find partial directory match (e.g., '02' matches '02_app_framework')."""
    for example_dir in sorted(examples_dir.iterdir()):
        if example_dir.is_dir() and example_dir.name.startswith(name):
            return example_dir
    return None


def _find_fuzzy_dir_match(examples_dir: Path, name_normalized: str) -> Path | None:
    """Find directory by fuzzy matching suffix after number prefix."""
    for example_dir in sorted(examples_dir.iterdir()):
        if not example_dir.is_dir() or "_" not in example_dir.name:
            continue
        suffix = example_dir.name.split("_", 1)[1]
        suffix_normalized = suffix.lower().replace("-", "").replace("_", "")
        if name_normalized == suffix_normalized:
            return example_dir
    return None


def _find_file_in_subdirs(
    examples_dir: Path, name: str, name_normalized: str
) -> Path | None:
    """Search for file by name across all example directories."""
    for example_dir in sorted(examples_dir.iterdir()):
        if not example_dir.is_dir():
            continue
        candidate = example_dir / name
        if candidate.exists() and candidate.is_file():
            return candidate
        if not name.endswith(".py"):
            candidate_py = example_dir / f"{name}.py"
            if candidate_py.exists():
                return candidate_py
        for py_file in example_dir.glob("*.py"):
            file_normalized = py_file.stem.lower().replace("-", "").replace("_", "")
            if name_normalized == file_normalized:
                return py_file
    return None


def find_example(examples_dir: Path, name: str) -> Path | None:
    """Find an example directory or file by name.

    Supports:
    - Directory: "02", "02_app_framework", "app_framework"
    - File path: "02/app_with_tool.py", "02_app_framework/app_with_tool.py"
    - File name: "app_with_tool.py", "app_with_tool" (searches all example dirs)
    """
    if not examples_dir.exists():
        return None

    name_base = name[:-3] if name.endswith(".py") else name
    name_normalized = name_base.lower().replace("-", "").replace("_", "")

    # Path with directory component
    if "/" in name:
        result = _find_file_in_path(examples_dir, name)
        if result:
            return result

    # Direct match
    result = _find_direct_match(examples_dir, name)
    if result:
        return result

    # Partial directory match
    result = _find_partial_dir_match(examples_dir, name)
    if result:
        return result

    # Fuzzy directory match
    result = _find_fuzzy_dir_match(examples_dir, name_normalized)
    if result:
        return result

    # Search files in subdirectories
    return _find_file_in_subdirs(examples_dir, name, name_normalized)


def extract_title(md_file: Path) -> str:
    """Extract the first heading from a markdown file."""
    try:
        with open(md_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith("# "):
                    return line[2:].strip()
        return ""
    except Exception:
        return ""


class DocsListTool(Tool):
    """List all available documentation and examples."""

    def __init__(
        self, parent: Traceable | None = None, out: OutputWriter | None = None
    ):
        config = ToolConfig(
            name="list",
            aliases=["ls"],
            help_text="List all available documentation and examples",
        )
        super().__init__(parent, config)
        self.out = out if out is not None else ConsoleOutput()

    def run(self, **kwargs: Any) -> int:
        """List all available documentation and examples."""
        self.out.write("Available Documentation")
        self.out.write("=" * 60)
        self.out.write()

        docs_dir = get_docs_dir()
        if docs_dir.exists():
            self._list_section("GUIDES:", docs_dir / "guides")
            self._list_section("API REFERENCE:", docs_dir / "api", skip_index=True)
            self._list_section("OTHER DOCS:", docs_dir, skip_index=True)

        self._list_examples()

        self.out.write("-" * 60)
        self.out.write("Usage: appinfra docs show <topic>")
        self.out.write("Example: appinfra docs show logging-builder")
        return 0

    def _list_section(
        self, header: str, directory: Path, skip_index: bool = False
    ) -> None:
        """List markdown files in a directory section."""
        self.out.write(header)
        if directory.exists():
            for md_file in sorted(directory.glob("*.md")):
                if skip_index and md_file.stem == "index":
                    continue
                self.out.write(f"  {md_file.stem:<35} {extract_title(md_file)}")
            # Also list LICENSE if present (non-.md file)
            license_file = directory / "LICENSE"
            if license_file.exists() and license_file.is_file():
                self.out.write(f"  {'LICENSE':<35} Project License")
        self.out.write()

    def _list_examples(self) -> None:
        """List available examples."""
        examples_dir = get_examples_dir()
        if not examples_dir.exists():
            return

        self.out.write("EXAMPLES:")
        for example_dir in sorted(examples_dir.iterdir()):
            if not example_dir.is_dir() or example_dir.name.startswith("."):
                continue
            readme = example_dir / "README.md"
            desc = extract_title(readme) if readme.exists() else "(no description)"
            self.out.write(f"  {example_dir.name:<35} {desc}")
        self.out.write()


class DocsShowTool(Tool):
    """Show specific documentation or example."""

    def __init__(
        self, parent: Traceable | None = None, out: OutputWriter | None = None
    ):
        config = ToolConfig(
            name="show",
            aliases=["s"],
            help_text="Show specific documentation topic or example",
        )
        super().__init__(parent, config)
        self.out = out if out is not None else ConsoleOutput()

    def add_args(self, parser: Any) -> None:
        """Add arguments for the show command."""
        parser.add_argument(
            "topic",
            help="Documentation topic or example name (e.g., 'logging-builder', '02_app_framework')",
        )

    def run(self, **kwargs: Any) -> int:
        """Show a specific documentation topic or example."""
        topic = getattr(self.args, "topic", None)
        if not topic:
            self.out.write("Error: Please specify a topic.")
            self.out.write("Usage: appinfra docs show <topic>")
            self.out.write("Run 'appinfra docs list' to see available topics.")
            return 1

        # Strip .md suffix if present (allow "README.md" as well as "README")
        if topic.endswith(".md"):
            topic = topic[:-3]

        docs_dir = get_docs_dir()
        examples_dir = get_examples_dir()

        # Try to find as documentation first
        doc_file = find_doc(docs_dir, topic)
        if doc_file:
            self.out.write(doc_file.read_text())
            return 0

        # Try to find as example
        example_dir = find_example(examples_dir, topic)
        if example_dir:
            return self._show_example(example_dir)

        # Not found
        self.out.write(f"Error: '{topic}' not found in documentation or examples.")
        self.out.write()
        self.out.write("Run 'appinfra docs list' to see available topics.")
        return 1

    def _show_example(self, example_path: Path) -> int:
        """Show an example directory's README/listing, or a file's contents."""
        # If it's a file, just display it
        if example_path.is_file():
            self.out.write(example_path.read_text())
            return 0

        # It's a directory - show README and file listing
        readme = example_path / "README.md"
        if readme.exists():
            self.out.write(readme.read_text())
            self.out.write()

        # List Python files
        py_files = list(example_path.glob("*.py"))
        yaml_files = list(example_path.glob("*.yaml"))
        all_files = sorted(py_files + yaml_files, key=lambda p: p.name)

        if all_files:
            self.out.write("=" * 60)
            self.out.write(f"FILES in {example_path.name}/:")
            self.out.write()
            for f in all_files:
                self.out.write(f"  {f.name}")
            self.out.write()
            self.out.write(f"View with: appinfra docs show {all_files[0].stem}")

        return 0


def parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter from markdown content.

    Args:
        content: Markdown file content

    Returns:
        Dictionary of frontmatter fields, empty dict if no frontmatter
    """
    if not content.startswith("---"):
        return {}
    try:
        # Find closing delimiter
        end = content.index("---", 3)
        frontmatter_text = content[3:end].strip()
        if not frontmatter_text:
            return {}
        return yaml.safe_load(frontmatter_text) or {}
    except (ValueError, Exception):
        return {}


class DocsFindTool(Tool):
    """Search documentation and examples for a pattern."""

    def __init__(
        self, parent: Traceable | None = None, out: OutputWriter | None = None
    ):
        config = ToolConfig(
            name="find",
            aliases=["f", "search"],
            help_text="Search documentation and examples for a pattern",
        )
        super().__init__(parent, config)
        self.out = out if out is not None else ConsoleOutput()

    def add_args(self, parser: Any) -> None:
        """Add arguments for the find command."""
        add = parser.add_argument
        add("pattern", help="Text pattern to search for (case-insensitive)")
        add("-c", "--context", type=int, default=0, help="Context lines around matches")
        add("-w", "--word", action="store_true", help="Match whole words only")
        add("-n", "--max-matches", type=int, default=10, help="Max matches per file")
        add("--docs-only", action="store_true", help="Search only documentation")
        add("--examples-only", action="store_true", help="Search only examples")
        add("--no-color", action="store_true", help="Disable match highlighting")
        add(
            "-z",
            "--fuzzy",
            action="store_true",
            help="Enable fuzzy matching for typos and partial matches",
        )
        add(
            "--threshold",
            type=float,
            default=0.6,
            help="Fuzzy match threshold 0.0-1.0 (default: 0.6)",
        )

    def _get_search_options(self) -> dict[str, Any]:
        """Extract search options from parsed args."""
        args = self.args
        return {
            "word": getattr(args, "word", False),
            "docs_only": getattr(args, "docs_only", False),
            "examples_only": getattr(args, "examples_only", False),
            "context": getattr(args, "context", 0),
            "max_matches": getattr(args, "max_matches", 10),
            "no_color": getattr(args, "no_color", False),
            "fuzzy": getattr(args, "fuzzy", False),
            "threshold": getattr(args, "threshold", 0.6),
        }

    def _display_results(
        self, pattern: str, matches: list, opts: dict[str, Any]
    ) -> None:
        """Display search results."""
        self.out.write(f"Found matches for '{pattern}' in {len(matches)} file(s):")
        self.out.write()
        self._print_matches(
            matches,
            opts["context"],
            opts["max_matches"],
            pattern,
            opts["word"],
            opts["no_color"],
        )
        self.out.write(
            "Tip: View with 'appinfra docs show <topic>' (e.g., 'docs show hot-reload-logging')"
        )

    def run(self, **kwargs: Any) -> int:
        """Search documentation for a pattern."""
        pattern = getattr(self.args, "pattern", None)
        if not pattern:
            self.out.write("Error: Please specify a search pattern.")
            self.out.write("Usage: appinfra docs find <pattern>")
            return 1

        opts = self._get_search_options()
        matches = self._collect_matches(
            pattern,
            opts["word"],
            opts["docs_only"],
            opts["examples_only"],
            opts["fuzzy"],
            opts["threshold"],
        )
        if not matches:
            self.out.write(f"No matches found for '{pattern}'")
            return 0

        self._display_results(pattern, matches, opts)
        return 0

    def _collect_matches(
        self,
        pattern: str,
        word_boundary: bool = False,
        docs_only: bool = False,
        examples_only: bool = False,
        fuzzy: bool = False,
        threshold: float = 0.6,
    ) -> list[tuple[str, list[tuple[int, str]]]]:
        """Collect all matches from docs and examples."""
        matches: list[tuple[str, list[tuple[int, str]]]] = []
        docs_dir = get_docs_dir()
        examples_dir = get_examples_dir()

        if not examples_only and docs_dir.exists():
            self._search_directory(
                docs_dir, "*.md", pattern, matches, word_boundary, fuzzy, threshold
            )

        if not docs_only and examples_dir.exists():
            for suffix in ("*.md", "*.py", "*.yaml"):
                self._search_directory(
                    examples_dir,
                    suffix,
                    pattern,
                    matches,
                    word_boundary,
                    fuzzy,
                    threshold,
                )

        return matches

    def _search_directory(
        self,
        directory: Path,
        glob: str,
        pattern: str,
        matches: list[tuple[str, list[tuple[int, str]]]],
        word_boundary: bool = False,
        fuzzy: bool = False,
        threshold: float = 0.6,
    ) -> None:
        """Search a directory for pattern matches."""
        for file_path in directory.rglob(glob):
            file_matches = self._search_file(
                file_path, pattern, word_boundary, fuzzy, threshold
            )
            if file_matches:
                # Use path relative to docs dir for docs (so paths work with 'docs show')
                docs_dir = get_docs_dir()
                if file_path.is_relative_to(docs_dir):
                    rel_path = file_path.relative_to(docs_dir)
                else:
                    rel_path = file_path.relative_to(get_package_root())
                matches.append((str(rel_path), file_matches))

    def _print_matches(
        self,
        matches: list[tuple[str, list[tuple[int, str]]]],
        context: int = 0,
        max_matches: int = 10,
        pattern: str = "",
        word_boundary: bool = False,
        no_color: bool = False,
    ) -> None:
        """Print search results with optional context lines."""
        for match_path, file_matches in sorted(matches):
            self.out.write(f"  {match_path}")

            if context > 0:
                self._print_matches_with_context(
                    match_path,
                    file_matches,
                    context,
                    max_matches,
                    pattern,
                    word_boundary,
                    no_color,
                )
            else:
                self._print_matches_simple(
                    file_matches, max_matches, pattern, word_boundary, no_color
                )

            self.out.write()

    def _print_matches_simple(
        self,
        file_matches: list[tuple[int, str]],
        max_matches: int,
        pattern: str = "",
        word_boundary: bool = False,
        no_color: bool = False,
    ) -> None:
        """Print matches without context."""
        for line_num, line_content in file_matches[:max_matches]:
            display_line = line_content.strip()
            if len(display_line) > 70:
                display_line = display_line[:70] + "..."
            if pattern and not no_color:
                display_line = self._highlight_match(
                    display_line, pattern, word_boundary
                )
            self.out.write(f"    Line {line_num}: {display_line}")
        if len(file_matches) > max_matches:
            self.out.write(
                f"    ... and {len(file_matches) - max_matches} more matches"
            )

    def _read_file_lines(self, match_path: str) -> list[str] | None:
        """Read file lines, trying package root then docs dir."""
        try:
            file_path = get_package_root() / match_path
            if not file_path.exists():
                file_path = get_docs_dir() / match_path
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                return f.readlines()
        except Exception:
            return None

    def _print_matches_with_context(
        self,
        match_path: str,
        file_matches: list[tuple[int, str]],
        context: int,
        max_matches: int,
        pattern: str = "",
        word_boundary: bool = False,
        no_color: bool = False,
    ) -> None:
        """Print matches with surrounding context lines."""
        all_lines = self._read_file_lines(match_path)
        if all_lines is None:
            self._print_matches_simple(
                file_matches, max_matches, pattern, word_boundary, no_color
            )
            return

        printed_lines: set[int] = set()
        matches_shown = 0

        for line_num, _ in file_matches:
            if matches_shown >= max_matches:
                remaining = len(file_matches) - matches_shown
                if remaining > 0:
                    self.out.write(f"    ... and {remaining} more matches")
                break

            self._print_context_block(
                line_num,
                context,
                all_lines,
                printed_lines,
                pattern,
                word_boundary,
                no_color,
            )
            matches_shown += 1

    def _print_context_block(
        self,
        match_line: int,
        context: int,
        all_lines: list[str],
        printed_lines: set[int],
        pattern: str = "",
        word_boundary: bool = False,
        no_color: bool = False,
    ) -> None:
        """Print a single match with its context lines."""
        start = max(1, match_line - context)
        end = min(len(all_lines), match_line + context)

        # Print separator if there's a gap from previous context
        if printed_lines and start > max(printed_lines) + 1:
            self.out.write("    ---")

        for i in range(start, end + 1):
            if i in printed_lines:
                continue
            printed_lines.add(i)

            line_content = all_lines[i - 1].rstrip()
            if len(line_content) > 70:
                line_content = line_content[:70] + "..."

            # Highlight matches on the matching line
            if i == match_line and pattern and not no_color:
                line_content = self._highlight_match(
                    line_content, pattern, word_boundary
                )

            marker = ">>>" if i == match_line else "   "
            self.out.write(f"    {marker} {i}: {line_content}")

    def _highlight_match(self, line: str, pattern: str, word_boundary: bool) -> str:
        """Highlight matched text with ANSI color codes."""
        import re

        highlight = "\033[1;33m"  # Bold yellow
        reset = "\033[0m"

        if word_boundary:
            pattern_re = re.compile(r"\b" + re.escape(pattern) + r"\b", re.IGNORECASE)
        else:
            pattern_re = re.compile(re.escape(pattern), re.IGNORECASE)

        return pattern_re.sub(lambda m: f"{highlight}{m.group()}{reset}", line)

    def _fuzzy_match(
        self, pattern: str, text: str, threshold: float = 0.6
    ) -> tuple[bool, str | None]:
        """Check if pattern fuzzy-matches any word in text.

        Returns:
            Tuple of (matched, matched_word) where matched_word is the
            word that matched if any.
        """
        from difflib import SequenceMatcher

        pattern_lower = pattern.lower()
        # Split on whitespace and common separators
        words = text.lower().replace("-", " ").replace("_", " ").split()

        for word in words:
            # Skip very short words
            if len(word) < 2:
                continue
            ratio = SequenceMatcher(None, pattern_lower, word).ratio()
            if ratio >= threshold:
                return True, word

        return False, None

    def _search_frontmatter_keywords(
        self, content: str, pattern_lower: str, fuzzy: bool, threshold: float
    ) -> tuple[int, str] | None:
        """Search frontmatter keywords for a match."""
        frontmatter = parse_frontmatter(content)
        keywords = frontmatter.get("keywords", []) or []
        aliases = frontmatter.get("aliases", []) or []

        for kw in keywords + aliases:
            if not isinstance(kw, str):
                continue
            if pattern_lower in kw.lower():
                return (0, f"[keyword: {kw}]")
            if fuzzy:
                matched, _ = self._fuzzy_match(pattern_lower, kw, threshold)
                if matched:
                    return (0, f"[keyword: {kw}] (fuzzy)")
        return None

    def _search_file(
        self,
        file_path: Path,
        pattern: str,
        word_boundary: bool = False,
        fuzzy: bool = False,
        threshold: float = 0.6,
    ) -> list[tuple[int, str]]:
        """Search a file for pattern matches."""
        import re

        matches: list[tuple[int, str]] = []
        pattern_lower = pattern.lower()
        pattern_re = (
            re.compile(r"\b" + re.escape(pattern) + r"\b", re.IGNORECASE)
            if word_boundary
            else None
        )

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            # Check frontmatter keywords for .md files
            if file_path.suffix == ".md":
                if kw_match := self._search_frontmatter_keywords(
                    content, pattern_lower, fuzzy, threshold
                ):
                    matches.append(kw_match)
            # Search content lines
            for i, line in enumerate(content.splitlines(keepends=True), 1):
                if self._line_matches(
                    line, pattern_lower, pattern_re, fuzzy, threshold
                ):
                    matches.append((i, line))
        except Exception:
            pass
        return matches

    def _line_matches(
        self,
        line: str,
        pattern_lower: str,
        pattern_re: Any,
        fuzzy: bool,
        threshold: float,
    ) -> bool:
        """Check if a line matches the search pattern."""
        if pattern_re:
            return bool(pattern_re.search(line))
        if fuzzy:
            matched, _ = self._fuzzy_match(pattern_lower, line, threshold)
            return matched
        return pattern_lower in line.lower()


class DocsLicenseTool(Tool):
    """Show the project license."""

    def __init__(
        self, parent: Traceable | None = None, out: OutputWriter | None = None
    ):
        config = ToolConfig(
            name="license",
            aliases=[],
            help_text="Show the project license (Apache 2.0)",
        )
        super().__init__(parent, config)
        self.out = out if out is not None else ConsoleOutput()

    def run(self, **kwargs: Any) -> int:
        """Display the LICENSE file."""
        license_file = get_docs_dir() / "LICENSE"
        if not license_file.exists():
            self.out.write("Error: LICENSE file not found.")
            return 1

        self.out.write(license_file.read_text())
        return 0


class DocsSecurityTool(Tool):
    """Show the security policy."""

    def __init__(
        self, parent: Traceable | None = None, out: OutputWriter | None = None
    ):
        config = ToolConfig(
            name="security",
            aliases=[],
            help_text="Show the security policy and vulnerability reporting",
        )
        super().__init__(parent, config)
        self.out = out if out is not None else ConsoleOutput()

    def run(self, **kwargs: Any) -> int:
        """Display the SECURITY.md file."""
        security_file = get_docs_dir() / "SECURITY.md"
        if not security_file.exists():
            self.out.write("Error: SECURITY.md file not found.")
            return 1

        self.out.write(security_file.read_text())
        return 0


class DocsGenerateTool(Tool):
    """Generate CLI reference documentation from tool definitions."""

    def __init__(
        self, parent: Traceable | None = None, out: OutputWriter | None = None
    ):
        config = ToolConfig(
            name="generate",
            aliases=["gen"],
            help_text="Generate CLI reference documentation from tool definitions",
        )
        super().__init__(parent, config)
        self.out = out if out is not None else ConsoleOutput()

    def add_args(self, parser: Any) -> None:
        """Add arguments for the generate command."""
        parser.add_argument(
            "-o",
            "--output",
            help="Output file path (default: print to stdout)",
        )
        parser.add_argument(
            "--title",
            default="CLI Reference",
            help="Documentation title",
        )
        parser.add_argument(
            "--no-examples",
            action="store_true",
            help="Exclude examples from documentation",
        )
        parser.add_argument(
            "--no-aliases",
            action="store_true",
            help="Exclude command aliases",
        )

    def _write_output(self, markdown: str, output_path: str | None) -> None:
        """Write markdown to file or stdout."""
        if output_path:
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(markdown)
            self.out.write(f"Documentation written to: {output_path}")
        else:
            self.out.write(markdown)

    def run(self, **kwargs: Any) -> int:
        """Generate documentation from the current app's tools."""
        from ...app.docs import DocsGenerator

        generator = DocsGenerator(
            title=getattr(self.args, "title", "CLI Reference"),
            include_examples=not getattr(self.args, "no_examples", False),
            include_aliases=not getattr(self.args, "no_aliases", False),
        )
        try:
            markdown = generator.generate_all(self.app)
        except Exception:
            self.out.write("Error: Could not access application instance.")
            return 1
        self._write_output(markdown, getattr(self.args, "output", None))
        return 0


class DocsTool(Tool):
    """
    Browse appinfra documentation and examples.

    Provides CLI access to all bundled documentation including guides,
    API references, and runnable examples.

    Usage:
        docs              - Show documentation index
        docs list         - List all available docs and examples
        docs show <topic> - Show specific doc or example
        docs find <text>  - Search docs for text
        docs license      - Show the project license
        docs security     - Show the security policy
    """

    def __init__(
        self, parent: Traceable | None = None, out: OutputWriter | None = None
    ):
        config = ToolConfig(
            name="docs",
            aliases=["d"],
            help_text="Browse documentation and examples",
            description=(
                "Access appinfra documentation from the command line. "
                "Use 'docs' for overview, 'docs list' to see all available docs, "
                "'docs show <topic>' to read a guide, 'docs find <pattern>' to search, "
                "'docs license' for license, or 'docs security' for security policy."
            ),
        )
        super().__init__(parent, config)
        self.out = out if out is not None else ConsoleOutput()

        # Add subtools (share output writer for consistency)
        self.add_tool(DocsListTool(self, out=self.out))
        self.add_tool(DocsShowTool(self, out=self.out))
        self.add_tool(DocsFindTool(self, out=self.out))
        self.add_tool(DocsGenerateTool(self, out=self.out))
        self.add_tool(DocsLicenseTool(self, out=self.out))
        self.add_tool(DocsSecurityTool(self, out=self.out))

    def run(self, **kwargs: Any) -> int:
        """Show documentation overview or delegate to subcommand."""
        # Check if a subcommand was provided
        cmd_var = self.group._cmd_var
        cmd = getattr(self.args, cmd_var, None)

        if cmd is None:
            return self._run_overview()

        return self.group.run(**kwargs)

    def _run_overview(self) -> int:
        """Show the main documentation index."""
        index_file = get_docs_dir() / "index.md"
        if not index_file.exists():
            self.out.write("Error: Documentation index not found.")
            self.out.write(f"Expected: {index_file}")
            return 1

        self.out.write(index_file.read_text())
        return 0
