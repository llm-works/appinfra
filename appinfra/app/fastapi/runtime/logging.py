"""Subprocess logging isolation utilities."""

import logging
import sys
from pathlib import Path
from typing import TextIO


def setup_subprocess_logging(
    log_file: str | None,
    log_level: str = "INFO",
    redirect_stdio: bool = True,
) -> logging.Logger:
    """
    Isolate subprocess logging to dedicated file.

    This function MUST be called early in the subprocess, before creating
    the FastAPI app or importing libraries that configure logging.

    Critical implementation notes:
    - Replaces (not appends to) root logger handlers
    - Redirects stdout/stderr for libraries that print directly (e.g., C extensions)
    - File is opened in append mode to preserve logs across restarts

    Args:
        log_file: Path to log file. If None, no file logging is configured
            but a logger is still returned.
        log_level: Logging level (default: "INFO")
        redirect_stdio: Redirect stdout/stderr to log file (default: True).
            Required for capturing output from libraries that bypass logging.

    Returns:
        Configured logger for subprocess use
    """
    logger = logging.getLogger("fastapi.subprocess")

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Configure file handler
        handler = logging.FileHandler(log_file)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

        # MUST replace root logger handlers (not just add)
        # This ensures subprocess logs don't go to parent process handlers
        logging.root.handlers = [handler]
        logging.root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

        # Redirect stdout/stderr for libraries that print directly
        # (e.g., native code, C extensions that bypass Python logging)
        if redirect_stdio:
            log_stream = open(log_file, "a")  # noqa: SIM115
            sys.stdout = log_stream  # type: ignore[assignment]
            sys.stderr = log_stream  # type: ignore[assignment]

    return logger


def restore_stdio(
    original_stdout: TextIO | None = None,
    original_stderr: TextIO | None = None,
) -> None:
    """
    Restore original stdout/stderr.

    Call this during subprocess cleanup if stdio was redirected.

    Args:
        original_stdout: Original stdout (defaults to sys.__stdout__)
        original_stderr: Original stderr (defaults to sys.__stderr__)
    """
    sys.stdout = original_stdout or sys.__stdout__
    sys.stderr = original_stderr or sys.__stderr__
