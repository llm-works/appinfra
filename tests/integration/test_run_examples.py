# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra/scripts/run_examples.py."""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_EXAMPLES_PY = REPO_ROOT / "appinfra" / "scripts" / "run_examples.py"


def test_examples_import_uninstalled_project_from_source_tree(tmp_path: Path) -> None:
    """An example imports a project that is not installed, with no PYTHONPATH set.

    Mirrors a fresh clone after `make setup` (dependencies only): the project
    is importable only from the source tree, and the example does not patch
    sys.path itself. The runner is started from the project root, as `make`
    does.
    """
    (tmp_path / "srcpkg_fixture").mkdir()
    (tmp_path / "srcpkg_fixture" / "__init__.py").write_text("VALUE = 42\n")
    examples_dir = tmp_path / "examples"
    examples_dir.mkdir()
    (examples_dir / "use_pkg.py").write_text(
        "import srcpkg_fixture\n\nassert srcpkg_fixture.VALUE == 42\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

    result = subprocess.run(
        [sys.executable, str(RUN_EXAMPLES_PY), str(examples_dir), "--jobs", "1"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed, 0 failed" in result.stdout


_FAILS = (
    "import sys\n"
    "for i in range(30):\n"
    "    print(f'stdout line {i}')\n"
    "sys.exit('the root cause')\n"
)


def _run_failing_example(tmp_path: Path, source: str, *flags: str) -> str:
    examples_dir = tmp_path / "examples"
    examples_dir.mkdir()
    (examples_dir / "fails.py").write_text(source)
    result = subprocess.run(
        [
            sys.executable,
            str(RUN_EXAMPLES_PY),
            str(examples_dir),
            "--jobs",
            "1",
            *flags,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    return result.stdout


def test_failed_example_shows_a_tail_of_stderr_by_default(tmp_path: Path) -> None:
    out = _run_failing_example(tmp_path, _FAILS)

    assert "the root cause" in out
    assert "stdout line 0" not in out  # stdout is dropped when stderr has output


def test_full_output_shows_both_streams_whole(tmp_path: Path) -> None:
    out = _run_failing_example(tmp_path, _FAILS, "--full-output")

    assert "--- stdout ---" in out
    assert all(f"stdout line {i}\n" in out for i in range(30))
    assert "--- stderr ---" in out
    assert "the root cause" in out


def test_a_hung_example_times_out(tmp_path: Path) -> None:
    """Its output goes through the same path as any failure's
    (test_full_output_shows_both_streams_whole); asserting it here would race the example's
    startup against the one-second timeout."""
    source = "# ci-timeout: 1\nimport time\ntime.sleep(30)\n"
    out = _run_failing_example(tmp_path, source, "--full-output")

    assert "no exit within 1s" in out


def test_passing_example_reports_its_warnings(tmp_path: Path) -> None:
    """A warning a library raises in a passing example is printed, under Python's defaults
    hidden: one line per distinct warning, in the form check.sh reads."""
    examples_dir = tmp_path / "examples"
    examples_dir.mkdir()
    # stacklevel=1: the warning belongs to oldlib, not __main__, so the defaults ignore it
    (examples_dir / "oldlib.py").write_text(
        "# ci-skip: a module the example imports\n"
        "import warnings\n\n"
        "def call():\n"
        "    warnings.warn('old api', DeprecationWarning, stacklevel=1)\n"
    )
    (examples_dir / "use_old.py").write_text(
        "# ci-run: --twice\nimport oldlib\n\noldlib.call()\noldlib.call()\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONWARNINGS"}

    result = subprocess.run(
        [sys.executable, str(RUN_EXAMPLES_PY), str(examples_dir), "--jobs", "1"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    warned = [
        line for line in result.stdout.splitlines() if line.startswith("warning:")
    ]
    assert warned == [
        "warning: use_old.py --twice: DeprecationWarning: old api (examples/oldlib.py:5)"
    ]


def _run_pg_example(tmp_path: Path, *flags: str, env: dict[str, str] | None = None):
    """Run one example that declares `ci-requires: pg`, with no INFRA_* overrides
    but those given."""
    examples_dir = tmp_path / "examples"
    examples_dir.mkdir()
    (examples_dir / "needs_pg.py").write_text("# ci-requires: pg\nprint('ran')\n")
    base = {k: v for k, v in os.environ.items() if not k.startswith("INFRA_")}
    return subprocess.run(
        [
            sys.executable,
            str(RUN_EXAMPLES_PY),
            str(examples_dir),
            "--jobs",
            "1",
            *flags,
        ],
        cwd=tmp_path,
        env={**base, **(env or {})},
        capture_output=True,
        text=True,
        timeout=60,
    )


def _pg_config(tmp_path: Path, port: int, key: str = "pgserver") -> Path:
    path = tmp_path / "etc" / "infra.yaml"
    path.parent.mkdir()
    path.write_text(f"{key}:\n  host: 127.0.0.1\n  port: {port}\n")
    return path


@contextlib.contextmanager
def _listening() -> Iterator[int]:
    """A TCP port on loopback that accepts connections, for the pg probe."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        yield sock.getsockname()[1]


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class TestPgEndpoint:
    """The endpoint `ci-requires: pg` is probed at comes from the project's config."""

    def test_the_config_names_the_endpoint(self, tmp_path: Path) -> None:
        with _listening() as port:
            config = _pg_config(tmp_path, port)
            result = _run_pg_example(tmp_path, "--pg-config", str(config))
        assert result.returncode == 0, result.stdout + result.stderr
        assert "1 passed, 0 failed" in result.stdout

    def test_an_unreachable_config_endpoint_is_named(self, tmp_path: Path) -> None:
        port = _closed_port()
        config = _pg_config(tmp_path, port, key="db_server")
        result = _run_pg_example(
            tmp_path, "--pg-config", str(config), "--pg-key", "db_server"
        )
        assert f"127.0.0.1:{port} unreachable" in result.stdout

    def test_an_override_of_the_config_applies(self, tmp_path: Path) -> None:
        with _listening() as port:
            config = _pg_config(tmp_path, _closed_port())
            result = _run_pg_example(
                tmp_path,
                "--pg-config",
                str(config),
                env={"INFRA_PGSERVER_PORT": str(port)},
            )
        assert "1 passed, 0 failed" in result.stdout, result.stdout + result.stderr

    def test_a_configured_port_of_zero_is_rejected(self, tmp_path: Path) -> None:
        # A bad port is an error, not a missing endpoint that skips the examples
        config = _pg_config(tmp_path, 0)
        result = _run_pg_example(tmp_path, "--pg-config", str(config))
        assert result.returncode == 2, result.stdout + result.stderr
        assert "port must be 1-65535, got '0'" in result.stderr

    def test_without_an_endpoint_the_example_is_skipped(self, tmp_path: Path) -> None:
        # No config, no INFRA_PGSERVER_PORT: nothing is probed at a guessed port
        result = _run_pg_example(tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "pg-unavailable: no endpoint" in result.stdout
