# Version Tracking

Track git commit hashes of installed packages for debugging and deployment verification.

## Overview

The version module provides tools to:

- Track commit hashes of pip-installed packages
- Detect versions from multiple sources (build info, PEP 610, git runtime)
- Display version info at startup and via `--version`
- Extract fields programmatically for scripting

## Quick Start

### CLI Usage

```bash
# Show version with commit hash
appinfra version
# Output: appinfra 0.1.0 (abc123f)

# Extract specific fields
appinfra version semver    # 0.1.0
appinfra version commit    # abc123f
appinfra version full      # abc123def456789...
appinfra version modified  # true/false/unknown

# JSON output
appinfra version --json
```

### Programmatic Usage

```python
from appinfra.version import PackageVersionTracker

tracker = PackageVersionTracker()
tracker.track("mylib", "otherlib")

for name, info in tracker.get_all().items():
    print(f"{name}: {info.version} @ {info.commit}")
```

### AppBuilder Integration

```python
from appinfra.app.builder import AppBuilder

app = (
    AppBuilder("myapp")
    .version.with_semver("1.0.0")
    .with_build_info()  # Include commit from _build_info.py
    .with_package("mylib")  # Track dependency
    .done()  # Startup logging enabled by default
    .build()
)

# To disable startup logging:
app = (
    AppBuilder("myapp")
    .version.with_semver("1.0.0")
    .with_build_info()
    .without_startup_log()  # Disable version logging at startup
    .done()
    .build()
)
```

## Version Sources

The tracker uses a chain of sources to detect commit information:

| Source | Priority | Description |
|--------|----------|-------------|
| `BuildInfoSource` | 1st | Reads `_build_info.py` generated at build time |
| `PEP610Source` | 2nd | Reads `direct_url.json` from `pip install git+...` |
| `GitRuntimeSource` | 3rd | Runs `git rev-parse HEAD` for editable installs |

### Build Info Source

When packages are installed via `pip install` (non-editable), a `_build_info.py` file is generated
containing the commit hash at build time:

```python
# _build_info.py (auto-generated)
COMMIT_HASH = "abc123def456789..."
COMMIT_SHORT = "abc123d"
COMMIT_MESSAGE = "feat: add feature"
BUILD_TIME = "2025-12-01T10:30:00Z"
MODIFIED = False
```

### PEP 610 Source

For packages installed directly from git:

```bash
pip install git+https://github.com/org/mylib.git@main
```

Pip creates `direct_url.json` with commit info that this source reads.

### Git Runtime Source

For editable installs (`pip install -e .`), runs git commands in the package directory to get the
current commit.

## API Reference

### PackageVersionTracker

Main class for tracking package versions.

```python
class PackageVersionTracker:
    def track(self, *packages: str) -> None:
        """Add packages to track."""

    def get(self, name: str) -> PackageVersionInfo | None:
        """Get version info for a specific package."""

    def get_all(self) -> dict[str, PackageVersionInfo]:
        """Get all tracked package versions."""

    def format_for_log(self) -> str:
        """Format versions for log output."""

    def format_for_version(self, app_version: str) -> str:
        """Format for --version display."""
```

### PackageVersionInfo

Dataclass containing version information for a package.

```python
@dataclass
class PackageVersionInfo:
    name: str  # Package name
    version: str  # Semantic version (e.g., "1.0.0")
    commit: str | None  # Short commit hash (e.g., "abc123f")
    commit_full: str | None  # Full commit hash
    source_url: str | None  # Git URL if available
    source_type: str  # "build-info" | "pip-git" | "editable-git" | "pip"
```

### BuildInfo

Dataclass for build-time information.

```python
@dataclass
class BuildInfo:
    commit: str | None  # Short commit hash
    commit_full: str | None  # Full commit hash
    message: str | None  # Commit message
    time: str | None  # Build timestamp (ISO 8601)
    modified: bool | None  # True if working directory was dirty
```

## Downstream Project Setup

Projects using appinfra can adopt the same version tracking protocol. The `init-hook` command
generates
a self-contained setup.py that works with standard `pip install .` (PEP 517 build isolation).

### Quick Setup (Recommended)

```bash
# Generate setup.py and stub file
cd myproject
appinfra version init-hook mypackage --output setup.py --with-stub

# Commit both files to git
git add setup.py mypackage/_build_info.py
git commit -m "Add version tracking"

# Now pip install works normally
pip install .
```

### Manual Setup

#### Step 1: Generate standalone setup.py

```bash
appinfra version init-hook mypackage --output setup.py
```

This generates a self-contained `setup.py` with no appinfra imports - it works with standard
`pip install .` and PEP 517 build isolation.

#### Step 2: Create stub `_build_info.py`

Create `mypackage/_build_info.py` with stub values (committed to git):

```python
"""Build information - auto-generated during install, do not edit."""

# Stub values - populated during pip install by setup.py hook
COMMIT_HASH = ""
COMMIT_SHORT = ""
COMMIT_MESSAGE = ""
BUILD_TIME = ""
MODIFIED = None
```

Or generate with:

```bash
appinfra version init-hook mypackage --with-stub
# Or: python -c "from appinfra.version import get_stub_content; print(get_stub_content())"
```

### How it works

1. The stub `_build_info.py` is committed to git with empty values
2. During `pip install`, the `build_py` hook runs
3. The hook writes populated values to the **build directory** (not source)
4. Your source repo stays clean - only the installed package has commit info

### Verify it works

```bash
# Install your package
pip install .

# Check the installed build info
python -c "from mypackage._build_info import COMMIT_SHORT; print(COMMIT_SHORT)"
# Output: abc123f
```

### Alternative: Import-based approach

If appinfra is available in your build environment (e.g., with `--no-build-isolation`), you can use
the shorter import-based approach:

```python
# setup.py - requires appinfra in build environment
from appinfra.version import make_build_py_class
from setuptools import setup

setup(cmdclass={"build_py": make_build_py_class("mypackage")})
```

**Note:** This approach fails with standard `pip install .` due to PEP 517 build isolation.
Use `pip install --no-build-isolation .` or prefer the `init-hook` approach above.

### Using with appinfra version tracking

Once set up, your package works with `PackageVersionTracker`:

```python
from appinfra.version import PackageVersionTracker

tracker = PackageVersionTracker()
tracker.track("mypackage")

info = tracker.get("mypackage")
print(f"{info.name}: {info.version} @ {info.commit}")
```

## Output Examples

### Startup Log

```
INFO  *** start *** prog_args="myapp run" cwd="/app"
INFO  package versions: mylib=1.2.0@abc123f otherlib=2.0.0@def456a
```

### --version Flag

```
myapp 1.0.0 (abc123f)

Tracked packages:
  mylib     1.2.0 @ abc123f (git+https://github.com/org/mylib)
  otherlib  2.0.0 @ def456a (git+https://github.com/org/otherlib)
```

### JSON Output

```json
{
  "semver": "1.0.0",
  "commit": "abc123f",
  "full": "abc123def456789012345678901234567890abcd",
  "message": "feat: add feature",
  "time": "2025-12-01T10:30:00Z",
  "modified": false
}
```

## See Also

- [AppBuilder](app-builder.md) - Application builder with version configurer
- [Getting Started](../getting-started.md#version-information) - CLI version command examples
