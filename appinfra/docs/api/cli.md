# CLI Framework

Output abstractions and built-in tools for building testable command-line interfaces.

## Output Writers

The CLI module provides output abstraction for testable CLI tools. Instead of writing directly to
stdout, tools use an `OutputWriter` protocol, allowing output to be captured, buffered, or
discarded during testing.

### OutputWriter Protocol

```python
class OutputWriter(Protocol):
    def write(self, text: str = "") -> None:
        """Write text with trailing newline."""
        ...

    def write_raw(self, text: str) -> None:
        """Write text without trailing newline."""
        ...
```

### ConsoleOutput

Default output writer that writes to a stream (stdout by default).

```python
from appinfra.cli import ConsoleOutput

# Default usage (stdout)
out = ConsoleOutput()
out.write("Hello world")

# Custom stream for testing
import io

buffer = io.StringIO()
out = ConsoleOutput(buffer)
out.write("Hello")
assert buffer.getvalue() == "Hello\n"
```

### NullOutput

Output writer that discards all output. Useful for tests where output is not relevant.

```python
from appinfra.cli import NullOutput

out = NullOutput()
out.write("This goes nowhere")  # Silently discarded
```

### BufferedOutput

Output writer that captures output to a list. Useful for testing where you need to verify specific
output lines.

```python
from appinfra.cli import BufferedOutput

out = BufferedOutput()
out.write("Line 1")
out.write("Line 2")

# Access captured output
assert out.lines == ["Line 1", "Line 2"]
assert out.text == "Line 1\nLine 2\n"

# Clear the buffer
out.clear()
```

**Properties and Methods:**

| Member | Type | Description |
|--------|------|-------------|
| `lines` | `list[str]` | All output lines as a list |
| `text` | `str` | All output as a single string with newlines |
| `clear()` | method | Clear the buffer |
| `flush()` | method | Flush any pending raw parts as a line |

## Built-in CLI Tools

The `appinfra` CLI provides several built-in tools for project management.

### scaffold

Generate project scaffolding for appinfra-based applications.

```bash
appinfra scaffold my-project
appinfra scaffold my-api --with-db --with-server
```

**Options:**

| Option | Description |
|--------|-------------|
| `name` | Project name (required) |
| `--path` | Directory to create project in (default: current) |
| `--with-db` | Include database configuration and examples |
| `--with-server` | Include HTTP server configuration and examples |
| `--with-logging-db` | Include database logging handler configuration |
| `--makefile-style` | `standalone` or `framework` (default: standalone) |

### doctor

Check project health and configuration.

```bash
appinfra doctor
appinfra dr  # Alias
```

Performs checks for:
- Python version compatibility
- Required tools (ruff, pytest, mypy)
- Package configuration
- Project structure (tests/ directory)
- Config file syntax

### config

Display resolved configuration values.

```bash
appinfra config
appinfra config --path logging.level
```

### version

Display version information.

```bash
appinfra version
appinfra -v
```

### docs

Open documentation in the browser.

```bash
appinfra docs
```

### etc-path / scripts-path

Display the resolved paths for the `etc/` and `scripts/` directories.

```bash
appinfra etc-path
appinfra scripts-path
```

### completion

Generate shell completion scripts.

```bash
appinfra completion bash
appinfra completion zsh
```

## Testing CLI Tools

Example of testing a CLI tool with BufferedOutput:

```python
from appinfra.cli import BufferedOutput


def test_my_tool_output():
    out = BufferedOutput()

    # Your tool writes to output
    my_tool.run(output=out)

    # Verify output
    assert "Expected message" in out.lines
    assert out.lines[0] == "First line"
```

## See Also

- [Application Framework](app.md) - Tool registration with AppBuilder
- [App Builder](app-builder.md) - Full application configuration
