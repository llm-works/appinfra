"""
E2E tests for with_main_tool() workflow.

Tests the complete workflow for single-tool apps where the main tool
runs without requiring a subcommand.

Example:
    ./proxy.py --port 8080        # Main tool runs automatically
    ./proxy.py run --port 8080    # Explicit subcommand still works
"""

import sys
from unittest.mock import patch

import pytest

from appinfra.app.builder import AppBuilder
from appinfra.app.tools import Tool, ToolConfig


class ProxyTool(Tool):
    """Test tool simulating a proxy server."""

    def __init__(self, parent=None):
        super().__init__(
            parent,
            ToolConfig(name="run", aliases=["r"], help_text="Run the proxy server"),
        )
        self.captured_port = None
        self.captured_host = None
        self.run_called = False

    def add_args(self, parser):
        parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
        parser.add_argument("--host", default="localhost", help="Host to bind to")

    def run(self, **kwargs):
        self.run_called = True
        self.captured_port = self.args.port
        self.captured_host = self.args.host
        return 0


@pytest.mark.e2e
class TestMainToolWorkflow:
    """E2E tests for with_main_tool() feature."""

    def test_main_tool_runs_without_subcommand(self):
        """Test that main tool runs when no subcommand is specified."""
        tool = ProxyTool()
        app = (
            AppBuilder("proxy")
            .without_standard_args()
            .tools.with_tool(tool)
            .done()
            .with_main_tool("run")
            .build()
        )

        # Invoke without subcommand - just tool args
        with patch.object(sys, "argv", ["proxy", "--port", "9000"]):
            app.setup()
            result = app.run()

        assert tool.run_called
        assert tool.captured_port == 9000
        assert result == 0

    def test_main_tool_with_explicit_subcommand_still_works(self):
        """Test that explicit subcommand still works with main tool set."""
        tool = ProxyTool()
        app = (
            AppBuilder("proxy")
            .without_standard_args()
            .tools.with_tool(tool)
            .done()
            .with_main_tool("run")
            .build()
        )

        # Invoke with explicit subcommand
        with patch.object(sys, "argv", ["proxy", "run", "--port", "7000"]):
            app.setup()
            result = app.run()

        assert tool.run_called
        assert tool.captured_port == 7000
        assert result == 0

    def test_main_tool_uses_default_args_when_none_provided(self):
        """Test that main tool uses default arg values when none specified."""
        tool = ProxyTool()
        app = (
            AppBuilder("proxy")
            .without_standard_args()
            .tools.with_tool(tool)
            .done()
            .with_main_tool("run")
            .build()
        )

        # Invoke with no args at all
        with patch.object(sys, "argv", ["proxy"]):
            app.setup()
            result = app.run()

        assert tool.run_called
        assert tool.captured_port == 8080  # default
        assert tool.captured_host == "localhost"  # default
        assert result == 0

    def test_main_tool_with_multiple_tools(self):
        """Test main tool works correctly when multiple tools are registered."""

        class OtherTool(Tool):
            def __init__(self, parent=None):
                super().__init__(
                    parent,
                    ToolConfig(name="other", help_text="Other tool"),
                )
                self.run_called = False

            def run(self, **kwargs):
                self.run_called = True
                return 0

        main_tool = ProxyTool()
        other_tool = OtherTool()

        app = (
            AppBuilder("proxy")
            .without_standard_args()
            .tools.with_tool(main_tool)
            .with_tool(other_tool)
            .done()
            .with_main_tool("run")
            .build()
        )

        # Without subcommand - main tool runs
        with patch.object(sys, "argv", ["proxy", "--port", "5000"]):
            app.setup()
            app.run()

        assert main_tool.run_called
        assert main_tool.captured_port == 5000
        assert not other_tool.run_called

    def test_explicit_other_tool_runs_instead_of_main(self):
        """Test that explicitly specifying another tool runs that tool."""

        class OtherTool(Tool):
            def __init__(self, parent=None):
                super().__init__(
                    parent,
                    ToolConfig(name="other", help_text="Other tool"),
                )
                self.run_called = False

            def run(self, **kwargs):
                self.run_called = True
                return 42

        main_tool = ProxyTool()
        other_tool = OtherTool()

        app = (
            AppBuilder("proxy")
            .without_standard_args()
            .tools.with_tool(main_tool)
            .with_tool(other_tool)
            .done()
            .with_main_tool("run")
            .build()
        )

        # Explicitly run "other" tool
        with patch.object(sys, "argv", ["proxy", "other"]):
            app.setup()
            result = app.run()

        assert other_tool.run_called
        assert not main_tool.run_called
        assert result == 42

    def test_main_tool_with_tool_object(self):
        """Test with_main_tool() accepts Tool object, not just string."""
        tool = ProxyTool()
        app = (
            AppBuilder("proxy")
            .without_standard_args()
            .tools.with_tool(tool)
            .done()
            .with_main_tool(tool)  # Pass Tool object
            .build()
        )

        with patch.object(sys, "argv", ["proxy", "--port", "3000"]):
            app.setup()
            result = app.run()

        assert tool.run_called
        assert tool.captured_port == 3000
        assert result == 0

    def test_main_tool_with_standard_args(self):
        """Test main tool works alongside standard args like --log-level."""
        tool = ProxyTool()
        app = (
            AppBuilder("proxy")
            .tools.with_tool(tool)
            .done()
            .with_main_tool("run")
            .build()
        )

        # Mix standard args with tool args
        with patch.object(
            sys, "argv", ["proxy", "--log-level", "debug", "--port", "4000"]
        ):
            app.setup()
            result = app.run()

        assert tool.run_called
        assert tool.captured_port == 4000
        assert app.config.logging.level == "debug"
        assert result == 0


@pytest.mark.e2e
class TestMainToolPositionalArgsConflict:
    """
    E2E tests for positional argument conflict resolution.

    When main tool and subcommands both have positional arguments,
    subcommand positional args should not be consumed by the main tool's
    positional args at the root parser level.
    """

    def test_subcommand_positional_not_consumed_by_main_tool(self):
        """Test subcommand's positional arg is not consumed by main tool."""

        class ProcessTool(Tool):
            """Main tool with positional argument."""

            def __init__(self, parent=None):
                super().__init__(
                    parent,
                    ToolConfig(name="process", aliases=["p"], help_text="Process data"),
                )
                self.captured_target = None
                self.run_called = False

            def add_args(self, parser):
                parser.add_argument("target", nargs="?", help="Target to process")
                parser.add_argument("--verbose", action="store_true")

            def run(self, **kwargs):
                self.run_called = True
                self.captured_target = getattr(self.args, "target", None)
                return 0

        class AnalyzeTool(Tool):
            """Subcommand with its own positional argument."""

            def __init__(self, parent=None):
                super().__init__(
                    parent,
                    ToolConfig(name="analyze", aliases=["a"], help_text="Analyze data"),
                )
                self.captured_filename = None
                self.run_called = False

            def add_args(self, parser):
                parser.add_argument("filename", help="File to analyze")
                parser.add_argument("--deep", action="store_true")

            def run(self, **kwargs):
                self.run_called = True
                self.captured_filename = self.args.filename
                return 0

        process_tool = ProcessTool()
        analyze_tool = AnalyzeTool()

        app = (
            AppBuilder("cli")
            .without_standard_args()
            .tools.with_tool(process_tool)
            .with_tool(analyze_tool)
            .done()
            .with_main_tool("process")
            .build()
        )

        # Key test: "analyze" should be recognized as subcommand,
        # "/tmp/data.csv" should go to AnalyzeTool's filename arg
        with patch.object(sys, "argv", ["cli", "analyze", "/tmp/data.csv"]):
            app.setup()
            result = app.run()

        assert analyze_tool.run_called
        assert analyze_tool.captured_filename == "/tmp/data.csv"
        assert not process_tool.run_called
        assert result == 0

    def test_main_tool_optional_args_still_hoisted(self):
        """Test main tool's optional args work at root level."""

        class ProcessTool(Tool):
            def __init__(self, parent=None):
                super().__init__(
                    parent,
                    ToolConfig(name="process", help_text="Process data"),
                )
                self.captured_verbose = None
                self.run_called = False

            def add_args(self, parser):
                parser.add_argument("target", nargs="?", help="Target to process")
                parser.add_argument("--verbose", action="store_true")

            def run(self, **kwargs):
                self.run_called = True
                self.captured_verbose = self.args.verbose
                return 0

        tool = ProcessTool()
        app = (
            AppBuilder("cli")
            .without_standard_args()
            .tools.with_tool(tool)
            .done()
            .with_main_tool("process")
            .build()
        )

        # Optional args from main tool should work without subcommand
        with patch.object(sys, "argv", ["cli", "--verbose"]):
            app.setup()
            result = app.run()

        assert tool.run_called
        assert tool.captured_verbose is True
        assert result == 0

    def test_subcommand_with_multiple_positional_args(self):
        """Test subcommand with multiple positional args works correctly."""

        class MainTool(Tool):
            def __init__(self, parent=None):
                super().__init__(parent, ToolConfig(name="main", help_text="Main tool"))
                self.run_called = False

            def add_args(self, parser):
                parser.add_argument("input", nargs="?", help="Input")

            def run(self, **kwargs):
                self.run_called = True
                return 0

        class CopyTool(Tool):
            def __init__(self, parent=None):
                super().__init__(
                    parent, ToolConfig(name="copy", help_text="Copy files")
                )
                self.captured_src = None
                self.captured_dst = None
                self.run_called = False

            def add_args(self, parser):
                parser.add_argument("src", help="Source path")
                parser.add_argument("dst", help="Destination path")

            def run(self, **kwargs):
                self.run_called = True
                self.captured_src = self.args.src
                self.captured_dst = self.args.dst
                return 0

        main_tool = MainTool()
        copy_tool = CopyTool()

        app = (
            AppBuilder("cli")
            .without_standard_args()
            .tools.with_tool(main_tool)
            .with_tool(copy_tool)
            .done()
            .with_main_tool("main")
            .build()
        )

        # Both positional args should go to copy tool
        with patch.object(sys, "argv", ["cli", "copy", "/src/file", "/dst/file"]):
            app.setup()
            result = app.run()

        assert copy_tool.run_called
        assert copy_tool.captured_src == "/src/file"
        assert copy_tool.captured_dst == "/dst/file"
        assert not main_tool.run_called
        assert result == 0


@pytest.mark.e2e
class TestMainToolWithDecorators:
    """E2E tests for with_main_tool() with @app.tool decorator post-build."""

    def test_decorated_tool_as_main_tool(self):
        """Test that @app.tool decorator works with with_main_tool() post-build.

        Regression test for bug where DecoratedTool.set_args() didn't accept
        skip_positional parameter, causing TypeError when used as main tool.
        """
        app = AppBuilder("proxy").without_standard_args().with_main_tool("run").build()

        @app.tool(name="run", help="Run the proxy")
        @app.argument("--port", type=int, default=8080, help="Port")
        def run_proxy(self):
            self.captured_port = self.args.port
            return 0

        with patch.object(sys, "argv", ["proxy", "--port", "9000"]):
            app.setup()
            result = app.run()

        assert result == 0
        # Verify the tool ran and captured the port
        tool = app.registry.get_tool("run")
        assert tool.captured_port == 9000

    def test_decorated_main_tool_with_other_subcommands(self):
        """Test decorated main tool works with other subcommand tools."""
        app = AppBuilder("cli").without_standard_args().with_main_tool("serve").build()

        @app.tool(name="serve", help="Start server")
        @app.argument("--port", type=int, default=8000, help="Port")
        def serve(self):
            self.serve_called = True
            return 0

        @app.tool(name="check", help="Health check")
        def check(self):
            self.check_called = True
            return 42

        # Without subcommand - main tool runs
        with patch.object(sys, "argv", ["cli", "--port", "5000"]):
            app.setup()
            result = app.run()

        assert result == 0
        assert app.registry.get_tool("serve").serve_called

        # Reset: need a fresh app since setup() was already called
        app2 = AppBuilder("cli").without_standard_args().with_main_tool("serve").build()

        @app2.tool(name="serve", help="Start server")
        @app2.argument("--port", type=int, default=8000, help="Port")
        def serve2(self):
            self.serve_called = True
            return 0

        @app2.tool(name="check", help="Health check")
        def check2(self):
            self.check_called = True
            return 42

        with patch.object(sys, "argv", ["cli", "check"]):
            app2.setup()
            result2 = app2.run()

        assert result2 == 42
        assert app2.registry.get_tool("check").check_called
