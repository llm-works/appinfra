# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Output abstraction for CLI tools.

Provides a testable interface for CLI output, allowing tools to be tested
without capturing stdout.
"""

import sys
from typing import Protocol, TextIO


class OutputWriter(Protocol):
    """Protocol for CLI output writing."""

    def write(self, text: str = "") -> None:
        """Write text with trailing newline."""
        ...

    def write_raw(self, text: str) -> None:
        """Write text without trailing newline."""
        ...


class ConsoleOutput:
    """
    Default output writer that writes to a stream (stdout by default).

    This is the production implementation used by CLI tools.

    Example:
        # Default usage (stdout)
        out = ConsoleOutput()
        out.write("Hello world")

        # Custom stream for testing
        import io
        buffer = io.StringIO()
        out = ConsoleOutput(buffer)
        out.write("Hello")
        assert buffer.getvalue() == "Hello\\n"
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        """
        Initialize with optional output stream.

        Args:
            stream: Output stream (defaults to sys.stdout)
        """
        self._stream = stream if stream is not None else sys.stdout

    def write(self, text: str = "") -> None:
        """Write text with trailing newline."""
        print(text, file=self._stream)

    def write_raw(self, text: str) -> None:
        """Write text without trailing newline."""
        print(text, end="", file=self._stream)

    def flush(self) -> None:
        """Flush the output stream."""
        self._stream.flush()


class NullOutput:
    """
    Output writer that discards all output.

    Useful for tests where output is not relevant.

    Example:
        out = NullOutput()
        out.write("This goes nowhere")
    """

    def write(self, text: str = "") -> None:
        """Discard text."""
        pass

    def write_raw(self, text: str) -> None:
        """Discard text."""
        pass

    def flush(self) -> None:
        """No-op flush."""
        pass


class BufferedOutput:
    """
    Output writer that captures output to a list.

    Useful for testing where you need to verify specific output lines.

    Example:
        out = BufferedOutput()
        out.write("Line 1")
        out.write("Line 2")
        assert out.lines == ["Line 1", "Line 2"]
        assert out.text == "Line 1\\nLine 2\\n"
    """

    def __init__(self) -> None:
        """Initialize empty buffer."""
        self._lines: list[str] = []
        self._raw_parts: list[str] = []

    def write(self, text: str = "") -> None:
        """Write text with trailing newline."""
        # Flush any pending raw parts first
        if self._raw_parts:
            prefix = "".join(self._raw_parts)
            self._raw_parts.clear()
            self._lines.append(prefix + text)
        else:
            self._lines.append(text)

    def write_raw(self, text: str) -> None:
        """Buffer text without newline (will be prefixed to next write)."""
        self._raw_parts.append(text)

    def flush(self) -> None:
        """Flush any pending raw parts as a line."""
        if self._raw_parts:
            self._lines.append("".join(self._raw_parts))
            self._raw_parts.clear()

    @property
    def lines(self) -> list[str]:
        """Get all output lines."""
        return self._lines.copy()

    @property
    def text(self) -> str:
        """Get all output as a single string with newlines."""
        self.flush()
        return "\n".join(self._lines) + ("\n" if self._lines else "")

    def clear(self) -> None:
        """Clear the buffer."""
        self._lines.clear()
        self._raw_parts.clear()
