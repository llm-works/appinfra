# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.app.docs.generator module."""

import argparse

from appinfra.app.docs.generator import DocsGenerator


class TestDocsGenerator:
    """Tests for DocsGenerator class."""

    def test_generator_creation(self):
        """Test generator can be created."""
        generator = DocsGenerator()
        assert generator.title == "CLI Reference"
        assert generator.include_examples is True
        assert generator.include_aliases is True

    def test_generator_custom_options(self):
        """Test generator with custom options."""
        generator = DocsGenerator(
            title="My Docs",
            include_examples=False,
            include_aliases=False,
        )
        assert generator.title == "My Docs"
        assert generator.include_examples is False
        assert generator.include_aliases is False

    def test_extract_arguments_basic(self):
        """Test extracting arguments from parser."""
        generator = DocsGenerator()

        parser = argparse.ArgumentParser()
        parser.add_argument("name", help="The name")
        parser.add_argument("--verbose", "-v", action="store_true", help="Verbose mode")
        parser.add_argument("--count", type=int, default=5, help="Count value")

        args = generator._extract_arguments(parser)

        # Should have 3 arguments (excluding help)
        assert len(args) == 3

        # Check positional argument
        name_arg = next(a for a in args if a["name"] == "name")
        assert name_arg["required"] is True
        assert name_arg["help"] == "The name"

        # Check flag argument
        verbose_arg = next(a for a in args if "--verbose" in a["name"])
        assert verbose_arg["type"] == "flag"
        assert verbose_arg["required"] is False

        # Check int argument
        count_arg = next(a for a in args if "--count" in a["name"])
        assert count_arg["type"] == "int"
        assert count_arg["default"] == "5"

    def test_extract_arguments_choices(self):
        """Test extracting arguments with choices."""
        generator = DocsGenerator()

        parser = argparse.ArgumentParser()
        parser.add_argument("--env", choices=["dev", "staging", "prod"])

        args = generator._extract_arguments(parser)

        env_arg = next(a for a in args if "--env" in a["name"])
        assert env_arg["type"] == "choice"
        assert env_arg["choices"] == ["dev", "staging", "prod"]

    def test_extract_arguments_required_optional(self):
        """Test extracting required optional arguments."""
        generator = DocsGenerator()

        parser = argparse.ArgumentParser()
        parser.add_argument("--file", required=True)
        parser.add_argument("--output")

        args = generator._extract_arguments(parser)

        file_arg = next(a for a in args if "--file" in a["name"])
        assert file_arg["required"] is True

        output_arg = next(a for a in args if "--output" in a["name"])
        assert output_arg["required"] is False

    def test_generate_arguments_doc(self):
        """Test generating arguments documentation."""
        generator = DocsGenerator()

        # Create a mock tool with argument parser
        class MockTool:
            _arg_prs = None

            def add_args(self, parser):
                parser.add_argument("--name", required=True, help="The name")
                parser.add_argument("--verbose", action="store_true", help="Verbose")

        tool = MockTool()
        doc = generator._generate_arguments_doc(tool)

        assert "**Arguments:**" in doc
        assert "| Name |" in doc
        assert "`--name`" in doc
        assert "`--verbose`" in doc
        assert "yes" in doc  # required
        assert "flag" in doc

    def test_extract_examples_from_docstring(self):
        """Test extracting examples from docstring."""
        generator = DocsGenerator()

        class MockTool:
            """
            A mock tool.

            Example:
                mytool --name test
                mytool --name test --verbose
            """

            config = None

            def run(self):
                pass

        tool = MockTool()
        examples = generator._extract_examples(tool, "app", "mytool")

        assert "mytool --name test" in examples

    def test_extract_examples_fallback(self):
        """Test example fallback when none in docstring."""
        generator = DocsGenerator()

        class MockTool:
            """A tool without examples."""

            config = None

            def run(self):
                pass

        tool = MockTool()
        examples = generator._extract_examples(tool, "app", "mytool")

        assert "app mytool" in examples

    def test_generate_tool_doc(self):
        """Test generating documentation for a tool."""
        generator = DocsGenerator()

        class MockConfig:
            name = "mock-tool"
            help_text = "Do something useful"
            aliases = ["mt", "mock"]
            description = ""

        class MockTool:
            """A mock tool for testing."""

            config = MockConfig()
            _arg_prs = None
            _group = None

            def add_args(self, parser):
                parser.add_argument("--input", required=True, help="Input file")

            def run(self):
                pass

        tool = MockTool()
        doc = generator.generate_tool_doc(tool, app_name="myapp")

        assert "`myapp mock-tool`" in doc
        assert "Do something useful" in doc
        assert "Aliases:" in doc
        assert "`mt`" in doc
        assert "**Arguments:**" in doc
        assert "`--input`" in doc

    def test_generate_tool_doc_no_aliases(self):
        """Test generating tool doc with aliases disabled."""
        generator = DocsGenerator(include_aliases=False)

        class MockConfig:
            name = "mytool"
            help_text = "Help text"
            aliases = ["alias1"]
            description = ""

        class MockTool:
            config = MockConfig()
            _arg_prs = None
            _group = None

            def add_args(self, parser):
                pass

            def run(self):
                pass

        tool = MockTool()
        doc = generator.generate_tool_doc(tool, app_name="myapp")

        assert "Aliases:" not in doc

    def test_generate_tool_doc_no_examples(self):
        """Test generating tool doc with examples disabled."""
        generator = DocsGenerator(include_examples=False)

        class MockConfig:
            name = "mytool"
            help_text = "Help text"
            aliases = []
            description = ""

        class MockTool:
            """
            A tool.

            Example:
                myapp mytool --flag
            """

            config = MockConfig()
            _arg_prs = None
            _group = None

            def add_args(self, parser):
                pass

            def run(self):
                pass

        tool = MockTool()
        doc = generator.generate_tool_doc(tool, app_name="myapp")

        assert "**Examples:**" not in doc

    def test_get_tool_name(self):
        """Test getting tool name from config or class."""
        generator = DocsGenerator()

        class MockConfig:
            name = "custom-name"

        class MockToolWithConfig:
            config = MockConfig()

        class MockToolWithoutConfig:
            config = None

        tool1 = MockToolWithConfig()
        tool2 = MockToolWithoutConfig()

        assert generator._get_tool_name(tool1) == "custom-name"
        # Without config, returns "unknown"
        assert generator._get_tool_name(tool2) == "unknown"

    def test_get_description(self):
        """Test getting description from docstring."""
        generator = DocsGenerator()

        class MockTool:
            """Short description that should be extracted."""

            config = None

        tool = MockTool()
        desc = generator._get_description(tool)

        # Returns first paragraph (the short description)
        assert "Short description" in desc

    def test_get_description_from_config(self):
        """Test getting description from config."""
        generator = DocsGenerator()

        class MockConfig:
            description = "Config description"

        class MockTool:
            """Docstring description."""

            config = MockConfig()

        tool = MockTool()
        desc = generator._get_description(tool)

        # Config description takes precedence
        assert desc == "Config description"

    def test_generate_all(self):
        """Test generating documentation for all tools in an app."""
        generator = DocsGenerator()

        class MockConfig:
            name = "tool1"
            help_text = "Tool help"
            aliases = []
            description = ""

        class MockTool:
            config = MockConfig()
            _arg_prs = None
            _group = None

            def add_args(self, parser):
                parser.add_argument("--flag", action="store_true")

            def run(self):
                pass

        class MockApp:
            name = "testapp"
            description = "Test application"
            _tools = {"tool1": MockTool()}

        app = MockApp()
        doc = generator.generate_all(app)

        assert "# CLI Reference" in doc
        assert "Test application" in doc
        assert "## Commands" in doc
        assert "Tool help" in doc

    def test_generate_all_custom_title(self):
        """Test generate_all with custom title."""
        generator = DocsGenerator(title="My Custom Docs")

        class MockApp:
            name = "testapp"
            description = None
            _tools = {}

        app = MockApp()
        doc = generator.generate_all(app)

        assert "# My Custom Docs" in doc

    def test_write_header(self):
        """Test _write_header method."""
        from io import StringIO

        generator = DocsGenerator()

        class MockConfig:
            name = "tool"
            help_text = "Help text here"
            aliases = ["a", "b"]
            description = ""

        class MockTool:
            config = MockConfig()

        tool = MockTool()
        output = StringIO()
        generator._write_header(output, tool, "app", "tool", depth=0)

        result = output.getvalue()
        assert "### `app tool`" in result
        assert "Help text here" in result
        assert "**Aliases:**" in result
        assert "`a`" in result
        assert "`b`" in result

    def test_write_examples(self):
        """Test _write_examples method."""
        from io import StringIO

        generator = DocsGenerator()

        class MockTool:
            """
            Tool description.

            Example:
                app tool --flag
            """

            config = None

        tool = MockTool()
        output = StringIO()
        generator._write_examples(output, tool, "app", "tool")

        result = output.getvalue()
        assert "**Examples:**" in result
        assert "```bash" in result
        assert "app tool --flag" in result

    def test_write_subcommands(self):
        """Test _write_subcommands with tool group."""
        from io import StringIO

        generator = DocsGenerator()

        class SubConfig:
            name = "sub"
            help_text = "Subcommand help"
            aliases = []
            description = ""

        class SubTool:
            config = SubConfig()
            _arg_prs = None
            _group = None

            def add_args(self, parser):
                pass

        class MockGroup:
            _tools = {"sub": SubTool()}

        class MockConfig:
            name = "parent"
            help_text = "Parent help"
            aliases = []
            description = ""

        class MockTool:
            config = MockConfig()
            _group = MockGroup()
            _arg_prs = None

            def add_args(self, parser):
                pass

        tool = MockTool()
        output = StringIO()
        generator._write_subcommands(output, tool, "app", "parent", depth=0)

        result = output.getvalue()
        assert "**Subcommands:**" in result
        assert "sub" in result

    def test_generate_to_file(self, tmp_path):
        """Test generating docs to file."""
        generator = DocsGenerator()

        class MockConfig:
            name = "tool1"
            help_text = "Tool help"
            aliases = []
            description = ""

        class MockTool:
            config = MockConfig()
            _arg_prs = None
            _group = None

            def add_args(self, parser):
                pass

        class MockApp:
            name = "testapp"
            description = "Test application"
            _tools = {"tool1": MockTool()}

        app = MockApp()
        output_file = tmp_path / "docs" / "cli.md"
        generator.generate_to_file(app, output_file)

        assert output_file.exists()
        content = output_file.read_text()
        assert "# CLI Reference" in content
        assert "Test application" in content

    def test_get_tools_from_registry(self):
        """Test getting tools from registry attribute (AppBuilder apps)."""
        generator = DocsGenerator()

        class MockConfig:
            name = "tool1"
            help_text = "Help"
            aliases = []
            description = ""

        class MockTool:
            config = MockConfig()
            _arg_prs = None
            _group = None

            def add_args(self, parser):
                pass

        tool_instance = MockTool()

        class MockRegistry:
            def list_tools(self):
                return ["tool1"]

            def get_tool(self, name):
                return tool_instance if name == "tool1" else None

        class MockApp:
            name = "testapp"
            description = None
            registry = MockRegistry()

        app = MockApp()
        tools = generator._get_tools(app)

        assert len(tools) == 1
        assert tools[0] is tool_instance

    def test_get_tools_from_tool_registry(self):
        """Test getting tools from tool_registry attribute (legacy)."""
        generator = DocsGenerator()

        class MockConfig:
            name = "tool1"
            help_text = "Help"
            aliases = []
            description = ""

        class MockTool:
            config = MockConfig()
            _arg_prs = None
            _group = None

            def add_args(self, parser):
                pass

        class MockRegistry:
            def get_all(self):
                return [MockTool()]

        class MockApp:
            name = "testapp"
            description = None
            registry = None  # No registry
            _tools = None
            tool_registry = MockRegistry()

        app = MockApp()
        tools = generator._get_tools(app)

        assert len(tools) == 1

    def test_clean_example_block(self):
        """Test cleaning example block content."""
        generator = DocsGenerator()

        # Test with indented block
        block = "    app tool --flag\n    app tool --other"
        result = generator._clean_example_block(block)

        assert "app tool --flag" in result
        assert "app tool --other" in result

    def test_get_arg_type_with_callable(self):
        """Test _get_arg_type with callable type."""
        generator = DocsGenerator()

        class MockAction:
            option_strings = ["--num"]
            dest = "num"
            nargs = None
            required = False
            choices = None
            default = None
            help = "A number"
            type = int

        action = MockAction()
        result = generator._get_arg_type(action)

        assert result == "int"

    def test_extract_arguments_nargs(self):
        """Test extracting arguments with nargs returns string type."""
        generator = DocsGenerator()

        parser = argparse.ArgumentParser()
        parser.add_argument("files", nargs="+", help="Files to process")
        parser.add_argument("--opt", nargs="*", help="Optional list")

        args = generator._extract_arguments(parser)

        # nargs doesn't affect type string - just returns "string"
        files_arg = next(a for a in args if a["name"] == "files")
        assert files_arg["type"] == "string"

        opt_arg = next(a for a in args if "--opt" in a["name"])
        assert opt_arg["type"] == "string"
