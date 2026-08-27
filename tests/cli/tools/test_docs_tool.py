# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for cli/tools/docs_tool.py.

Tests key functionality including:
- Helper functions for path resolution and file finding
- DocsListTool for listing documentation
- DocsShowTool for displaying specific docs
- DocsFindTool for searching documentation
- DocsLicenseTool for displaying license
- DocsSecurityTool for displaying security policy
- DocsTool main tool and overview
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from appinfra.cli.tools.docs_tool import (
    DocsFindTool,
    DocsLicenseTool,
    DocsListTool,
    DocsSecurityTool,
    DocsShowTool,
    DocsTool,
    extract_title,
    find_doc,
    find_example,
    get_docs_dir,
    get_examples_dir,
    get_package_root,
    parse_frontmatter,
)

# =============================================================================
# Test Helper Functions
# =============================================================================


@pytest.mark.unit
class TestGetPackageRoot:
    """Test get_package_root helper function."""

    def test_returns_path(self):
        """Test returns a Path object."""
        result = get_package_root()
        assert isinstance(result, Path)

    def test_returns_appinfra_parent(self):
        """Test returns parent of appinfra package."""
        result = get_package_root()
        # Should be the appinfra package directory
        assert result.name == "appinfra"


@pytest.mark.unit
class TestGetDocsDir:
    """Test get_docs_dir helper function."""

    def test_returns_docs_path(self):
        """Test returns path to docs directory."""
        result = get_docs_dir()
        assert isinstance(result, Path)
        assert result.name == "docs"

    def test_docs_dir_under_package_root(self):
        """Test docs dir is under package root."""
        docs_dir = get_docs_dir()
        pkg_root = get_package_root()
        assert docs_dir.parent == pkg_root


@pytest.mark.unit
class TestGetExamplesDir:
    """Test get_examples_dir helper function."""

    def test_returns_examples_path(self):
        """Test returns path to examples directory."""
        result = get_examples_dir()
        assert isinstance(result, Path)
        assert result.name == "examples"


@pytest.mark.unit
class TestFindDoc:
    """Test find_doc helper function."""

    def test_returns_none_for_nonexistent_dir(self):
        """Test returns None when docs dir doesn't exist."""
        result = find_doc(Path("/nonexistent"), "topic")
        assert result is None

    def test_finds_direct_match(self):
        """Test finds direct .md file match."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            (docs_dir / "logging.md").write_text("# Logging")

            result = find_doc(docs_dir, "logging")
            assert result == docs_dir / "logging.md"

    def test_finds_in_guides_subdir(self):
        """Test finds file in guides subdirectory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            (docs_dir / "guides").mkdir()
            (docs_dir / "guides" / "setup.md").write_text("# Setup Guide")

            result = find_doc(docs_dir, "setup")
            assert result == docs_dir / "guides" / "setup.md"

    def test_finds_in_api_subdir(self):
        """Test finds file in api subdirectory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            (docs_dir / "api").mkdir()
            (docs_dir / "api" / "database.md").write_text("# Database API")

            result = find_doc(docs_dir, "database")
            assert result == docs_dir / "api" / "database.md"

    def test_fuzzy_match_ignores_case_and_separators(self):
        """Test fuzzy matching normalizes names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            (docs_dir / "logging-builder.md").write_text("# Logging Builder")

            # Should match with different casing and separators
            result = find_doc(docs_dir, "LoggingBuilder")
            assert result == docs_dir / "logging-builder.md"

    def test_returns_none_when_not_found(self):
        """Test returns None when topic not found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            (docs_dir / "other.md").write_text("# Other")

            result = find_doc(docs_dir, "nonexistent")
            assert result is None


@pytest.mark.unit
class TestFindExample:
    """Test find_example helper function."""

    def test_returns_none_for_nonexistent_dir(self):
        """Test returns None when examples dir doesn't exist."""
        result = find_example(Path("/nonexistent"), "example")
        assert result is None

    def test_finds_direct_match(self):
        """Test finds exact directory match."""
        with tempfile.TemporaryDirectory() as tmpdir:
            examples_dir = Path(tmpdir)
            (examples_dir / "myexample").mkdir()

            result = find_example(examples_dir, "myexample")
            assert result == examples_dir / "myexample"

    def test_finds_by_prefix(self):
        """Test finds directory by prefix match."""
        with tempfile.TemporaryDirectory() as tmpdir:
            examples_dir = Path(tmpdir)
            (examples_dir / "02_app_framework").mkdir()

            result = find_example(examples_dir, "02")
            assert result == examples_dir / "02_app_framework"

    def test_prefix_match_returns_first_sorted(self):
        """Test prefix match returns first directory in sorted order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            examples_dir = Path(tmpdir)
            (examples_dir / "02_second").mkdir()
            (examples_dir / "02_first").mkdir()

            result = find_example(examples_dir, "02")
            # Should return 02_first (alphabetically first)
            assert result == examples_dir / "02_first"

    def test_fuzzy_match_on_suffix(self):
        """Test fuzzy match on name part after number prefix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            examples_dir = Path(tmpdir)
            (examples_dir / "03_app_framework").mkdir()

            result = find_example(examples_dir, "appframework")
            assert result == examples_dir / "03_app_framework"

    def test_finds_files(self):
        """Test finds files (not just directories)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            examples_dir = Path(tmpdir)
            example_file = examples_dir / "example.py"
            example_file.write_text("print('hello')")

            result = find_example(examples_dir, "example")
            assert result == example_file

            result = find_example(examples_dir, "example.py")
            assert result == example_file

    def test_finds_file_in_subdir(self):
        """Test finds file within example subdirectory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            examples_dir = Path(tmpdir)
            subdir = examples_dir / "02_app_framework"
            subdir.mkdir()
            example_file = subdir / "app_with_tool.py"
            example_file.write_text("print('hello')")

            # Find by filename alone
            result = find_example(examples_dir, "app_with_tool")
            assert result == example_file

            result = find_example(examples_dir, "app_with_tool.py")
            assert result == example_file

    def test_finds_file_with_path(self):
        """Test finds file using dir/file path syntax."""
        with tempfile.TemporaryDirectory() as tmpdir:
            examples_dir = Path(tmpdir)
            subdir = examples_dir / "02_app_framework"
            subdir.mkdir()
            example_file = subdir / "app_with_tool.py"
            example_file.write_text("print('hello')")

            # Full path
            result = find_example(examples_dir, "02_app_framework/app_with_tool.py")
            assert result == example_file

            # Partial dir name
            result = find_example(examples_dir, "02/app_with_tool.py")
            assert result == example_file

            # Partial dir without .py
            result = find_example(examples_dir, "02/app_with_tool")
            assert result == example_file

    def test_returns_none_when_not_found(self):
        """Test returns None when example not found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            examples_dir = Path(tmpdir)
            (examples_dir / "other").mkdir()

            result = find_example(examples_dir, "nonexistent")
            assert result is None


@pytest.mark.unit
class TestParseFrontmatter:
    """Test parse_frontmatter helper function."""

    def test_returns_empty_dict_for_no_frontmatter(self):
        """Test returns empty dict when no frontmatter present."""
        content = "# Title\n\nSome content"
        result = parse_frontmatter(content)
        assert result == {}

    def test_returns_empty_dict_for_empty_frontmatter(self):
        """Test returns empty dict for empty frontmatter."""
        content = "---\n---\n# Title"
        result = parse_frontmatter(content)
        assert result == {}

    def test_parses_simple_frontmatter(self):
        """Test parses simple key-value frontmatter."""
        content = "---\ntitle: My Doc\nauthor: Test\n---\n# Content"
        result = parse_frontmatter(content)
        assert result["title"] == "My Doc"
        assert result["author"] == "Test"

    def test_parses_keywords_list(self):
        """Test parses keywords as list."""
        content = "---\nkeywords: [foo, bar, baz]\n---\n# Content"
        result = parse_frontmatter(content)
        assert result["keywords"] == ["foo", "bar", "baz"]

    def test_parses_keywords_yaml_list(self):
        """Test parses keywords in YAML list format."""
        content = "---\nkeywords:\n  - foo\n  - bar\n---\n# Content"
        result = parse_frontmatter(content)
        assert result["keywords"] == ["foo", "bar"]

    def test_parses_aliases(self):
        """Test parses aliases list."""
        content = "---\naliases: [alias1, alias2]\n---\n# Content"
        result = parse_frontmatter(content)
        assert result["aliases"] == ["alias1", "alias2"]

    def test_handles_invalid_yaml(self):
        """Test handles invalid YAML gracefully."""
        content = "---\ninvalid: yaml: content:\n---\n# Content"
        result = parse_frontmatter(content)
        # Should return empty dict or partial result, not raise
        assert isinstance(result, dict)

    def test_handles_unclosed_frontmatter(self):
        """Test handles unclosed frontmatter delimiter."""
        content = "---\ntitle: Test\n# Content without closing"
        result = parse_frontmatter(content)
        assert result == {}


@pytest.mark.unit
class TestExtractTitle:
    """Test extract_title helper function."""

    def test_extracts_h1_heading(self):
        """Test extracts first H1 heading from markdown."""
        with tempfile.TemporaryDirectory() as tmpdir:
            md_file = Path(tmpdir) / "doc.md"
            md_file.write_text("# My Title\n\nSome content")

            result = extract_title(md_file)
            assert result == "My Title"

    def test_returns_empty_for_no_heading(self):
        """Test returns empty string when no H1 heading found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            md_file = Path(tmpdir) / "doc.md"
            md_file.write_text("Some content without heading")

            result = extract_title(md_file)
            assert result == ""

    def test_returns_empty_for_missing_file(self):
        """Test returns empty string for nonexistent file."""
        result = extract_title(Path("/nonexistent/doc.md"))
        assert result == ""

    def test_skips_h2_headings(self):
        """Test ignores H2 and lower headings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            md_file = Path(tmpdir) / "doc.md"
            md_file.write_text("## Not H1\n\n# Real Title")

            result = extract_title(md_file)
            assert result == "Real Title"


# =============================================================================
# Test DocsListTool
# =============================================================================


@pytest.mark.unit
class TestDocsListTool:
    """Test DocsListTool class."""

    def test_initialization(self):
        """Test tool initializes with correct config."""
        tool = DocsListTool()
        assert tool.name == "list"
        assert "ls" in tool.config.aliases

    def test_run_returns_zero(self):
        """Test run returns 0 on success."""
        tool = DocsListTool()
        tool._parsed_args = Mock()

        with patch("appinfra.cli.tools.docs_tool.get_docs_dir") as mock_docs:
            mock_docs.return_value = Path("/nonexistent")
            result = tool.run()

        assert result == 0

    def test_lists_guides_section(self, capsys):
        """Test lists guides section when it exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            (docs_dir / "guides").mkdir()
            (docs_dir / "guides" / "setup.md").write_text("# Setup Guide")

            tool = DocsListTool()
            tool._parsed_args = Mock()

            with patch(
                "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_examples_dir",
                    return_value=Path("/nonexistent"),
                ):
                    tool.run()

            captured = capsys.readouterr()
            assert "GUIDES:" in captured.out
            assert "setup" in captured.out


# =============================================================================
# Test DocsShowTool
# =============================================================================


@pytest.mark.unit
class TestDocsShowTool:
    """Test DocsShowTool class."""

    def test_initialization(self):
        """Test tool initializes with correct config."""
        tool = DocsShowTool()
        assert tool.name == "show"
        assert "s" in tool.config.aliases

    def test_add_args(self):
        """Test adds topic argument."""
        tool = DocsShowTool()
        parser = Mock()

        tool.add_args(parser)

        parser.add_argument.assert_called_once()
        call_args = parser.add_argument.call_args
        assert call_args[0][0] == "topic"

    def test_run_without_topic_returns_error(self, capsys):
        """Test returns 1 when no topic provided."""
        tool = DocsShowTool()
        tool._parsed_args = Mock(spec=[])

        result = tool.run()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error" in captured.out

    def test_run_shows_doc_file(self, capsys):
        """Test displays documentation file content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            (docs_dir / "logging.md").write_text("# Logging\n\nContent here")

            tool = DocsShowTool()
            args = Mock()
            args.topic = "logging"
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_examples_dir",
                    return_value=Path("/nonexistent"),
                ):
                    result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            assert "# Logging" in captured.out
            assert "Content here" in captured.out

    def test_run_shows_example(self, capsys):
        """Test displays example README and file list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            examples_dir = Path(tmpdir)
            example_dir = examples_dir / "02_example"
            example_dir.mkdir()
            (example_dir / "README.md").write_text("# Example\n\nDescription")
            (example_dir / "main.py").write_text("print('hello')")

            tool = DocsShowTool()
            args = Mock()
            args.topic = "02"
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_docs_dir",
                return_value=Path("/nonexistent"),
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_examples_dir",
                    return_value=examples_dir,
                ):
                    result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            assert "# Example" in captured.out
            assert "main.py" in captured.out

    def test_run_not_found_returns_error(self, capsys):
        """Test returns 1 when topic not found."""
        tool = DocsShowTool()
        args = Mock()
        args.topic = "nonexistent"
        tool._parsed_args = args

        with patch(
            "appinfra.cli.tools.docs_tool.get_docs_dir",
            return_value=Path("/nonexistent"),
        ):
            with patch(
                "appinfra.cli.tools.docs_tool.get_examples_dir",
                return_value=Path("/nonexistent"),
            ):
                result = tool.run()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.out

    def test_run_with_md_suffix(self, capsys):
        """Test topic with .md suffix works (suffix is stripped)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            (docs_dir / "logging.md").write_text("# Logging\n\nContent here")

            tool = DocsShowTool()
            args = Mock()
            args.topic = "logging.md"  # With .md suffix
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_examples_dir",
                    return_value=Path("/nonexistent"),
                ):
                    result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            assert "# Logging" in captured.out

    def test_run_shows_example_file(self, capsys):
        """Test displays example file contents (not just directory)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            examples_dir = Path(tmpdir)
            subdir = examples_dir / "02_app_framework"
            subdir.mkdir()
            example_file = subdir / "app_with_tool.py"
            example_file.write_text("print('hello from example')")

            tool = DocsShowTool()
            args = Mock()
            args.topic = "app_with_tool"
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_docs_dir",
                return_value=Path("/nonexistent"),
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_examples_dir",
                    return_value=examples_dir,
                ):
                    result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            assert "print('hello from example')" in captured.out


# =============================================================================
# Test DocsFindTool
# =============================================================================


@pytest.mark.unit
class TestDocsFindTool:
    """Test DocsFindTool class."""

    def test_initialization(self):
        """Test tool initializes with correct config."""
        tool = DocsFindTool()
        assert tool.name == "find"
        assert "f" in tool.config.aliases
        assert "search" in tool.config.aliases

    def test_add_args(self):
        """Test adds pattern and context arguments."""
        tool = DocsFindTool()
        parser = Mock()

        tool.add_args(parser)

        calls = [c[0][0] for c in parser.add_argument.call_args_list]
        assert "pattern" in calls
        assert "-c" in calls or "--context" in [
            c[1].get("dest") for c in parser.add_argument.call_args_list
        ]

    def test_run_without_pattern_returns_error(self, capsys):
        """Test returns 1 when no pattern provided."""
        tool = DocsFindTool()
        tool._parsed_args = Mock(spec=[])

        result = tool.run()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error" in captured.out

    def test_run_finds_matches(self, capsys):
        """Test finds and displays pattern matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            (docs_dir / "logging.md").write_text("# Logging\n\nUse LoggingBuilder here")

            tool = DocsFindTool()
            args = Mock()
            args.pattern = "LoggingBuilder"
            args.context = 0
            args.word = False
            args.max_matches = 10
            args.docs_only = False
            args.examples_only = False
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_package_root",
                return_value=Path(tmpdir),
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
                ):
                    with patch(
                        "appinfra.cli.tools.docs_tool.get_examples_dir",
                        return_value=Path("/nonexistent"),
                    ):
                        result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            assert "LoggingBuilder" in captured.out

    def test_run_no_matches(self, capsys):
        """Test handles no matches gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            (docs_dir / "logging.md").write_text("# Logging")

            tool = DocsFindTool()
            args = Mock()
            args.pattern = "nonexistent_pattern_xyz"
            args.context = 0
            args.word = False
            args.max_matches = 10
            args.docs_only = False
            args.examples_only = False
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_examples_dir",
                    return_value=Path("/nonexistent"),
                ):
                    result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            assert "No matches found" in captured.out

    def test_case_insensitive_search(self, capsys):
        """Test search is case-insensitive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            (docs_dir / "doc.md").write_text("UPPERCASE content")

            tool = DocsFindTool()
            args = Mock()
            args.pattern = "uppercase"
            args.context = 0
            args.word = False
            args.max_matches = 10
            args.docs_only = False
            args.examples_only = False
            args.no_color = True
            args.fuzzy = False
            args.threshold = 0.6
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_package_root",
                return_value=Path(tmpdir),
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
                ):
                    with patch(
                        "appinfra.cli.tools.docs_tool.get_examples_dir",
                        return_value=Path("/nonexistent"),
                    ):
                        result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            assert "UPPERCASE" in captured.out

    def test_word_boundary_matching(self, capsys):
        """Test -w/--word flag matches whole words only."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            # File contains both "log" and "catalog" - only "log" should match with -w
            (docs_dir / "doc.md").write_text("Use log for logging\nCheck catalog here")

            tool = DocsFindTool()
            args = Mock()
            args.pattern = "log"
            args.context = 0
            args.word = True  # Word boundary matching
            args.max_matches = 10
            args.docs_only = False
            args.examples_only = False
            args.no_color = True
            args.fuzzy = False
            args.threshold = 0.6
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_package_root",
                return_value=Path(tmpdir),
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
                ):
                    with patch(
                        "appinfra.cli.tools.docs_tool.get_examples_dir",
                        return_value=Path("/nonexistent"),
                    ):
                        result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            # Should match "log" but not "catalog"
            assert "Use log" in captured.out
            assert "catalog" not in captured.out

    def test_context_lines(self, capsys):
        """Test -c/--context flag shows surrounding lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            (docs_dir / "doc.md").write_text(
                "Line 1\nLine 2\nMatch here\nLine 4\nLine 5"
            )

            tool = DocsFindTool()
            args = Mock()
            args.pattern = "Match"
            args.context = 1  # Show 1 line before and after
            args.word = False
            args.max_matches = 10
            args.docs_only = False
            args.examples_only = False
            args.no_color = True
            args.fuzzy = False
            args.threshold = 0.6
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_package_root",
                return_value=Path(tmpdir),
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
                ):
                    with patch(
                        "appinfra.cli.tools.docs_tool.get_examples_dir",
                        return_value=Path("/nonexistent"),
                    ):
                        result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            # Should show context lines
            assert "Line 2" in captured.out
            assert "Match here" in captured.out
            assert "Line 4" in captured.out

    def test_max_matches_limit(self, capsys):
        """Test -n/--max-matches limits output per file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            # Create file with many matches
            content = "\n".join([f"match line {i}" for i in range(20)])
            (docs_dir / "doc.md").write_text(content)

            tool = DocsFindTool()
            args = Mock()
            args.pattern = "match"
            args.context = 0
            args.word = False
            args.max_matches = 3  # Only show 3 matches
            args.docs_only = False
            args.examples_only = False
            args.no_color = True
            args.fuzzy = False
            args.threshold = 0.6
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_package_root",
                return_value=Path(tmpdir),
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
                ):
                    with patch(
                        "appinfra.cli.tools.docs_tool.get_examples_dir",
                        return_value=Path("/nonexistent"),
                    ):
                        result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            # Should show "and X more matches"
            assert "more matches" in captured.out

    def test_docs_only_filter(self, capsys):
        """Test --docs-only flag searches only documentation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            examples_dir = Path(tmpdir) / "examples"
            examples_dir.mkdir()

            (docs_dir / "doc.md").write_text("findme in docs")
            (examples_dir / "example.py").write_text("findme in examples")

            tool = DocsFindTool()
            args = Mock()
            args.pattern = "findme"
            args.context = 0
            args.word = False
            args.max_matches = 10
            args.docs_only = True  # Only search docs
            args.examples_only = False
            args.no_color = True
            args.fuzzy = False
            args.threshold = 0.6
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_package_root",
                return_value=Path(tmpdir),
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
                ):
                    with patch(
                        "appinfra.cli.tools.docs_tool.get_examples_dir",
                        return_value=examples_dir,
                    ):
                        result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            assert "docs" in captured.out
            assert "example.py" not in captured.out

    def test_examples_only_filter(self, capsys):
        """Test --examples-only flag searches only examples."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            examples_dir = Path(tmpdir) / "examples"
            examples_dir.mkdir()

            (docs_dir / "doc.md").write_text("findme in docs")
            (examples_dir / "example.py").write_text("findme in examples")

            tool = DocsFindTool()
            args = Mock()
            args.pattern = "findme"
            args.context = 0
            args.word = False
            args.max_matches = 10
            args.docs_only = False
            args.examples_only = True  # Only search examples
            args.no_color = True
            args.fuzzy = False
            args.threshold = 0.6
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_package_root",
                return_value=Path(tmpdir),
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
                ):
                    with patch(
                        "appinfra.cli.tools.docs_tool.get_examples_dir",
                        return_value=examples_dir,
                    ):
                        result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            assert "example.py" in captured.out
            assert "doc.md" not in captured.out

    def test_highlighting_adds_ansi_codes(self, capsys):
        """Test that matching text is highlighted with ANSI codes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            (docs_dir / "doc.md").write_text("Find the pattern here")

            tool = DocsFindTool()
            args = Mock()
            args.pattern = "pattern"
            args.context = 0
            args.word = False
            args.max_matches = 10
            args.docs_only = False
            args.examples_only = False
            args.no_color = False  # Highlighting enabled
            args.fuzzy = False
            args.threshold = 0.6
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_package_root",
                return_value=Path(tmpdir),
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
                ):
                    with patch(
                        "appinfra.cli.tools.docs_tool.get_examples_dir",
                        return_value=Path("/nonexistent"),
                    ):
                        result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            # Check for ANSI escape codes (bold yellow)
            assert "\033[1;33m" in captured.out
            assert "\033[0m" in captured.out

    def test_no_color_disables_highlighting(self, capsys):
        """Test that --no-color flag disables highlighting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            (docs_dir / "doc.md").write_text("Find the pattern here")

            tool = DocsFindTool()
            args = Mock()
            args.pattern = "pattern"
            args.context = 0
            args.word = False
            args.max_matches = 10
            args.docs_only = False
            args.examples_only = False
            args.no_color = True  # Highlighting disabled
            args.fuzzy = False
            args.threshold = 0.6
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_package_root",
                return_value=Path(tmpdir),
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
                ):
                    with patch(
                        "appinfra.cli.tools.docs_tool.get_examples_dir",
                        return_value=Path("/nonexistent"),
                    ):
                        result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            # Should NOT have ANSI escape codes
            assert "\033[1;33m" not in captured.out
            assert "pattern" in captured.out

    def test_finds_by_frontmatter_keyword(self, capsys):
        """Test finds file by frontmatter keyword even if content doesn't match."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            # File with keyword in frontmatter but not in content
            (docs_dir / "doc.md").write_text(
                "---\nkeywords: [check-funcs, funcsize, cq cf]\n---\n"
                "# Function Size Checker\n\nContent about function sizes"
            )

            tool = DocsFindTool()
            args = Mock()
            args.pattern = "check-funcs"  # Only in keywords, not content
            args.context = 0
            args.word = False
            args.max_matches = 10
            args.docs_only = False
            args.examples_only = False
            args.no_color = True
            args.fuzzy = False
            args.threshold = 0.6
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_package_root",
                return_value=Path(tmpdir),
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
                ):
                    with patch(
                        "appinfra.cli.tools.docs_tool.get_examples_dir",
                        return_value=Path("/nonexistent"),
                    ):
                        result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            assert "doc.md" in captured.out
            assert "[keyword: check-funcs]" in captured.out

    def test_finds_by_frontmatter_alias(self, capsys):
        """Test finds file by frontmatter alias."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            (docs_dir / "doc.md").write_text(
                "---\naliases: [function-checker, line-limit]\n---\n"
                "# Function Size Checker\n\nContent here"
            )

            tool = DocsFindTool()
            args = Mock()
            args.pattern = "line-limit"  # Only in aliases
            args.context = 0
            args.word = False
            args.max_matches = 10
            args.docs_only = False
            args.examples_only = False
            args.no_color = True
            args.fuzzy = False
            args.threshold = 0.6
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_package_root",
                return_value=Path(tmpdir),
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
                ):
                    with patch(
                        "appinfra.cli.tools.docs_tool.get_examples_dir",
                        return_value=Path("/nonexistent"),
                    ):
                        result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            assert "doc.md" in captured.out
            assert "[keyword: line-limit]" in captured.out

    def test_keyword_search_case_insensitive(self, capsys):
        """Test keyword search is case insensitive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            (docs_dir / "doc.md").write_text(
                "---\nkeywords: [CheckFuncs, FUNCSIZE]\n---\n# Content"
            )

            tool = DocsFindTool()
            args = Mock()
            args.pattern = "checkfuncs"  # lowercase
            args.context = 0
            args.word = False
            args.max_matches = 10
            args.docs_only = False
            args.examples_only = False
            args.no_color = True
            args.fuzzy = False
            args.threshold = 0.6
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_package_root",
                return_value=Path(tmpdir),
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
                ):
                    with patch(
                        "appinfra.cli.tools.docs_tool.get_examples_dir",
                        return_value=Path("/nonexistent"),
                    ):
                        result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            assert "doc.md" in captured.out

    def test_fuzzy_matching_finds_typos(self, capsys):
        """Test fuzzy matching finds words with typos."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            (docs_dir / "doc.md").write_text("# Guide\n\nConfigure the logging here")

            tool = DocsFindTool()
            args = Mock()
            args.pattern = "loging"  # typo: missing 'g'
            args.context = 0
            args.word = False
            args.max_matches = 10
            args.docs_only = False
            args.examples_only = False
            args.no_color = True
            args.fuzzy = True
            args.threshold = 0.7
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_package_root",
                return_value=Path(tmpdir),
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
                ):
                    with patch(
                        "appinfra.cli.tools.docs_tool.get_examples_dir",
                        return_value=Path("/nonexistent"),
                    ):
                        result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            assert "doc.md" in captured.out
            assert "logging" in captured.out

    def test_fuzzy_matching_finds_partial_words(self, capsys):
        """Test fuzzy matching finds partial word matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            (docs_dir / "doc.md").write_text(
                "---\nkeywords: [configuration]\n---\n# Content"
            )

            tool = DocsFindTool()
            args = Mock()
            args.pattern = "config"  # partial match
            args.context = 0
            args.word = False
            args.max_matches = 10
            args.docs_only = False
            args.examples_only = False
            args.no_color = True
            args.fuzzy = True
            args.threshold = 0.6
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_package_root",
                return_value=Path(tmpdir),
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
                ):
                    with patch(
                        "appinfra.cli.tools.docs_tool.get_examples_dir",
                        return_value=Path("/nonexistent"),
                    ):
                        result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            # Should find via keyword fuzzy match
            assert "doc.md" in captured.out

    def test_fuzzy_disabled_by_default(self, capsys):
        """Test fuzzy matching is disabled by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            (docs_dir / "doc.md").write_text("# Guide\n\nConfigure the logging here")

            tool = DocsFindTool()
            args = Mock()
            args.pattern = "loging"  # typo
            args.context = 0
            args.word = False
            args.max_matches = 10
            args.docs_only = False
            args.examples_only = False
            args.no_color = True
            args.fuzzy = False  # Disabled
            args.threshold = 0.6
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_package_root",
                return_value=Path(tmpdir),
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
                ):
                    with patch(
                        "appinfra.cli.tools.docs_tool.get_examples_dir",
                        return_value=Path("/nonexistent"),
                    ):
                        result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            # Should NOT find with exact matching
            assert "No matches found" in captured.out

    def test_fuzzy_threshold_affects_results(self, capsys):
        """Test that threshold affects fuzzy match sensitivity."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()
            (docs_dir / "doc.md").write_text("# Guide\n\nConfigure the logging here")

            tool = DocsFindTool()
            args = Mock()
            args.pattern = "log"  # very short pattern
            args.context = 0
            args.word = False
            args.max_matches = 10
            args.docs_only = False
            args.examples_only = False
            args.no_color = True
            args.fuzzy = True
            args.threshold = 0.95  # Very high threshold
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_package_root",
                return_value=Path(tmpdir),
            ):
                with patch(
                    "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
                ):
                    with patch(
                        "appinfra.cli.tools.docs_tool.get_examples_dir",
                        return_value=Path("/nonexistent"),
                    ):
                        result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            # With 0.95 threshold, "log" shouldn't match "logging" (ratio ~0.67)
            assert "No matches found" in captured.out


# =============================================================================
# Test DocsLicenseTool
# =============================================================================


@pytest.mark.unit
class TestDocsLicenseTool:
    """Test DocsLicenseTool class."""

    def test_initialization(self):
        """Test tool initializes with correct config."""
        tool = DocsLicenseTool()
        assert tool.name == "license"
        assert tool.config.aliases == []

    def test_run_displays_license(self, capsys):
        """Test displays LICENSE file content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            (docs_dir / "LICENSE").write_text("Apache License 2.0\n\nLicense text here")

            tool = DocsLicenseTool()
            tool._parsed_args = Mock()

            with patch(
                "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
            ):
                result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            assert "Apache License" in captured.out

    def test_run_missing_license_returns_error(self, capsys):
        """Test returns 1 when LICENSE not found."""
        tool = DocsLicenseTool()
        tool._parsed_args = Mock()

        with patch(
            "appinfra.cli.tools.docs_tool.get_docs_dir",
            return_value=Path("/nonexistent"),
        ):
            result = tool.run()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.out


# =============================================================================
# Test DocsSecurityTool
# =============================================================================


@pytest.mark.unit
class TestDocsSecurityTool:
    """Test DocsSecurityTool class."""

    def test_initialization(self):
        """Test tool initializes with correct config."""
        tool = DocsSecurityTool()
        assert tool.name == "security"
        assert tool.config.aliases == []

    def test_run_displays_security(self, capsys):
        """Test displays SECURITY.md file content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            (docs_dir / "SECURITY.md").write_text("# Security Policy\n\nReport issues")

            tool = DocsSecurityTool()
            tool._parsed_args = Mock()

            with patch(
                "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
            ):
                result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            assert "Security Policy" in captured.out

    def test_run_missing_security_returns_error(self, capsys):
        """Test returns 1 when SECURITY.md not found."""
        tool = DocsSecurityTool()
        tool._parsed_args = Mock()

        with patch(
            "appinfra.cli.tools.docs_tool.get_docs_dir",
            return_value=Path("/nonexistent"),
        ):
            result = tool.run()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.out


# =============================================================================
# Test DocsTool (Main Tool)
# =============================================================================


@pytest.mark.unit
class TestDocsTool:
    """Test DocsTool main class."""

    def test_initialization(self):
        """Test tool initializes with correct config."""
        tool = DocsTool()
        assert tool.name == "docs"
        assert "d" in tool.config.aliases

    def test_has_subtools(self):
        """Test tool has all expected subtools."""
        tool = DocsTool()
        subtool_names = list(tool.group._tools.keys())

        assert "list" in subtool_names
        assert "show" in subtool_names
        assert "find" in subtool_names
        assert "license" in subtool_names
        assert "security" in subtool_names

    def test_run_overview_shows_index(self, capsys):
        """Test run without subcommand shows index.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            (docs_dir / "index.md").write_text("# Infra Framework\n\nOverview content")

            tool = DocsTool()
            args = Mock()
            # Simulate no subcommand - set the cmd_var to None
            setattr(args, tool.group._cmd_var, None)
            tool._parsed_args = args

            with patch(
                "appinfra.cli.tools.docs_tool.get_docs_dir", return_value=docs_dir
            ):
                result = tool.run()

            assert result == 0
            captured = capsys.readouterr()
            assert "Infra Framework" in captured.out

    def test_run_overview_missing_index_returns_error(self, capsys):
        """Test returns 1 when index.md not found."""
        tool = DocsTool()
        args = Mock()
        # Simulate no subcommand
        setattr(args, tool.group._cmd_var, None)
        tool._parsed_args = args

        with patch(
            "appinfra.cli.tools.docs_tool.get_docs_dir",
            return_value=Path("/nonexistent"),
        ):
            result = tool.run()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.out


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestDocsToolIntegration:
    """Integration tests using actual docs directory."""

    def test_list_actual_docs(self):
        """Test listing actual documentation."""
        tool = DocsListTool()
        tool._parsed_args = Mock()

        result = tool.run()

        # Should succeed with real docs
        assert result == 0

    def test_show_actual_index(self, capsys):
        """Test showing actual index.md."""
        tool = DocsTool()
        args = Mock()
        # Simulate no subcommand
        setattr(args, tool.group._cmd_var, None)
        tool._parsed_args = args

        result = tool.run()

        assert result == 0
        captured = capsys.readouterr()
        # Should contain actual index content
        assert "Infra" in captured.out or "appinfra" in captured.out.lower()

    def test_find_in_actual_docs(self, capsys):
        """Test searching actual documentation."""
        tool = DocsFindTool()
        args = Mock()
        args.pattern = "logging"
        args.context = 0
        args.word = False
        args.max_matches = 10
        args.docs_only = False
        args.examples_only = False
        tool._parsed_args = args

        result = tool.run()

        assert result == 0
        captured = capsys.readouterr()
        # Should find logging-related content
        assert "logging" in captured.out.lower() or "Found" in captured.out
