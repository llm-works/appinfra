# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.ui.fallback module."""

import pytest

from appinfra.ui.fallback import Panel, Progress, Table

pytestmark = pytest.mark.unit


class TestTable:
    """Tests for fallback Table class."""

    def test_table_creation(self):
        """Test table can be created."""
        table = Table(title="Test Table")
        assert table.title == "Test Table"
        assert table.columns == []
        assert table.rows == []

    def test_table_add_column(self):
        """Test adding columns to table."""
        table = Table()
        table.add_column("Name")
        table.add_column("Value")

        assert table.columns == ["Name", "Value"]

    def test_table_add_row(self):
        """Test adding rows to table."""
        table = Table()
        table.add_column("Name")
        table.add_column("Value")
        table.add_row("test", "123")

        assert table.rows == [["test", "123"]]

    def test_table_str_output(self):
        """Test table string output."""
        table = Table(title="Results")
        table.add_column("Name")
        table.add_column("Status")
        table.add_row("server-1", "OK")
        table.add_row("server-2", "Failed")

        output = str(table)

        assert "Results" in output
        assert "Name" in output
        assert "Status" in output
        assert "server-1" in output
        assert "OK" in output
        assert "server-2" in output
        assert "Failed" in output

    def test_table_strips_markup(self):
        """Test table strips rich markup from values."""
        table = Table()
        table.add_column("Status")
        table.add_row("[green]OK[/green]")

        output = str(table)

        assert "OK" in output
        assert "[green]" not in output

    def test_empty_table(self):
        """Test empty table outputs nothing."""
        table = Table()
        assert str(table) == ""


class TestPanel:
    """Tests for fallback Panel class."""

    def test_panel_creation(self):
        """Test panel can be created."""
        panel = Panel("Content", title="Title")
        assert panel.content == "Content"
        assert panel.title == "Title"

    def test_panel_str_output(self):
        """Test panel string output."""
        panel = Panel("Important message", title="Notice")
        output = str(panel)

        assert "Notice" in output
        assert "Important message" in output
        assert "+" in output  # Border characters
        assert "-" in output
        assert "|" in output

    def test_panel_without_title(self):
        """Test panel without title."""
        panel = Panel("Content")
        output = str(panel)

        assert "Content" in output
        assert "+" in output

    def test_panel_strips_markup(self):
        """Test panel strips rich markup."""
        panel = Panel("[bold]Important[/bold]")
        output = str(panel)

        assert "Important" in output
        assert "[bold]" not in output


class TestProgress:
    """Tests for fallback Progress class."""

    def test_progress_context_manager(self):
        """Test progress as context manager."""
        with Progress() as progress:
            task_id = progress.add_task("Processing", total=100)
            assert task_id == 0
            assert task_id in progress.tasks

    def test_progress_add_task(self):
        """Test adding tasks to progress."""
        progress = Progress()
        task1 = progress.add_task("Task 1", total=100)
        task2 = progress.add_task("Task 2", total=50)

        assert task1 == 0
        assert task2 == 1
        assert progress.tasks[task1]["description"] == "Task 1"
        assert progress.tasks[task2]["total"] == 50

    def test_progress_update(self):
        """Test updating progress."""
        progress = Progress()
        task_id = progress.add_task("Task", total=100)

        progress.update(task_id, advance=10)
        assert progress.tasks[task_id]["completed"] == 10

        progress.update(task_id, advance=20)
        assert progress.tasks[task_id]["completed"] == 30

        progress.update(task_id, completed=50)
        assert progress.tasks[task_id]["completed"] == 50

    def test_progress_remove_task(self):
        """Test removing tasks."""
        progress = Progress()
        task_id = progress.add_task("Task", total=100)

        progress.remove_task(task_id)
        assert task_id not in progress.tasks

    def test_progress_update_nonexistent_task(self):
        """Test updating nonexistent task does nothing."""
        progress = Progress()
        progress.update(999, advance=10)  # Should not raise

    def test_progress_exit_prints_completion(self, capsys):
        """Test __exit__ prints completion for completed tasks."""
        progress = Progress()
        task_id = progress.add_task("Processing", total=100)
        progress.update(task_id, completed=100)  # Mark complete

        progress.__exit__(None, None, None)

        captured = capsys.readouterr()
        assert "Processing - Complete" in captured.out

    def test_progress_exit_no_print_for_incomplete(self, capsys):
        """Test __exit__ doesn't print for incomplete tasks."""
        progress = Progress()
        task_id = progress.add_task("Processing", total=100)
        progress.update(task_id, completed=50)  # Only 50% complete

        progress.__exit__(None, None, None)

        captured = capsys.readouterr()
        assert "Processing - Complete" not in captured.out
