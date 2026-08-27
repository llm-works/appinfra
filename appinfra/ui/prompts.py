# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Interactive prompts for CLI tools.

Provides smart confirmations, password input, selections, and
other interactive prompts. Respects --yes and --non-interactive
flags, and auto-detects non-TTY environments.
"""

import getpass
import os
import re
import sys
from collections.abc import Callable, Sequence
from typing import Any, cast

# Check for questionary availability
try:
    import questionary
    from questionary import Style

    QUESTIONARY_AVAILABLE = True
except ImportError:
    QUESTIONARY_AVAILABLE = False
    questionary = None  # type: ignore[assignment]
    Style = None  # type: ignore[assignment, misc]

# Check for InquirerPy availability
try:
    from InquirerPy import inquirer as inq
    from InquirerPy.utils import InquirerPyStyle

    INQUIRER_AVAILABLE = True
except ImportError:
    INQUIRER_AVAILABLE = False
    inq = None  # type: ignore[assignment]
    InquirerPyStyle = None  # type: ignore[assignment, misc]

# Backward compatibility alias
TERM_MENU_AVAILABLE = INQUIRER_AVAILABLE


# Default style for prompts
PROMPT_STYLE = None
if QUESTIONARY_AVAILABLE and Style is not None:
    PROMPT_STYLE = Style(
        [
            ("question", "bold"),
            ("answer", "fg:green bold"),
            ("pointer", "fg:cyan bold"),
            ("highlighted", "fg:cyan bold"),
            ("selected", "fg:green"),
        ]
    )


def _is_interactive() -> bool:
    """Check if we're in an interactive terminal."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _get_auto_confirm() -> bool:
    """Check if auto-confirm is enabled via environment."""
    return os.environ.get("APPINFRA_YES", "").lower() in ("1", "true", "yes")


def _get_non_interactive() -> bool:
    """Check if non-interactive mode is forced via environment."""
    return os.environ.get("APPINFRA_NON_INTERACTIVE", "").lower() in (
        "1",
        "true",
        "yes",
    )


class NonInteractiveError(Exception):
    """Raised when interactive input is required but not available."""

    pass


def _confirm_fallback(message: str, default: bool) -> bool:
    """Fallback confirmation using standard input."""
    suffix = " [Y/n]" if default else " [y/N]"
    try:
        response = input(f"{message}{suffix} ").strip().lower()
        return response in ("y", "yes") if response else default
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def confirm(
    message: str, *, default: bool = False, auto_confirm: bool | None = None
) -> bool:
    """
    Ask for confirmation.

    Args:
        message: The confirmation question
        default: Default value if user just presses Enter
        auto_confirm: Override auto-confirm behavior (None = auto-detect)

    Returns:
        True if confirmed, False otherwise

    Raises:
        NonInteractiveError: If in non-interactive mode and no auto-confirm
    """
    if auto_confirm is True or (auto_confirm is None and _get_auto_confirm()):
        return True
    if not _is_interactive() or _get_non_interactive():
        if auto_confirm is False:
            raise NonInteractiveError(
                f"Cannot prompt for confirmation in non-interactive mode: {message}"
            )
        return default
    if QUESTIONARY_AVAILABLE and questionary:
        result = questionary.confirm(message, default=default, style=PROMPT_STYLE).ask()
        return result if result is not None else default
    return _confirm_fallback(message, default)


def _text_fallback(
    message: str, default: str, validate: Callable[[str], bool] | None
) -> str:
    """Fallback text input using standard input."""
    prompt = f"{message} [{default}] " if default else f"{message} "
    while True:
        try:
            response = input(prompt).strip() or default
            if validate and not validate(response):
                print("Invalid input. Please try again.")
                continue
            return response
        except (EOFError, KeyboardInterrupt):
            print()
            return default


def text(
    message: str,
    *,
    default: str = "",
    validate: Callable[[str], bool] | None = None,
    multiline: bool = False,
) -> str:
    """
    Prompt for text input.

    Args:
        message: The prompt message
        default: Default value
        validate: Optional validation function
        multiline: Allow multiline input

    Returns:
        User input string

    Raises:
        NonInteractiveError: If in non-interactive mode
    """
    if not _is_interactive() or _get_non_interactive():
        if default:
            return default
        raise NonInteractiveError(
            f"Cannot prompt for text input in non-interactive mode: {message}"
        )
    if QUESTIONARY_AVAILABLE and questionary:
        result = questionary.text(
            message,
            default=default,
            validate=validate,
            multiline=multiline,
            style=PROMPT_STYLE,
        ).ask()
        return result if result is not None else default
    return _text_fallback(message, default, validate)


def _password_questionary(message: str, do_confirm: bool) -> str:
    """Get password using questionary."""
    pwd_result = questionary.password(message, style=PROMPT_STYLE).ask()
    if pwd_result is None:
        return ""
    pwd: str = str(pwd_result)
    if do_confirm:
        pwd2_result = questionary.password(
            "Confirm password:", style=PROMPT_STYLE
        ).ask()
        if str(pwd2_result) if pwd2_result else "" != pwd:
            print("Passwords do not match. Please try again.")
            return _password_questionary(message, do_confirm)
    return pwd


def _password_getpass(message: str, do_confirm: bool) -> str:
    """Get password using getpass fallback."""
    while True:
        pwd = getpass.getpass(f"{message} ")
        if do_confirm:
            if getpass.getpass("Confirm password: ") != pwd:
                print("Passwords do not match. Please try again.")
                continue
        return pwd


def password(message: str, *, confirm: bool = False) -> str:
    """
    Prompt for password input (masked).

    Args:
        message: The prompt message
        confirm: Ask for confirmation (enter password twice)

    Returns:
        Password string

    Raises:
        NonInteractiveError: If in non-interactive mode
    """
    if not _is_interactive() or _get_non_interactive():
        raise NonInteractiveError(
            f"Cannot prompt for password in non-interactive mode: {message}"
        )
    if QUESTIONARY_AVAILABLE and questionary:
        return _password_questionary(message, confirm)
    return _password_getpass(message, confirm)


def _normalize_choices(choices: Sequence[str] | Sequence[dict[str, Any]]) -> list[dict]:
    """Normalize choices to list of dicts with name and value."""
    choice_list = []
    for c in choices:
        if isinstance(c, dict):
            choice_list.append(c)
        else:
            choice_list.append({"name": str(c), "value": str(c)})
    return choice_list


def _select_questionary(
    message: str, choice_list: list[dict], default: str | None
) -> str:
    """Use questionary for selection if available."""
    result = questionary.select(
        message,
        choices=[c["name"] for c in choice_list],
        default=default,
        style=PROMPT_STYLE,
    ).ask()

    if result is None:
        return default or str(choice_list[0]["value"])

    for c in choice_list:
        if c["name"] == result:
            return str(c["value"])
    return str(result)


def _select_fallback(message: str, choice_list: list[dict], default: str | None) -> str:
    """Fallback to numbered selection without questionary."""
    print(message)
    for i, c in enumerate(choice_list, 1):
        marker = "*" if c["value"] == default else " "
        print(f"  {marker}{i}. {c['name']}")

    while True:
        try:
            response = input("Enter number: ").strip()
            if not response and default:
                return default
            idx = int(response) - 1
            if 0 <= idx < len(choice_list):
                return str(choice_list[idx]["value"])
            print(f"Please enter a number between 1 and {len(choice_list)}")
        except ValueError:
            print("Please enter a valid number")
        except (EOFError, KeyboardInterrupt):
            print()
            return default or str(choice_list[0]["value"])


def select(
    message: str,
    choices: Sequence[str] | Sequence[dict[str, Any]],
    *,
    default: str | None = None,
) -> str:
    """
    Prompt for single selection from choices.

    Args:
        message: The prompt message
        choices: List of choices (strings or dicts with 'name' and 'value')
        default: Default selection

    Returns:
        Selected value

    Raises:
        NonInteractiveError: If in non-interactive mode

    Example:
        env = select("Choose environment:", ["dev", "staging", "prod"])
    """
    if not _is_interactive() or _get_non_interactive():
        if default:
            return default
        raise NonInteractiveError(
            f"Cannot prompt for selection in non-interactive mode: {message}"
        )

    choice_list = _normalize_choices(choices)

    if QUESTIONARY_AVAILABLE and questionary:
        return _select_questionary(message, choice_list, default)
    return _select_fallback(message, choice_list, default)


def _multiselect_questionary(
    message: str, choice_list: list[dict], default: Sequence[str] | None
) -> list[str]:
    """Use questionary for multiselect if available."""
    q_choices = []
    for c in choice_list:
        checked = bool(default and c["value"] in default)
        q_choices.append(questionary.Choice(c["name"], checked=checked))

    result = questionary.checkbox(message, choices=q_choices, style=PROMPT_STYLE).ask()

    if result is None:
        return list(default) if default else []

    values = []
    for name in result:
        for c in choice_list:
            if c["name"] == name:
                values.append(str(c["value"]))
                break
    return values


def _multiselect_fallback(
    message: str, choice_list: list[dict], default: Sequence[str] | None
) -> list[str]:
    """Fallback to comma-separated input without questionary."""
    print(message)
    for i, c in enumerate(choice_list, 1):
        marker = "*" if default and c["value"] in default else " "
        print(f"  {marker}{i}. {c['name']}")

    print("Enter numbers separated by commas (e.g., 1,3,4)")
    if default:
        print(f"Press Enter for default: {', '.join(default)}")

    try:
        response = input("Selection: ").strip()
        if not response:
            return list(default) if default else []

        selected = []
        for part in response.split(","):
            try:
                idx = int(part.strip()) - 1
                if 0 <= idx < len(choice_list):
                    selected.append(str(choice_list[idx]["value"]))
            except ValueError:
                pass
        return selected
    except (EOFError, KeyboardInterrupt):
        print()
        return list(default) if default else []


def multiselect(
    message: str,
    choices: Sequence[str] | Sequence[dict[str, Any]],
    *,
    default: Sequence[str] | None = None,
) -> list[str]:
    """
    Prompt for multiple selections from choices.

    Args:
        message: The prompt message
        choices: List of choices (strings or dicts with 'name' and 'value')
        default: Default selections

    Returns:
        List of selected values

    Raises:
        NonInteractiveError: If in non-interactive mode

    Example:
        features = multiselect(
            "Enable features:",
            ["auth", "logging", "cache"],
            default=["logging"]
        )
    """
    if not _is_interactive() or _get_non_interactive():
        if default:
            return list(default)
        raise NonInteractiveError(
            f"Cannot prompt for multiselect in non-interactive mode: {message}"
        )

    choice_list = _normalize_choices(choices)

    if QUESTIONARY_AVAILABLE and questionary:
        return _multiselect_questionary(message, choice_list, default)
    return _multiselect_fallback(message, choice_list, default)


def _require_term_menu() -> None:
    """Raise ImportError if simple-term-menu is not installed."""
    if not TERM_MENU_AVAILABLE:
        raise ImportError(
            "Scrollable selection requires simple-term-menu. "
            "Install with: pip install appinfra[ui]"
        )


def _display_fallback_page(
    choices: list[str], start: int, end: int, default_index: int
) -> None:
    """Display a page of choices for fallback selection."""
    for i in range(start, end):
        marker = ">" if i == default_index else " "
        print(f"  {marker}{i + 1}. {choices[i]}")
    if start > 0:
        print("  (p) Previous page")
    if end < len(choices):
        print("  (n) Next page")


def _select_scrollable_fallback(
    message: str, choices: list[str], default_index: int, max_height: int
) -> int | None:
    """Fallback to numbered selection when simple-term-menu is not available."""
    print(message)
    start, page_size = 0, max_height

    while True:
        end = min(start + page_size, len(choices))
        _display_fallback_page(choices, start, end, default_index)

        try:
            response = input("Enter number (or p/n): ").strip().lower()
            if response == "n" and end < len(choices):
                start = end
            elif response == "p" and start > 0:
                start = max(0, start - page_size)
            elif not response:
                return default_index
            else:
                idx = int(response) - 1
                if 0 <= idx < len(choices):
                    return idx
                print(f"Please enter a number between 1 and {len(choices)}")
        except ValueError:
            print("Invalid input")
        except (EOFError, KeyboardInterrupt):
            print()
            return None


def select_scrollable(
    message: str,
    choices: Sequence[str],
    *,
    default_index: int = 0,
    max_height: int = 10,
    highlight_color: str = "#005fff",
    highlight_text: str = "#ffffff",
) -> int | None:
    """
    Scrollable single selection with arrow keys.

    Args:
        message: Title/prompt message displayed above the menu
        choices: List of string options to choose from
        default_index: Initially highlighted option (0-based)
        max_height: Maximum visible rows before scrolling
        highlight_color: Background color for highlighted row (hex color)
        highlight_text: Text color for highlighted row (hex color)

    Returns:
        Selected index (0-based), or None if cancelled

    Raises:
        NonInteractiveError: If in non-interactive mode

    Example:
        idx = select_scrollable(
            "Choose server:",
            ["web-1", "web-2", "db-1", "cache-1"],
            max_height=5
        )
        if idx is not None:
            print(f"Selected: {choices[idx]}")
    """
    if not _is_interactive() or _get_non_interactive():
        raise NonInteractiveError(
            f"Cannot show scrollable selection in non-interactive mode: {message}"
        )

    choice_list = list(choices)

    if not INQUIRER_AVAILABLE:
        return _select_scrollable_fallback(
            message, choice_list, default_index, max_height
        )

    result = _inquirer_select(
        message, choice_list, default_index, max_height, highlight_color, highlight_text
    )
    if result is None:
        return None

    try:
        return choice_list.index(result)
    except ValueError:
        return None


def _inquirer_select(
    message: str,
    choices: list[str],
    default_index: int,
    max_height: int,
    highlight_color: str,
    highlight_text: str,
) -> str | None:
    """Invoke InquirerPy select with standard styling and keybindings."""
    style = InquirerPyStyle({"pointer": f"bg:{highlight_color} {highlight_text} bold"})
    default_value = (
        choices[default_index] if 0 <= default_index < len(choices) else None
    )

    result = inq.select(
        message=message,
        choices=choices,
        default=default_value,
        max_height=max_height,
        style=style,
        keybindings={"skip": [{"key": "q"}, {"key": "escape"}]},
        mandatory=False,
    ).execute()
    return cast(str, result) if result is not None else None


def _result_to_row(
    result: str | None, formatted: list[str], row_list: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Convert InquirerPy result string back to row dict."""
    if result is None:
        return None
    try:
        return row_list[formatted.index(result)]
    except ValueError:
        return None


def _select_table_fallback(
    message: str,
    header: str,
    formatted: list[str],
    row_list: list[dict[str, Any]],
    default_index: int,
    max_height: int,
) -> dict[str, Any] | None:
    """Fallback for table selection when InquirerPy is not available."""
    print(f"{message}\n{header}")
    print("-" * len(header))
    idx = _select_scrollable_fallback("", formatted, default_index, max_height)
    return row_list[idx] if idx is not None else None


# Pattern to match ANSI escape sequences (color codes, cursor movement, etc.)
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")

# Zero-width Unicode characters that don't contribute to visible width
_ZERO_WIDTH = frozenset(
    {
        "\u200b",  # Zero Width Space
        "\u200c",  # Zero Width Non-Joiner
        "\u200d",  # Zero Width Joiner
        "\u2063",  # Invisible Separator
        "\ufeff",  # Zero Width No-Break Space (BOM)
        "\ufe0f",  # Variation Selector-16 (emoji modifier)
    }
)


def _visible_len(s: str) -> int:
    """Return display width of string, excluding ANSI codes and zero-width chars."""
    plain = _ANSI_ESCAPE.sub("", s)
    return sum(1 for c in plain if c not in _ZERO_WIDTH)


def _pad(s: str, width: int) -> str:
    """Pad string to width using visible length for calculation."""
    padding = width - _visible_len(s)
    return s + " " * max(0, padding)


def _format_table_rows(
    rows: Sequence[dict[str, Any]], columns: Sequence[str], column_spacing: int = 2
) -> tuple[str, list[str]]:
    """Format rows as aligned table strings. Returns (header, formatted_rows)."""
    row_list = list(rows)
    col_list = list(columns)

    widths = {
        col: max(
            _visible_len(str(col)),
            max(_visible_len(str(r.get(col, ""))) for r in row_list),
        )
        for col in col_list
    }

    spacing = " " * column_spacing
    header = spacing.join(_pad(str(col), widths[col]) for col in col_list)
    formatted = [
        spacing.join(_pad(str(r.get(col, "")), widths[col]) for col in col_list)
        for r in row_list
    ]
    return header, formatted


def select_table(
    message: str,
    rows: Sequence[dict[str, Any]],
    columns: Sequence[str],
    *,
    default_index: int = 0,
    max_height: int = 10,
    column_spacing: int = 2,
    highlight_color: str = "#005fff",
    highlight_text: str = "#ffffff",
) -> dict[str, Any] | None:
    """
    Scrollable table selection with arrow keys.

    Displays rows as aligned columns and returns the selected row dict.

    Args:
        message: Title/prompt message displayed above the table
        rows: List of dicts, each representing a row
        columns: Column keys to display (in order)
        default_index: Initially highlighted row (0-based)
        max_height: Maximum visible rows before scrolling
        column_spacing: Spaces between columns
        highlight_color: Background color for highlighted row (hex color)
        highlight_text: Text color for highlighted row (hex color)

    Returns:
        Selected row dict, or None if cancelled

    Raises:
        NonInteractiveError: If in non-interactive mode

    Example:
        servers = [
            {"id": "001", "name": "web-prod", "status": "running"},
            {"id": "002", "name": "db-main", "status": "stopped"},
        ]
        selected = select_table(
            "Choose server:",
            servers,
            columns=["id", "name", "status"],
            max_height=5
        )
        if selected:
            print(f"Selected: {selected['name']}")
    """
    if not _is_interactive() or _get_non_interactive():
        raise NonInteractiveError(
            f"Cannot show table selection in non-interactive mode: {message}"
        )

    if not rows:
        return None

    row_list = list(rows)
    header, formatted = _format_table_rows(row_list, columns, column_spacing)

    if not INQUIRER_AVAILABLE:
        return _select_table_fallback(
            message, header, formatted, row_list, default_index, max_height
        )

    full_message = f"{message}\n  {header}"  # 2-space indent to match selection marker
    result = _inquirer_select(
        full_message,
        formatted,
        default_index,
        max_height,
        highlight_color,
        highlight_text,
    )
    return _result_to_row(result, formatted, row_list)
