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
    # ci-requires: pg
    # ci-requires: port:8000

Without a ``ci-run`` line the script runs once with no arguments. Each
``ci-run`` line is one case. A case is killed after ``ci-timeout`` seconds
(default 7) and reported as TIMEOUT. A ``ci-skip`` line skips the file.

``ci-stop`` is for servers and loops: a case still running after that many
seconds gets SIGTERM, and passes if it then exits within the timeout,
whatever the exit code. Exiting before the stop time is judged by exit code
as usual. Whatever is left in the case's process group is killed afterwards.

``ci-requires`` names a service or resource the file needs. Each is probed
once before anything runs; when one is unavailable, every file declaring it
is reported with a warning mark and counted as skipped instead of failing.
Files declaring the same requirement share it, so they run one at a time
while everything else stays concurrent around them. Two forms are known,
any other is rejected:

- ``pg``: a real Postgres connection. The endpoint (``--pg``, else
  ``INFRA_PGSERVER_HOST`` / ``INFRA_PGSERVER_PORT``, else 127.0.0.1:25432)
  must accept a TCP connect.
- ``port:N``: the file binds TCP port N. The probe binds it on all
  interfaces and releases it; a port another process holds is unavailable.

Scripts run with stdin closed and inherit the current working directory, so
relative paths resolve the same way as under ``make``. That directory, the
project root, is prepended to ``PYTHONPATH``: examples import the project
from the source tree, with or without an installed copy. Each case gets a
private scratch directory as ``TMPDIR``, removed afterwards, so an example
that writes files uses ``tempfile`` and lands there, never in the checkout.

Files run concurrently, ``--jobs`` at a time (0: one per CPU). A file's
cases stay sequential, and results print in discovery order as each file
completes, so the report reads the same as a serial run.

Usage::

    run_examples.py <examples-dir> [--jobs N] [--timeout N] [--only SUBSTRING]
                    [--pg HOST:PORT] [-v]
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from appinfra.ui import status

_MARKER_RE = re.compile(r"^#\s*ci-(run|skip|stop|timeout|requires):\s*(.*?)\s*$")
_DEFAULT_TIMEOUT_S = 7.0
_OUTPUT_TAIL_LINES = 15
_FAILING = ("FAIL", "TIMEOUT")
# Result-state marks. Draws from the shared status palette so scripts and
# Python tooling stay visually consistent. TIMEOUT reuses the FAIL mark —
# the specific reason surfaces in the result's ``detail`` field. SKIP
# reuses the pending mark; both mean "did not run".
_MARKS = {
    "PASS": status.mark_ok(),
    "FAIL": status.mark_fail(),
    "TIMEOUT": status.mark_fail(),
    "SKIP": status.mark_pending(),
    "UNMET": status.mark_warn(),
}

# Requirement keys are "pg" or "port:N". The pg skip reason matches the
# sentinel the test suite uses for the same condition so the two read alike
# in check.sh's skip summary.
_PG_REQUIREMENT = "pg"
_PG_UNAVAILABLE = "pg-unavailable"
_PORT_PREFIX = "port:"
# Endpoint used when neither --pg nor INFRA_PGSERVER_* names one. Matches the
# canonical port in etc/pg.yaml.
_DEFAULT_PG_HOST = "127.0.0.1"
_DEFAULT_PG_PORT = 25432
_PROBE_TIMEOUT_S = 2.0


@dataclass
class Spec:
    """How one example file is exercised."""

    path: Path
    cases: list[str] = field(default_factory=list)
    timeout_s: float = _DEFAULT_TIMEOUT_S
    stop_s: float | None = None
    skip_reason: str | None = None
    requires: set[str] = field(default_factory=set)


@dataclass
class Result:
    """Outcome of one case."""

    spec: Spec
    args: str
    status: str
    detail: str = ""


def parse_spec(path: Path, default_timeout_s: float) -> Spec:
    """Read the ci-* markers from a file's comment lines.

    Raises ``ValueError`` on a ``ci-requires`` name the runner cannot probe,
    so a typo fails the run instead of silently running the file unguarded.
    """
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
        elif kind == "requires":
            spec.requires.add(parse_requirement(path, value))
    if not spec.cases:
        spec.cases.append("")
    return spec


def parse_port(text: str, source: str) -> int:
    """Parse a TCP port, 1 to 65535. Raises ``ValueError`` naming ``source``."""
    if text.isdigit() and 1 <= int(text) <= 65535:
        return int(text)
    raise ValueError(f"{source}: port must be 1-65535, got '{text}'")


def parse_requirement(path: Path, value: str) -> str:
    """Validate one ``ci-requires`` value and return its key.

    Raises ``ValueError`` for anything but ``pg`` or ``port:N``.
    """
    if value == _PG_REQUIREMENT:
        return value
    if value.startswith(_PORT_PREFIX):
        port = parse_port(value[len(_PORT_PREFIX) :], f"{path}: ci-requires '{value}'")
        return f"{_PORT_PREFIX}{port}"
    raise ValueError(
        f"{path}: unknown ci-requires '{value}' (known: {_PG_REQUIREMENT}, port:N)"
    )


def resolve_pg_endpoint(override: str | None) -> tuple[str, int]:
    """Pick the Postgres endpoint to probe: ``--pg``, else env, else default.

    Raises ``ValueError`` on a malformed ``--pg`` or ``INFRA_PGSERVER_PORT``;
    a bad value must not fall back to the default and probe the wrong port.
    """
    if override:
        host, sep, port_text = override.rpartition(":")
        if not sep or not host:
            raise ValueError(f"--pg expects HOST:PORT, got '{override}'")
        return host, parse_port(port_text, "--pg")
    host = os.environ.get("INFRA_PGSERVER_HOST", _DEFAULT_PG_HOST)
    env_port = os.environ.get("INFRA_PGSERVER_PORT")
    if env_port is None:
        return host, _DEFAULT_PG_PORT
    return host, parse_port(env_port, "INFRA_PGSERVER_PORT")


def probe_tcp(host: str, port: int) -> bool:
    """Confirm something accepts a TCP connection at host:port."""
    try:
        with socket.create_connection((host, port), timeout=_PROBE_TIMEOUT_S):
            return True
    except OSError:
        return False


def probe_bind(port: int) -> bool:
    """Confirm TCP ``port`` can be bound on all interfaces right now.

    SO_REUSEADDR mirrors what servers set, so a socket lingering in
    TIME_WAIT from an earlier run does not count as taken; a live listener
    still does.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", port))
            return True
    except OSError:
        return False


def requirement_reason(key: str) -> str:
    """Short skip reason for an unmet requirement, as shown in summaries."""
    if key == _PG_REQUIREMENT:
        return _PG_UNAVAILABLE
    return f"port {key[len(_PORT_PREFIX) :]} in use"


def unmet_requirements(specs: list[Spec], pg: tuple[str, int]) -> dict[str, str]:
    """Probe each requirement any spec declares; map the unavailable ones to a detail.

    Only requirements actually declared are probed, so a tree with no
    ``ci-requires`` line pays nothing.
    """
    unmet: dict[str, str] = {}
    declared: set[str] = set().union(*(spec.requires for spec in specs))
    for key in sorted(declared):
        if key == _PG_REQUIREMENT:
            host, port = pg
            if not probe_tcp(host, port):
                unmet[key] = f"{_PG_UNAVAILABLE}: {host}:{port} unreachable"
        elif not probe_bind(int(key[len(_PORT_PREFIX) :])):
            unmet[key] = requirement_reason(key)
    return unmet


def discover(examples_dir: Path, only: str | None) -> list[Path]:
    """List example scripts in a stable order, excluding package markers."""
    files = sorted(p for p in examples_dir.rglob("*.py") if p.name != "__init__.py")
    if only:
        files = [p for p in files if only in str(p)]
    return files


def run_case(spec: Spec, args: str) -> Result:
    """Run one case in its own process group and classify the outcome."""
    scratch = Path(tempfile.mkdtemp(prefix="example-"))
    proc = _spawn([sys.executable, str(spec.path), *shlex.split(args)], scratch)
    out_chunks, err_chunks, readers = _start_readers(proc)
    try:
        status, detail = _wait_case(spec, proc)
    finally:
        # Servers and demos may fork workers; leave nothing behind.
        _kill_group(proc)
        # Close pipes so readers see EOF even if a detached descendant still
        # holds a copy; then join with a timeout as a safety net.
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()
        for reader in readers:
            reader.join(timeout=2.0)
        shutil.rmtree(scratch, ignore_errors=True)
    if status == "FAIL":
        output = "".join(err_chunks) or "".join(out_chunks)
        tail = "\n".join(output.splitlines()[-_OUTPUT_TAIL_LINES:])
        detail = f"{detail}\n{tail}"
    return Result(spec, args, status, detail)


def _spawn(cmd: list[str], scratch: Path) -> subprocess.Popen[str]:
    """Start a case in its own session with stdin closed and output piped.

    ``scratch`` is the case's private directory, handed over as ``TMPDIR``
    so anything the example creates through ``tempfile`` lands there. An
    ``INFRA_*`` name is not an option: the config layer reads every such
    variable as a config override.
    """
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["TMPDIR"] = str(scratch)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (os.getcwd(), env.get("PYTHONPATH")) if p
    )
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


def run_spec(
    spec: Spec, unmet: dict[str, str], locks: dict[str, threading.Lock]
) -> list[Result]:
    """Run every case of one file in order, or skip the file.

    A file whose requirement is in ``unmet`` is not started: it would only
    crash on the missing service. Otherwise the file holds the lock of every
    requirement it declares for all its cases, so two files sharing a
    database or a port never overlap. Locks are taken in sorted key order,
    the same order in every file, so no two files can deadlock.
    """
    if spec.skip_reason is not None:
        return [Result(spec, "", "SKIP", spec.skip_reason)]
    missing = sorted(spec.requires & unmet.keys())
    if missing:
        return [Result(spec, "", "UNMET", "; ".join(unmet[name] for name in missing))]
    held = [locks[key] for key in sorted(spec.requires)]
    for lock in held:
        lock.acquire()
    try:
        return [run_case(spec, args) for args in spec.cases]
    finally:
        for lock in reversed(held):
            lock.release()


def run_all(
    specs: list[Spec],
    unmet: dict[str, str],
    jobs: int,
    report: Callable[[Result], None],
) -> list[Result]:
    """Run files ``jobs`` at a time; report results in discovery order.

    Futures are drained in submission order, so a file's results are printed
    once it and every file before it have finished. The report therefore
    reads exactly like a serial run, only sooner. Files sharing a
    requirement queue on its lock while the rest of the pool keeps going.
    """
    declared: set[str] = set().union(*(spec.requires for spec in specs))
    locks = {key: threading.Lock() for key in declared}
    results: list[Result] = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(run_spec, spec, unmet, locks) for spec in specs]
        for future in futures:
            for result in future.result():
                report(result)
                results.append(result)
    return results


def print_result(result: Result, root: Path, verbose: bool) -> None:
    """Print one line for a case, plus details for failures."""
    label = f"{result.spec.path.relative_to(root)} {result.args}".rstrip()
    if result.status in ("PASS", "SKIP", "UNMET") and result.detail:
        label = f"{label}  {status.gray('(' + result.detail + ')')}"
    print(f"{_MARKS[result.status]} {label}", flush=True)
    if result.status in _FAILING or (verbose and result.detail):
        for line in result.detail.splitlines():
            print(f"    {status.gray(line)}", flush=True)


def print_summary(
    results: list[Result], unmet: dict[str, str], elapsed_s: float
) -> None:
    """Print the totals and the wall time, as check.sh does.

    Unmet files count as skipped; when there are any, a trailing
    ``N unmet (reason, ...)`` clause names them, and check.sh reads that
    clause to mark its Examples line with a warning.
    """
    counts = {
        status: sum(1 for r in results if r.status == status)
        for status in ("PASS", "FAIL", "TIMEOUT", "SKIP", "UNMET")
    }
    paint = status.green if counts["FAIL"] + counts["TIMEOUT"] == 0 else status.red
    skipped = counts["SKIP"] + counts["UNMET"]
    unmet_clause = ""
    if counts["UNMET"]:
        reasons = ", ".join(requirement_reason(key) for key in sorted(unmet))
        unmet_clause = f", {counts['UNMET']} unmet ({reasons})"
    body = (
        f"{counts['PASS']} passed, {counts['FAIL']} failed, "
        f"{counts['TIMEOUT']} timed out, {skipped} skipped{unmet_clause}"
    )
    print(
        f"\n{paint(body)} {status.gray(f'in {elapsed_s:.1f}s')}",
        flush=True,
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Run every example script and fail on errors."
    )
    parser.add_argument("examples_dir", type=Path, help="directory to scan")
    parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        help="files to run concurrently; 0 means one per CPU (default: %(default)s)",
    )
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
        "--pg",
        metavar="HOST:PORT",
        help="Postgres endpoint probed for `ci-requires: pg` files "
        "(default: INFRA_PGSERVER_HOST/PORT, else "
        f"{_DEFAULT_PG_HOST}:{_DEFAULT_PG_PORT})",
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
    if ns.jobs < 0:
        print(f"--jobs must be 0 or positive, got {ns.jobs}", file=sys.stderr)
        return 2
    start = time.monotonic()
    try:
        # Resolve --pg up front so a malformed value fails even when no
        # selected file declares pg.
        pg = resolve_pg_endpoint(ns.pg)
        specs = [parse_spec(p, ns.timeout) for p in discover(ns.examples_dir, ns.only)]
        unmet = unmet_requirements(specs, pg)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    jobs = ns.jobs or os.cpu_count() or 1
    results = run_all(
        specs, unmet, jobs, lambda r: print_result(r, ns.examples_dir, ns.verbose)
    )
    print_summary(results, unmet, time.monotonic() - start)
    return 1 if any(r.status in _FAILING for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
