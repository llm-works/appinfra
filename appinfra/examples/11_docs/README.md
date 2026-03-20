# Documentation Generation

Auto-generate CLI documentation from tool definitions using DocsGenerator.

## Examples

### docs_generation.py
Demonstrates generating markdown documentation from tool configurations.

**What you'll learn:**
- Using DocsGenerator for CLI documentation
- Extracting docs from tool definitions and argument parsers
- Configuring documentation output (examples, aliases, title)
- Writing documentation to files

**Run:**
```bash
# Print documentation to stdout
~/.venv/bin/python examples/11_docs/docs_generation.py generate

# Write to file
~/.venv/bin/python examples/11_docs/docs_generation.py generate -o cli.md

# With custom title
~/.venv/bin/python examples/11_docs/docs_generation.py generate --title "MyApp Commands"

# See documented tools in action
~/.venv/bin/python examples/11_docs/docs_generation.py deploy --help
~/.venv/bin/python examples/11_docs/docs_generation.py status --help
```

**Key concepts:**
- `DocsGenerator` - Documentation generator class
- `generate_all()` - Generate full documentation
- `generate_to_file()` - Write documentation to file
- Tool docstrings become command descriptions
- Argument definitions become parameter documentation

---

## Usage

### Basic Generation

```python
from pathlib import Path

from appinfra.app.docs import DocsGenerator

generator = DocsGenerator(
    title="CLI Reference",
    include_examples=True,
    include_aliases=True,
)

# Generate markdown string
markdown = generator.generate_all(app)
print(markdown)

# Or write directly to file
generator.generate_to_file(app, Path("docs/cli.md"))
```

### Configuration Options

```python
generator = DocsGenerator(
    title="My Commands",       # Documentation title
    include_examples=True,     # Include usage examples from docstrings
    include_aliases=True,      # Include command aliases
)
```

## How It Works

DocsGenerator extracts documentation from:

1. **Tool docstrings** - Become command descriptions
2. **ToolConfig** - Name, aliases, help text
3. **Argument parsers** - Parameter names, types, defaults, help
4. **Docstring examples** - Usage examples in docstrings

### Example Tool Definition

```python
class DeployTool(Tool):
    """
    Deploy application to target environment.

    Handles the full deployment lifecycle including validation,
    building, and rollout with configurable strategies.

    Example:
        myapp deploy --env prod --version v1.2.3
        myapp deploy --env staging --dry-run
    """

    def add_args(self, parser):
        parser.add_argument(
            "--env", "-e",
            required=True,
            choices=["dev", "staging", "prod"],
            help="Target environment",
        )
```

### Generated Output

```markdown
## deploy

Deploy application to target environment.

Handles the full deployment lifecycle including validation,
building, and rollout with configurable strategies.

**Aliases:** `d`

### Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `--env`, `-e` | choice | Yes | - | Target environment |

### Examples

    myapp deploy --env prod --version v1.2.3
    myapp deploy --env staging --dry-run
```

## Benefits

- **Single source of truth** - Docs generated from code
- **Always in sync** - No manual documentation drift
- **Consistent format** - Uniform documentation style
- **CI integration** - Generate docs as build step

## Best Practices

1. **Write clear docstrings** - They become your documentation
2. **Include examples** - Use `Example:` sections in docstrings
3. **Use descriptive help text** - Argument help becomes parameter docs
4. **Version control generated docs** - Commit the generated markdown

## Integration with CI

```bash
# Generate docs during build
python myapp.py generate -o docs/cli-reference.md

# Verify docs are up-to-date
python myapp.py generate -o /tmp/cli.md
diff docs/cli-reference.md /tmp/cli.md || exit 1
```

## Related Documentation

- [Application Framework](../../docs/api/app.md) - Tool definitions
- [AppBuilder](../../docs/api/app-builder.md) - Building CLI apps
- [Main README](../README.md) - Full examples index
