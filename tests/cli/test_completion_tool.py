# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the CompletionTool CLI module."""

from unittest.mock import MagicMock

import pytest

from appinfra.cli.tools.completion_tool import (
    BASH_COMPLETION_TEMPLATE,
    ZSH_COMPLETION_TEMPLATE,
    CompletionTool,
)


@pytest.mark.unit
class TestCompletionTool:
    """Tests for CompletionTool."""

    def test_init(self):
        """Test CompletionTool initialization."""
        tool = CompletionTool()
        assert tool.config.name == "completion"
        assert "shell completion" in tool.config.help_text.lower()

    def test_bash_template_structure(self):
        """Test bash completion template has required elements."""
        assert "_appinfra_completions" in BASH_COMPLETION_TEMPLATE
        assert "complete -F" in BASH_COMPLETION_TEMPLATE
        assert "scaffold" in BASH_COMPLETION_TEMPLATE
        assert "doctor" in BASH_COMPLETION_TEMPLATE
        assert "init" in BASH_COMPLETION_TEMPLATE

    def test_zsh_template_structure(self):
        """Test zsh completion template has required elements."""
        assert "#compdef appinfra" in ZSH_COMPLETION_TEMPLATE
        assert "_appinfra" in ZSH_COMPLETION_TEMPLATE
        assert "scaffold" in ZSH_COMPLETION_TEMPLATE
        assert "doctor" in ZSH_COMPLETION_TEMPLATE
        assert "init" in ZSH_COMPLETION_TEMPLATE

    def test_output_bash_completion(self, capsys):
        """Test bash completion script output."""
        tool = CompletionTool()
        tool._output_completion_script("bash")

        captured = capsys.readouterr()
        assert "_appinfra_completions" in captured.out
        assert "complete -F" in captured.out

    def test_output_zsh_completion(self, capsys):
        """Test zsh completion script output."""
        tool = CompletionTool()
        tool._output_completion_script("zsh")

        captured = capsys.readouterr()
        assert "#compdef appinfra" in captured.out
        assert "_appinfra" in captured.out

    def test_show_install_bash(self, capsys):
        """Test bash installation instructions."""
        tool = CompletionTool()
        tool._show_install_instructions("bash")

        captured = capsys.readouterr()
        assert "Bash completion" in captured.out
        assert ".bashrc" in captured.out
        assert "eval" in captured.out

    def test_show_install_zsh(self, capsys):
        """Test zsh installation instructions."""
        tool = CompletionTool()
        tool._show_install_instructions("zsh")

        captured = capsys.readouterr()
        assert "Zsh completion" in captured.out
        assert ".zshrc" in captured.out
        assert "fpath" in captured.out

    def test_run_bash(self, capsys):
        """Test run with bash shell."""
        tool = CompletionTool()
        mock_args = MagicMock()
        mock_args.shell = "bash"
        mock_args.install = False
        tool._parsed_args = mock_args

        result = tool.run()
        assert result == 0

        captured = capsys.readouterr()
        assert "_appinfra_completions" in captured.out

    def test_run_zsh(self, capsys):
        """Test run with zsh shell."""
        tool = CompletionTool()
        mock_args = MagicMock()
        mock_args.shell = "zsh"
        mock_args.install = False
        tool._parsed_args = mock_args

        result = tool.run()
        assert result == 0

        captured = capsys.readouterr()
        assert "#compdef appinfra" in captured.out

    def test_run_with_install_flag(self, capsys):
        """Test run with --install flag."""
        tool = CompletionTool()
        mock_args = MagicMock()
        mock_args.shell = "bash"
        mock_args.install = True
        tool._parsed_args = mock_args

        result = tool.run()
        assert result == 0

        captured = capsys.readouterr()
        assert "installation" in captured.out.lower()

    def test_bash_template_has_all_commands(self):
        """Test bash template includes all CLI commands."""
        commands = ["scaffold", "cq", "config", "docs", "doctor", "init", "completion"]
        for cmd in commands:
            assert cmd in BASH_COMPLETION_TEMPLATE, f"Missing command: {cmd}"

    def test_zsh_template_has_all_commands(self):
        """Test zsh template includes all CLI commands."""
        commands = ["scaffold", "cq", "config", "docs", "doctor", "init", "completion"]
        for cmd in commands:
            assert cmd in ZSH_COMPLETION_TEMPLATE, f"Missing command: {cmd}"

    def test_bash_template_has_subcommand_completions(self):
        """Test bash template has subcommand completions."""
        # Check for docs subcommands
        assert "list" in BASH_COMPLETION_TEMPLATE
        assert "show" in BASH_COMPLETION_TEMPLATE
        assert "search" in BASH_COMPLETION_TEMPLATE

    def test_zsh_template_has_descriptions(self):
        """Test zsh template has command descriptions."""
        assert "Generate project scaffolding" in ZSH_COMPLETION_TEMPLATE
        assert "Check project health" in ZSH_COMPLETION_TEMPLATE
        assert "Initialize project" in ZSH_COMPLETION_TEMPLATE
