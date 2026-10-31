#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Install, reinstall or uninstall the project package in each Python environment.

Run by `make install`, `install.e`, `uninstall` and `reinstall` (Makefile.install) with
the project interpreter; each ENV is an interpreter path, one that is not executable is
skipped.

`install` builds a wheel per env (C-extension or version-specific wheels stay valid for
their target), installs it, and publishes a copy to <sys.prefix>/share/<pkg>/wheels/.
share/'s mode bits (perm + setuid/setgid/sticky) become the mode of the directories
created under it, and masked to 0666 the mode of the wheel, whatever the caller's umask.

share/ must exist, except in a virtualenv (sys.prefix != sys.base_prefix), where a
missing share/ is created 0755. Elsewhere, e.g. a system interpreter's /usr, the
install is refused. Every env is checked before any is changed: a refused env leaves
all of them as they were, and `reinstall` uninstalls nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PROBE = "import json, sys; print(json.dumps([sys.prefix, sys.base_prefix]))"
VENV_SHARE_MODE = 0o755
BUILD_ARTIFACTS = (".dist", ".build", "dist", "build")
# PEP 503 distribution name: it becomes a path component under share/
PKG_NAME = re.compile(r"[A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]")


class RefusedError(Exception):
    """An env cannot be installed to; nothing has been changed."""


@dataclass(frozen=True)
class Env:
    """An interpreter, its sys.prefix, and whether that prefix is a virtualenv."""

    python: str
    prefix: Path
    venv: bool

    @property
    def share(self) -> Path:
        """<sys.prefix>/share."""
        return self.prefix / "share"

    def wheels(self, pkg: str) -> Path:
        """Where the package's wheel is published."""
        return self.share / pkg / "wheels"


def probe(python: str) -> Env:
    """The env's prefix, and whether it is a virtualenv."""
    out = subprocess.run(
        [python, "-c", PROBE], check=True, capture_output=True, text=True
    ).stdout
    prefix, base_prefix = json.loads(out)
    if not prefix:
        raise RefusedError(f"ERROR: {python} reported empty sys.prefix")
    return Env(python, Path(prefix), prefix != base_prefix)


def resolve(pythons: list[str]) -> list[Env]:
    """The envs to act on, in order; interpreters that are not executable are skipped."""
    envs = []
    for python in pythons:
        if os.path.isfile(python) and os.access(python, os.X_OK):
            envs.append(probe(python))
        else:
            print(f"  → {python} (skipped, not found)")
    return envs


def preflight(envs: list[Env]) -> None:
    """Refuse unless every env can take the wheel: share/ exists or a venv gets one."""
    for env in envs:
        if env.share.is_dir() or env.venv:
            continue
        raise RefusedError(
            f"ERROR: {env.share} does not exist\n"
            f"refusing to install: {env.prefix} is not a virtualenv, and share/ is"
            " created only inside one.\n"
            "create it manually with the desired permissions, e.g.:\n"
            f"  mkdir -p '{env.share}' && chmod 0755 '{env.share}'\n"
            "note: share/'s mode becomes the policy for all published wheels.\n"
            "then re-run 'make install'."
        )


def share_modes(share: Path) -> tuple[int, int]:
    """Modes for directories and for the wheel published under share/."""
    mode = stat.S_IMODE(os.stat(share).st_mode)
    return mode, mode & 0o666


def pip(env: Env, *args: str) -> None:
    """Run pip with the env's interpreter; a failure raises CalledProcessError."""
    subprocess.run([env.python, "-m", "pip", *args], check=True)


def with_extras(target: str, extras: str) -> str:
    """A pip install target with its extras, e.g. `x.whl[ui,dev]`."""
    return f"{target}[{extras}]" if extras else target


def clean_build() -> None:
    """Remove build artifacts of earlier builds from the project directory."""
    print("* cleaning build artifacts...")
    for path in [*Path().glob("*.egg-info"), *map(Path, BUILD_ARTIFACTS)]:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()


def build_wheel(env: Env) -> Path:
    """Build the project's wheel with the env's interpreter; the newest in dist/."""
    print("    building wheel...")
    pip(env, "wheel", ".", "--no-deps", "-q", "-w", "dist/")
    wheels = list(Path("dist").glob("*.whl"))
    if not wheels:
        raise RefusedError("ERROR: pip wheel produced no .whl")
    wheel = max(wheels, key=lambda w: w.stat().st_mtime)
    print(f"    built {wheel}")
    return wheel


def _make_dir(path: Path, mode: int) -> None:
    """Create path if missing and set its mode, as `install -d -m` does."""
    path.mkdir(exist_ok=True)
    os.chmod(path, mode)


def publish(env: Env, pkg: str, wheel: Path) -> None:
    """Copy the wheel to share/<pkg>/wheels/ with share/'s modes; drop older wheels."""
    dir_mode, file_mode = share_modes(env.share)
    _make_dir(env.share / pkg, dir_mode)
    wheels = env.wheels(pkg)
    _make_dir(wheels, dir_mode)
    dest = wheels / wheel.name
    shutil.copyfile(wheel, dest)
    os.chmod(dest, file_mode)
    for old in wheels.glob("*.whl"):
        if old.name != wheel.name:
            old.unlink()
    print(f"    wheel → {dest} (mode 0{file_mode:o})")


def install_env(env: Env, pkg: str, extras: str) -> None:
    """Build, install and publish the wheel for one env."""
    print(f"  → {env.python}")
    if not env.share.is_dir():
        _make_dir(env.share, VENV_SHARE_MODE)  # preflight admits this only for a venv
        print(f"    created {env.share} (mode 0{VENV_SHARE_MODE:o})")
    wheel = build_wheel(env)
    pip(env, "install", "-q", with_extras(str(wheel), extras))
    publish(env, pkg, wheel)


def install(envs: list[Env], pkg: str, extras: str) -> None:
    """Install the package's wheel to every env, once all of them can take it."""
    preflight(envs)
    clean_build()
    print(f"* installing {pkg} to all environments...")
    for env in envs:
        install_env(env, pkg, extras)
    print("* install done")


def install_editable(envs: list[Env], pkg: str, extras: str) -> None:
    """Install the package editable to every env; a published wheel would be stale."""
    clean_build()
    print(f"* installing {pkg} (editable) to all environments...")
    for env in envs:
        print(f"  → {env.python}")
        pip(env, "install", "-q", "-e", with_extras(".", extras))
        shutil.rmtree(env.wheels(pkg), ignore_errors=True)
    print("* install.e done")


def uninstall(envs: list[Env], pkg: str) -> None:
    """Uninstall the package from every env and remove its published wheel."""
    print(f"* uninstalling {pkg} from all environments...")
    for env in envs:
        print(f"  → {env.python}")
        cmd = [env.python, "-m", "pip", "uninstall", "-q", "-y", pkg]
        subprocess.run(cmd, check=False, stderr=subprocess.DEVNULL)
        shutil.rmtree(env.wheels(pkg), ignore_errors=True)
    print("* uninstall done")


def reinstall(envs: list[Env], pkg: str, extras: str) -> None:
    """Uninstall then install, once every env is known to take the new wheel."""
    preflight(envs)
    uninstall(envs, pkg)
    install(envs, pkg, extras)


def run(action: str, envs: list[Env], pkg: str, extras: str) -> None:
    """Dispatch the action."""
    if action == "install":
        install(envs, pkg, extras)
    elif action == "install-e":
        install_editable(envs, pkg, extras)
    elif action == "uninstall":
        uninstall(envs, pkg)
    else:
        reinstall(envs, pkg, extras)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the command line; --pkg must be a PEP 503 name, as it becomes a path."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "action", choices=["install", "install-e", "uninstall", "reinstall"]
    )
    parser.add_argument("--pkg", required=True, help="distribution name")
    parser.add_argument("--extras", default="", help="comma-separated extras")
    parser.add_argument("envs", nargs="*", metavar="ENV", help="interpreter paths")
    args = parser.parse_args(argv)
    if not PKG_NAME.fullmatch(args.pkg):
        parser.error(f"--pkg {args.pkg!r} is not a PEP 503 distribution name")
    return args


def main(argv: list[str]) -> int:
    """Run the action; 1 when an env is refused or a command fails."""
    args = parse_args(argv)
    try:
        run(args.action, resolve(args.envs), args.pkg, args.extras)
    except RefusedError as e:
        print("    " + str(e).replace("\n", "\n    "), file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(
            f"    ERROR: {' '.join(map(str, e.cmd))} failed ({e.returncode})",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
