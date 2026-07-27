# UI Module

Rich terminal output with tables, panels, progress bars, and interactive prompts. Gracefully
degrades when Rich is not installed or in non-TTY environments.

## Overview

The `appinfra.ui` module provides:

- **Console output** - Styled text, tables, and panels via Rich
- **Progress tracking** - Spinners and progress bars coordinated with logging
- **Interactive prompts** - Confirmations, selections, and text input
- **Help formatting** - Rich-formatted CLI help

## ProgressLogger

Context manager for displaying spinners or progress bars while coordinating with logging output.
Automatically pauses visual elements when logs are written, then resumes.

### Basic Usage

```python
from appinfra.ui import ProgressLogger

# Spinner mode (unknown duration)
with ProgressLogger(lg, "Processing...") as pl:
    for item in items:
        process(item)
        pl.info(f"Processed {item.name}")  # Pauses spinner, logs, resumes
```

### Progress Bar Mode

When a total is specified, displays a progress bar with elapsed time and ETA:

```
⠋ Downloading... ━━━━━━━━━━━━━━━━━━━━ 50/100 0:00:05 0:00:05
```

```python
# Progress bar mode (known total) - shows elapsed time and ETA
with ProgressLogger(lg, "Downloading...", total=100) as pl:
    for i, chunk in enumerate(chunks):
        download(chunk)
        pl.update(advance=1)
        if i % 10 == 0:
            pl.info(f"Downloaded {i} chunks")
```

### Right-Justified Mode

Use `justify="right"` to anchor the progress bar to the right edge, preventing jumping
when message text has variable length:

```python
# Right-justified: bar stays fixed as message changes
with ProgressLogger(lg, "Syncing...", total=10, justify="right") as pl:
    for pkg in packages:
        pl.update(message=f"Syncing {pkg}...")
```

### Full-Width Mode

Use `expand=True` to make the progress bar fill the terminal width:

```python
# Progress bar expands to fill available width
with ProgressLogger(lg, "Processing...", total=100, expand=True) as pl:
    for item in items:
        pl.update()
```

### Switching Modes

```python
# Start with spinner, switch to progress bar when total is known
with ProgressLogger(lg, "Scanning...") as pl:
    items = scan_directory()  # Spinner while scanning
    pl.set_total(len(items))  # Switch to progress bar
    for item in items:
        process(item)
        pl.update()
```

### API Reference

```python
class ProgressLogger:
    def __init__(
        self,
        lg: Logger,  # appinfra.log.Logger
        message: str = "Working...",
        total: int | None = None,  # None = spinner, int = progress bar
        spinner: str = "dots",     # Spinner style: "dots", "arc", "moon", etc.
        justify: str = "left",     # "left" or "right" (anchors bar to right edge)
        expand: bool = False,      # True = progress bar fills terminal width
        bar_style: str = "bar.complete",  # Bar color: "green", "blue", etc.
    ): ...

    # Logging methods (pause display, log, resume)
    def log(self, msg: str, level: int = logging.INFO, **kwargs) -> None
    def debug(self, msg: str, **kwargs) -> None
    def info(self, msg: str, **kwargs) -> None
    def warning(self, msg: str, **kwargs) -> None
    def error(self, msg: str, **kwargs) -> None

    # Progress control
    def update(
        self,
        message: str | None = None,  # Update display message
        advance: int = 1,            # Advance by N (progress bar)
        completed: int | None = None # Set absolute completion
    ) -> None

    def set_total(self, total: int) -> None  # Switch spinner → progress bar

    # Properties
    @property
    def is_interactive(self) -> bool  # True if showing visual elements
    @property
    def total(self) -> int | None     # Current total (None = spinner mode)
    @property
    def completed(self) -> int        # Current completion count
```

### Behavior

| Environment | Behavior |
|-------------|----------|
| TTY with Rich | Shows animated spinner/progress bar |
| Non-TTY | Logs only, no visual elements |
| `APPINFRA_NON_INTERACTIVE=1` | Logs only, no visual elements |
| Rich not installed | Logs only, no visual elements |

## Console

Styled console output using Rich.

```python
from appinfra.ui import console, Table, Panel

# Styled text
console.print("[green]Success![/green] Operation completed.")

# Tables
table = Table(title="Results")
table.add_column("Name")
table.add_column("Status")
table.add_row("server-1", "[green]OK[/]")
console.print(table)

# Panels
panel = Panel("Important message", title="Notice")
console.print(panel)
```

## Prompts

Interactive prompts for user input. Raises `NonInteractiveError` in non-TTY environments.

```python
from appinfra.ui import confirm, select, text, password, multiselect

# Confirmation
if confirm("Delete files?"):
    delete_files()

# Selection
env = select("Environment:", ["dev", "staging", "prod"])

# Text input
name = text("Enter name:", default="default")

# Password (hidden input)
secret = password("Enter API key:")

# Multi-select
features = multiselect("Enable features:", ["logging", "metrics", "tracing"])
```

### Scrollable Selection

Arrow-key navigable selection with configurable page height. Requires `pip install appinfra[ui]`.

```python
from appinfra.ui import select_scrollable, select_table

# Scrollable list selection
servers = [f"server-{i:03d}" for i in range(50)]
idx = select_scrollable("Select server:", servers, max_height=10)
if idx is not None:
    print(f"Selected: {servers[idx]}")

# Table-style selection with columns
processes = [
    {"pid": "1234", "name": "nginx", "status": "running"},
    {"pid": "1235", "name": "postgres", "status": "running"},
]
selected = select_table(
    "Select process:",
    processes,
    columns=["pid", "name", "status"],
    max_height=5,
)
if selected:
    print(f"Selected: {selected['name']}")
```

**Controls:**
- Arrow keys: Navigate up/down
- Enter: Select item
- Q or ESC: Cancel (returns `None`)

**Parameters:**
- `default_index`: Initially highlighted row, 0-based (default: 0)
- `max_height`: Maximum visible rows before scrolling (default: 10)
- `column_spacing`: Spaces between columns (default: 2)
- `highlight_color`: Background color for selected row (default: `#005fff`)
- `highlight_text`: Text color for selected row (default: `#ffffff`)

## Exports

```python
from appinfra.ui import (
    # Console
    Console,
    console,  # Default console instance
    get_console,
    # Rich components (with fallbacks)
    Panel,
    Progress,
    ProgressLogger,
    Table,
    RICH_AVAILABLE,
    # Help formatting
    RichHelpFormatter,
    get_help_formatter,
    # Prompts
    prompts,
    confirm,
    text,
    password,
    select,
    select_scrollable,  # Arrow-key scrollable selection
    select_table,  # Table-style scrollable selection
    multiselect,
    NonInteractiveError,
    INQUIRER_AVAILABLE,  # True if InquirerPy is installed
)
```
