# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Fallback implementations when rich is not installed.

Provides basic plain-text alternatives for Table, Panel, and Progress
so code using the UI module doesn't break when rich is unavailable.
"""

from typing import Any, Self


class Table:
    """
    Plain-text table fallback.

    Provides a basic table implementation that outputs plain text
    when rich is not available.

    Example:
        table = Table(title="Results")
        table.add_column("Name")
        table.add_column("Status")
        table.add_row("server-1", "OK")
        print(table)  # or console.print(table)
    """

    def __init__(
        self,
        *args: Any,
        title: str = "",
        **kwargs: Any,
    ):
        """Initialize the table."""
        self.title = title
        self.columns: list[str] = []
        self.rows: list[list[str]] = []

    def add_column(
        self,
        header: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Add a column to the table."""
        self.columns.append(header)

    def add_row(self, *values: Any, **kwargs: Any) -> None:
        """Add a row to the table."""
        self.rows.append([self._strip_markup(str(v)) for v in values])

    def _calculate_widths(self) -> list[int]:
        """Calculate column widths based on content."""
        widths = [len(col) for col in self.columns]
        for row in self.rows:
            for i, cell in enumerate(row):
                if i < len(widths):
                    widths[i] = max(widths[i], len(cell))
        return widths

    def _format_row(self, row: list[str], widths: list[int]) -> str:
        """Format a single row with padding."""
        padded = [
            cell.ljust(widths[i] if i < len(widths) else len(cell))
            for i, cell in enumerate(row)
        ]
        return " | ".join(padded)

    def __str__(self) -> str:
        """Render the table as plain text."""
        if not self.columns:
            return ""
        widths = self._calculate_widths()
        lines = []
        if self.title:
            lines.extend([self.title, ""])
        header = " | ".join(col.ljust(widths[i]) for i, col in enumerate(self.columns))
        lines.extend([header, "-" * len(header)])
        lines.extend(self._format_row(row, widths) for row in self.rows)
        return "\n".join(lines)

    @staticmethod
    def _strip_markup(text: str) -> str:
        """Remove rich markup tags from text."""
        import re

        return re.sub(r"\[/?[^\]]+\]", "", text)


class Panel:
    """
    Plain-text panel fallback.

    Provides a basic box/panel implementation that outputs plain text
    when rich is not available.

    Example:
        panel = Panel("Important message", title="Notice")
        print(panel)
    """

    def __init__(
        self,
        content: Any,
        *args: Any,
        title: str = "",
        **kwargs: Any,
    ):
        """Initialize the panel."""
        self.content = str(content)
        self.title = title

    def __str__(self) -> str:
        """Render the panel as plain text."""
        content = self._strip_markup(self.content)
        lines = content.split("\n")
        width = max(len(line) for line in lines) if lines else 0

        if self.title:
            width = max(width, len(self.title) + 4)

        result = []

        # Top border
        if self.title:
            title_str = f" {self.title} "
            padding = width - len(title_str) + 2
            left = padding // 2
            right = padding - left
            result.append("+" + "-" * left + title_str + "-" * right + "+")
        else:
            result.append("+" + "-" * (width + 2) + "+")

        # Content
        for line in lines:
            stripped = self._strip_markup(line)
            result.append(f"| {stripped.ljust(width)} |")

        # Bottom border
        result.append("+" + "-" * (width + 2) + "+")

        return "\n".join(result)

    @staticmethod
    def _strip_markup(text: str) -> str:
        """Remove rich markup tags from text."""
        import re

        return re.sub(r"\[/?[^\]]+\]", "", text)


class Progress:
    """
    Plain-text progress fallback.

    Provides a basic progress indicator when rich is not available.
    Uses simple print statements instead of animated progress bars.

    Example:
        with Progress() as progress:
            task = progress.add_task("Processing...", total=100)
            for i in range(100):
                progress.update(task, advance=1)
    """

    def __init__(self, *args: Any, **kwargs: Any):
        """Initialize progress tracker."""
        self.tasks: dict[int, dict[str, Any]] = {}
        self._next_id = 0

    def __enter__(self) -> Self:
        """Enter context."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Exit context."""
        # Print completion for all tasks
        for task in self.tasks.values():
            if task.get("completed", 0) >= task.get("total", 0):
                print(f"{task['description']} - Complete")

    def add_task(
        self,
        description: str,
        total: float = 100,
        **kwargs: Any,
    ) -> int:
        """Add a task to track."""
        task_id = self._next_id
        self._next_id += 1
        self.tasks[task_id] = {
            "description": description,
            "total": total,
            "completed": 0,
        }
        print(f"{description}...")
        return task_id

    def update(
        self,
        task_id: int,
        *,
        advance: float = 0,
        completed: float | None = None,
        **kwargs: Any,
    ) -> None:
        """Update task progress."""
        if task_id not in self.tasks:
            return

        task = self.tasks[task_id]
        if completed is not None:
            task["completed"] = completed
        else:
            task["completed"] += advance

    def remove_task(self, task_id: int) -> None:
        """Remove a task."""
        self.tasks.pop(task_id, None)
