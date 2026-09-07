# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for cli.cli module."""

import sys
from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestCLI:
    """Test CLI entry point."""

    def test_main_with_help(self, capsys):
        """Test main() with --help flag."""
        from appinfra.cli.cli import main

        with patch.object(sys, "argv", ["cli.py", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_main_with_invalid_args(self):
        """Test main() with invalid arguments."""
        from appinfra.cli.cli import main

        with patch.object(sys, "argv", ["cli.py", "nonexistent_command"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            # Should exit with non-zero for invalid command
            assert exc_info.value.code != 0


@pytest.mark.unit
class TestPathCommands:
    """Test path command early exit handlers."""

    def test_scripts_path(self, capsys):
        """Test scripts-path command returns package scripts directory."""
        from appinfra.cli.cli import main

        with patch.object(sys, "argv", ["cli.py", "scripts-path"]):
            result = main()
            assert result == 0

        captured = capsys.readouterr()
        assert "scripts" in captured.out
        assert "appinfra" in captured.out

    def test_etc_path(self, capsys):
        """Test etc-path command returns package etc directory."""
        from appinfra.cli.cli import main

        with patch.object(sys, "argv", ["cli.py", "etc-path"]):
            result = main()
            assert result == 0

        captured = capsys.readouterr()
        assert "etc" in captured.out
        assert "appinfra" in captured.out

    def test_etc_path_local(self, capsys):
        """Test etc-path --local returns local project etc directory."""
        from appinfra.cli.cli import main

        with patch.object(sys, "argv", ["cli.py", "etc-path", "--local"]):
            result = main()
            assert result == 0

        captured = capsys.readouterr()
        # Should find local etc dir (current project has etc/)
        assert "etc" in captured.out

    def test_etc_path_local_fallback_to_package(self, capsys, tmp_path, monkeypatch):
        """Test etc-path --local falls back to package etc when nothing local exists."""
        from appinfra.cli.cli import main

        # No etc/ above cwd and no XDG overlay: the spec resolves to the packaged base
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-xdg"))
        monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "no-xdg-sys"))

        with patch.object(sys, "argv", ["cli.py", "etc-path", "--local"]):
            result = main()
            assert result == 0

        captured = capsys.readouterr()
        # Should find package etc as fallback
        assert "etc" in captured.out
        assert "appinfra" in captured.out


@pytest.mark.unit
class TestEtcPathTool:
    """Test EtcPathTool directly (for coverage)."""

    def test_run_default(self, capsys):
        """Test EtcPathTool.run() returns package etc."""
        from appinfra.cli.tools.etc_path_tool import EtcPathTool

        tool = EtcPathTool()
        result = tool.run()
        assert result == 0

        captured = capsys.readouterr()
        assert "etc" in captured.out
        assert "appinfra" in captured.out

    def test_run_local(self, capsys):
        """Test EtcPathTool.run(local=True) prints the app's etc_dir."""
        from types import SimpleNamespace

        from appinfra.cli.tools.etc_path_tool import EtcPathTool

        tool = EtcPathTool()
        fake_app = SimpleNamespace(etc_dir="/srv/myapp/etc")
        with patch.object(EtcPathTool, "app", new=property(lambda s: fake_app)):
            result = tool.run(local=True)
        assert result == 0

        captured = capsys.readouterr()
        assert captured.out.strip() == "/srv/myapp/etc"

    def test_run_local_without_etc_dir_errors(self, capsys):
        """Test EtcPathTool.run(local=True) fails when no etc dir resolved."""
        from types import SimpleNamespace

        from appinfra.cli.tools.etc_path_tool import EtcPathTool

        tool = EtcPathTool()
        fake_app = SimpleNamespace(etc_dir=None)
        with patch.object(EtcPathTool, "app", new=property(lambda s: fake_app)):
            result = tool.run(local=True)
        assert result == 1

        captured = capsys.readouterr()
        assert "Error" in captured.err
