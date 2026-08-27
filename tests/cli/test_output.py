# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for CLI output abstraction."""

import io

import pytest

from appinfra.cli.output import BufferedOutput, ConsoleOutput, NullOutput


@pytest.mark.unit
class TestConsoleOutput:
    """Tests for ConsoleOutput class."""

    def test_write_to_stdout_by_default(self, capsys):
        """Test that ConsoleOutput writes to stdout by default."""
        out = ConsoleOutput()
        out.write("Hello")
        out.write("World")

        captured = capsys.readouterr()
        assert captured.out == "Hello\nWorld\n"

    def test_write_empty_string(self, capsys):
        """Test writing empty string produces newline."""
        out = ConsoleOutput()
        out.write()

        captured = capsys.readouterr()
        assert captured.out == "\n"

    def test_write_to_custom_stream(self):
        """Test writing to a custom stream."""
        buffer = io.StringIO()
        out = ConsoleOutput(buffer)
        out.write("Test line")

        assert buffer.getvalue() == "Test line\n"

    def test_write_raw_no_newline(self):
        """Test write_raw does not add newline."""
        buffer = io.StringIO()
        out = ConsoleOutput(buffer)
        out.write_raw("Hello ")
        out.write_raw("World")

        assert buffer.getvalue() == "Hello World"

    def test_flush(self):
        """Test flush calls underlying stream flush."""
        buffer = io.StringIO()
        out = ConsoleOutput(buffer)
        out.write("Test")
        out.flush()

        # Just verify no error occurs
        assert buffer.getvalue() == "Test\n"


@pytest.mark.unit
class TestNullOutput:
    """Tests for NullOutput class."""

    def test_write_discards_output(self):
        """Test that NullOutput discards all output."""
        out = NullOutput()
        out.write("This should be discarded")
        out.write_raw("This too")
        out.flush()
        # No assertions needed - just verify no errors

    def test_null_output_is_silent(self, capsys):
        """Test NullOutput produces no actual output."""
        out = NullOutput()
        out.write("Hello")
        out.write("World")

        captured = capsys.readouterr()
        assert captured.out == ""


@pytest.mark.unit
class TestBufferedOutput:
    """Tests for BufferedOutput class."""

    def test_write_captures_lines(self):
        """Test that write captures output lines."""
        out = BufferedOutput()
        out.write("Line 1")
        out.write("Line 2")
        out.write("Line 3")

        assert out.lines == ["Line 1", "Line 2", "Line 3"]

    def test_text_property(self):
        """Test text property returns all lines with newlines."""
        out = BufferedOutput()
        out.write("Line 1")
        out.write("Line 2")

        assert out.text == "Line 1\nLine 2\n"

    def test_text_empty_buffer(self):
        """Test text property with empty buffer."""
        out = BufferedOutput()
        assert out.text == ""

    def test_write_empty_string(self):
        """Test writing empty string."""
        out = BufferedOutput()
        out.write()
        out.write("After empty")

        assert out.lines == ["", "After empty"]

    def test_write_raw_combined_with_write(self):
        """Test write_raw content is prefixed to next write."""
        out = BufferedOutput()
        out.write_raw("Start: ")
        out.write("End")

        assert out.lines == ["Start: End"]

    def test_multiple_write_raw(self):
        """Test multiple write_raw calls accumulate."""
        out = BufferedOutput()
        out.write_raw("A")
        out.write_raw("B")
        out.write_raw("C")
        out.write("D")

        assert out.lines == ["ABCD"]

    def test_flush_with_pending_raw(self):
        """Test flush converts pending raw parts to line."""
        out = BufferedOutput()
        out.write_raw("Pending")
        out.flush()

        assert out.lines == ["Pending"]

    def test_clear(self):
        """Test clear empties the buffer."""
        out = BufferedOutput()
        out.write("Line 1")
        out.write_raw("Pending")
        out.clear()

        assert out.lines == []
        assert out.text == ""

    def test_lines_returns_copy(self):
        """Test lines property returns a copy."""
        out = BufferedOutput()
        out.write("Line 1")

        lines = out.lines
        lines.append("Modified")

        assert out.lines == ["Line 1"]


@pytest.mark.unit
class TestOutputWriterProtocol:
    """Tests verifying protocol compliance."""

    def test_console_output_implements_protocol(self):
        """Test ConsoleOutput satisfies OutputWriter protocol."""
        out = ConsoleOutput(io.StringIO())
        # Protocol check - should have write and write_raw
        assert hasattr(out, "write")
        assert hasattr(out, "write_raw")
        assert callable(out.write)
        assert callable(out.write_raw)

    def test_null_output_implements_protocol(self):
        """Test NullOutput satisfies OutputWriter protocol."""
        out = NullOutput()
        assert hasattr(out, "write")
        assert hasattr(out, "write_raw")

    def test_buffered_output_implements_protocol(self):
        """Test BufferedOutput satisfies OutputWriter protocol."""
        out = BufferedOutput()
        assert hasattr(out, "write")
        assert hasattr(out, "write_raw")
