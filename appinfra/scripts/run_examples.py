#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Run every example script and fail on errors.

Each example declares how it is exercised in header comments::

    # ci-run: --help
    # ci-run: greet --name CI
    # ci-stop: 4
    # ci-timeout: 10
    # ci-skip: requires a TTY

Without a ``ci-run`` line the script runs once with no arguments. Each
``ci-run`` line is one case. A case is killed after ``ci-timeout`` seconds
(default 7) and reported as TIMEOUT. A ``ci-skip`` line skips the file.

``ci-stop`` is for servers and loops: a case still running after that many
seconds gets SIGTERM, and passes if it then exits within the timeout,
whatever the exit code. Exiting before the stop time is judged by exit code
as usual. Whatever is left in the case's process group is killed afterwards.

Scripts run with stdin closed and inherit the current working directory, so
relative paths resolve the same way as under ``make``.

Usage::

    run_examples.py <examples-dir> [--timeout N] [--only SUBSTRING] [-v]
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

_MARKER_RE = re.compile(r"^#\s*ci-(run|skip|stop|timeout):\s*(.*?)\s*$")
_DEFAULT_TIMEOUT_S = 7.0
_OUTPUT_TAIL_LINES = 15
_FAILING = ("FAIL", "TIMEOUT")
# Same palette as check.sh.
_GREEN, _RED, _GRAY, _RESET = "\033[32m", "\033[31m", "\033[90m", "\033[0m"
_MARKS = {
    "PASS": f"{_GREEN}[✓]{_RESET}",
    "FAIL": f"{_RED}[✗]{_RESET}",
    "TIMEOUT": f"{_RED}[⏱]{_RESET}",
    "SKIP": f"{_GRAY}[–]{_RESET}",
}


@dataclass
class Spec:
    """How one example file is exercised."""

    path: Path
    cases: list[str] = field(default_factory=list)
    timeout_s: float = _DEFAULT_TIMEOUT_S
    stop_s: float | None = None
    skip_reason: str | None = None


@dataclass
class Result:
    """Outcome of one case."""

    spec: Spec
    args: str
    status: str
    detail: str = ""


def parse_spec(path: Path, default_timeout_s: float) -> Spec:
    """Read the ci-* markers from a file's comment lines."""
    spec = Spec(path=path, timeout_s=default_timeout_s)
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _MARKER_RE.match(line)
        if match is None:
            continue
        kind, value = match.group(1), match.group(2)
        if kind == "run":
            spec.cases.append(value)
        elif kind == "skip":
            spec.skip_reason = value or "skipped"
        elif kind == "stop":
            spec.stop_s = float(value)
        elif kind == "timeout":
            spec.timeout_s = float(value)
    if not spec.cases:
        spec.cases.append("")
    return spec


def discover(examples_dir: Path, only: str | None) -> list[Path]:
    """List example scripts in a stable order, excluding package markers."""
    files = sorted(p for p in examples_dir.rglob("*.py") if p.name != "__init__.py")
    if only:
        files = [p for p in files if only in str(p)]
    return files


def run_case(spec: Spec, args: str) -> Result:
    """Run one case in its own process group and classify the outcome."""
    proc = _spawn([sys.executable, str(spec.path), *shlex.split(args)])
    out_chunks, err_chunks, readers = _start_readers(proc)
    try:
        status, detail = _wait_case(spec, proc)
    finally:
        # Servers and demos may fork workers; leave nothing behind. This also
        # closes the pipes, so the readers finish.
        _kill_group(proc)
        for reader in readers:
            reader.join()
    if status == "FAIL":
        output = "".join(err_chunks) or "".join(out_chunks)
        tail = "\n".join(output.splitlines()[-_OUTPUT_TAIL_LINES:])
        detail = f"{detail}\n{tail}"
    return Result(spec, args, status, detail)


def _spawn(cmd: list[str]) -> subprocess.Popen[str]:
    """Start a case in its own session with stdin closed and output piped.

    Env vars that the CI container sets for the test postgres (INFRA_PGSERVER_*)
    are stripped so examples that load their own YAML configs don't fail on
    undeclared config paths.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("INFRA_PGSERVER_")}
    env["PYTHONUNBUFFERED"] = "1"
    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    )


def _start_readers(
    proc: subprocess.Popen[str],
) -> tuple[list[str], list[str], list[threading.Thread]]:
    """Drain stdout and stderr from threads.

    Waiting on the process instead of on pipe EOF keeps a forked worker that
    inherited the pipes from stalling the verdict, and keeps a chatty example
    from filling the pipe and blocking.
    """
    out_chunks: list[str] = []
    err_chunks: list[str] = []
    readers = [
        threading.Thread(target=_drain, args=(proc.stdout, out_chunks), daemon=True),
        threading.Thread(target=_drain, args=(proc.stderr, err_chunks), daemon=True),
    ]
    for reader in readers:
        reader.start()
    return out_chunks, err_chunks, readers


def _drain(stream: IO[str] | None, chunks: list[str]) -> None:
    """Read a pipe to EOF into chunks."""
    if stream is not None:
        chunks.append(stream.read())


def _wait_case(spec: Spec, proc: subprocess.Popen[str]) -> tuple[str, str]:
    """Wait for a case, applying the stop signal and the timeout."""
    stopped = ""
    try:
        if spec.stop_s is None:
            proc.wait(timeout=spec.timeout_s)
        else:
            try:
                proc.wait(timeout=spec.stop_s)
            except subprocess.TimeoutExpired:
                proc.terminate()  # SIGTERM to the process only: its handler runs
                stopped = f"SIGTERM at {spec.stop_s:g}s"
                proc.wait(timeout=spec.timeout_s)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", f"no exit within {spec.timeout_s:g}s"
    if stopped:
        return "PASS", f"{stopped} -> exit {proc.returncode}"
    if proc.returncode == 0:
        return "PASS", ""
    return "FAIL", f"exit {proc.returncode}"


def _kill_group(proc: subprocess.Popen[str]) -> None:
    """SIGKILL the case's process group, if anything in it is still alive."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_spec(spec: Spec, root: Path, verbose: bool) -> list[Result]:
    """Run every case of one file (or skip it), printing each as it finishes."""
    if spec.skip_reason is not None:
        skipped = Result(spec, "", "SKIP", spec.skip_reason)
        print_result(skipped, root, verbose)
        return [skipped]
    results: list[Result] = []
    for args in spec.cases:
        result = run_case(spec, args)
        print_result(result, root, verbose)
        results.append(result)
    return results


def print_result(result: Result, root: Path, verbose: bool) -> None:
    """Print one line for a case, plus details for failures."""
    label = f"{result.spec.path.relative_to(root)} {result.args}".rstrip()
    if result.status in ("PASS", "SKIP") and result.detail:
        label = f"{label}  {_GRAY}({result.detail}){_RESET}"
    print(f"{_MARKS[result.status]} {label}", flush=True)
    if result.status in _FAILING or (verbose and result.detail):
        for line in result.detail.splitlines():
            print(f"    {_GRAY}{line}{_RESET}", flush=True)


def print_summary(results: list[Result]) -> None:
    """Print the pass/fail/timeout/skip totals."""
    counts = {
        status: sum(1 for r in results if r.status == status)
        for status in ("PASS", "FAIL", "TIMEOUT", "SKIP")
    }
    color = _GREEN if counts["FAIL"] + counts["TIMEOUT"] == 0 else _RED
    print(
        f"\n{color}{counts['PASS']} passed, {counts['FAIL']} failed, "
        f"{counts['TIMEOUT']} timed out, {counts['SKIP']} skipped{_RESET}",
        flush=True,
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Run every example script and fail on errors."
    )
    parser.add_argument("examples_dir", type=Path, help="directory to scan")
    parser.add_argument(
        "--timeout",
        type=float,
        default=_DEFAULT_TIMEOUT_S,
        help="default per-case timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--only", help="run only files whose path contains this substring"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="print details for every case"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run all examples under the given directory; exit 1 on any failure."""
    ns = _build_parser().parse_args(argv)
    if not ns.examples_dir.is_dir():
        print(f"not a directory: {ns.examples_dir}", file=sys.stderr)
        return 2
    results: list[Result] = []
    for path in discover(ns.examples_dir, ns.only):
        results.extend(
            run_spec(parse_spec(path, ns.timeout), ns.examples_dir, ns.verbose)
        )
    print_summary(results)
    return 1 if any(r.status in _FAILING for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
