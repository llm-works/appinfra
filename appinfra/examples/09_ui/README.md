# UI Module Examples

This directory contains examples demonstrating the `appinfra.ui` module features:

- **Rich Terminal Output** - Beautiful tables, panels, and progress bars
- **Spinners and Progress** - Multiple progress bars, various spinner styles
- **Interactive Prompts** - Confirmations, selections, and password input

## Examples

| File | Description |
|------|-------------|
| `rich_output.py` | Tables, panels, styled text, and progress bars |
| `spinners_and_progress.py` | Multiple progress bars, spinner styles, live tables |
| `interactive_prompts.py` | Confirmations, selections, text input |
| `deploy_tool.py` | Complete tool combining all features |

## Running Examples

```bash
# Rich output demo
python examples/09_ui/rich_output.py

# Spinners and multiple progress bars
python examples/09_ui/spinners_and_progress.py

# Interactive prompts (requires TTY)
python examples/09_ui/interactive_prompts.py

# Full deploy tool example
python examples/09_ui/deploy_tool.py --help
python examples/09_ui/deploy_tool.py deploy --env staging
```

## Spinner Styles

The `console.status()` method supports various spinner styles:

```python
from appinfra.ui import console

# Default spinner (dots)
with console.status("Processing..."):
    do_work()

# Custom spinner style
with console.status("Deploying...", spinner="arc"):
    deploy()

# Available spinners include:
# dots, dots2, line, arc, moon, earth, bounce, aesthetic, and many more
```

## Dependencies

These examples require the `ui` optional dependencies:

```bash
pip install appinfra[ui]
# or
pip install rich questionary
```

The examples gracefully degrade when dependencies are not installed.
