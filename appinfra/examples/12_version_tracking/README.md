# Version Tracking Examples

Demonstrates the commit hash tracking framework for monitoring git commit
information of installed packages.

## Examples

### 1. `standalone_tracker.py`

Shows how to use `PackageVersionTracker` directly without the AppBuilder
framework. Useful for libraries or simple scripts.

```bash
python standalone_tracker.py
```

Output:
```
============================================================
Standalone Package Version Tracker Demo
============================================================

1. Tracking specific packages...
   Tracked 3 packages

2. Package information:
------------------------------------------------------------
   appinfra        0.1.0        e0b1216
      Source: editable-git
   pip             24.0         (no commit info)
      Source: pip
...
```

### 2. `version_tracking_demo.py`

Full CLI application using AppBuilder with version tracking integration.
Shows startup logging and tool integration.

```bash
# Show help
python version_tracking_demo.py --help

# List tracked packages
python version_tracking_demo.py list

# Show detailed info
python version_tracking_demo.py info
```

## How It Works

The framework detects commit hashes from three sources (in order):

1. **Build Info** (`_build_info.py`) - Generated via git hook, committed to source
2. **PEP 610** (`direct_url.json`) - For `pip install git+https://...`
3. **Git Runtime** - Runs `git rev-parse HEAD` for editable installs

## AppBuilder Integration

```python
from appinfra.app import AppBuilder

# Track this repo's build info + external packages
app = (
    AppBuilder("myapp")
    .version.with_semver("1.0.0")
    .with_build_info()  # reads _build_info.py from CWD
    .with_package("mylib")  # track specific external packages
    .with_package("otherlib")
    .done()
    .build()
)

# Just build info for this repo (no external packages)
app = AppBuilder("myapp").version.with_semver("1.0.0").with_build_info().done().build()
```

## Standalone Usage

```python
from appinfra.version import PackageVersionTracker

tracker = PackageVersionTracker()
tracker.track("mylib", "appinfra")

for name, info in tracker.get_all().items():
    print(f"{name}: {info.version} @ {info.commit}")
```

## Generating _build_info.py

The `_build_info.py` file is populated automatically:

1. **During pip install**: Setuptools hook generates it with current git info
2. **During CI/CD**: Run manually before building the wheel:
   ```bash
   python -m appinfra.version.build_info mypackage/
   ```

The source repo keeps a stub `_build_info.py` with empty values. Runtime
detection via `git status` works for editable installs.

For packages that use appinfra, add it to build dependencies:
```toml
[build-system]
requires = ["setuptools>=68.0", "wheel", "appinfra"]
build-backend = "setuptools.build_meta"
```
