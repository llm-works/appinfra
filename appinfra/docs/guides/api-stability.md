---
title: API Stability Policy
keywords:
  - versioning
  - semver
  - deprecation
  - breaking changes
  - backwards compatibility
  - migration
aliases:
  - versioning-policy
  - deprecation-policy
---

# API Stability Policy

This document describes appinfra's versioning scheme, API stability guarantees, and deprecation
policy.

## Versioning Scheme

appinfra follows [Semantic Versioning 2.0.0](https://semver.org/) (SemVer):

```
MAJOR.MINOR.PATCH
```

- **MAJOR**: Incompatible API changes
- **MINOR**: New functionality, backward compatible
- **PATCH**: Backward compatible bug fixes

## Current Status: Pre-1.0

**Current Version: 0.x.y**

During pre-1.0 development:

- The API is evolving and may change between minor versions
- Breaking changes may occur in 0.x releases (documented in CHANGELOG)
- We aim to minimize disruption, but stability is not guaranteed
- Production use is supported, but pin your version explicitly

**Recommendation for pre-1.0 users:**

```toml
# pyproject.toml
dependencies = [
    "appinfra==0.1.0",  # Pin exact version during pre-1.0
]
```

## Post-1.0 Stability Guarantees

Once appinfra reaches 1.0, we commit to:

### Public API Definition

The **public API** includes:

- All classes, functions, and constants exported in `__all__`
- All documented parameters and return types
- Command-line interface syntax and behavior
- Configuration file formats (YAML structure)

The **internal API** (not covered by stability guarantees):

- Modules or symbols prefixed with `_`
- Anything not in `__all__` exports
- Implementation details not documented in public docs

### Backward Compatibility

For any 1.x.y release:

| Change Type | Allowed in PATCH | Allowed in MINOR | Allowed in MAJOR |
|-------------|------------------|------------------|------------------|
| Bug fixes | Yes | Yes | Yes |
| New features | No | Yes | Yes |
| Deprecations | No | Yes (with warning) | Yes |
| Breaking changes | No | No | Yes |

### Deprecation Process

When an API needs to be changed or removed:

1. **Deprecation Warning**: The old API continues to work but emits `DeprecationWarning`
2. **Migration Period**: Minimum one minor release cycle (e.g., deprecated in 1.2, removed in 2.0)
3. **Documentation**: Deprecation documented in CHANGELOG with migration instructions
4. **Removal**: Old API removed only in next major version

**Example deprecation:**

```python
from appinfra.deprecation import deprecated


@deprecated(version="1.2.0", replacement="new_function")
def old_function():
    """Use new_function instead."""
    return new_function()
```

**User sees:**

```
DeprecationWarning: old_function is deprecated since version 1.2.0, use new_function instead
```

## How to Handle Deprecation Warnings

### See All Warnings

```python
import warnings

warnings.filterwarnings("default", category=DeprecationWarning, module="appinfra")
```

### Treat Warnings as Errors (CI)

```python
import warnings

warnings.filterwarnings("error", category=DeprecationWarning, module="appinfra")
```

### Suppress Warnings (temporarily)

```python
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning, module="appinfra")
```

## Version Support Policy

| Version | Status | Support |
|---------|--------|---------|
| Latest MAJOR.x | Active | Full support, new features |
| Previous MAJOR.x | Maintenance | Security fixes only, 12 months |
| Older versions | End of life | No support |

## Breaking Change Communication

All breaking changes are:

1. **Announced** in release notes before the release
2. **Documented** in CHANGELOG.md with migration guide
3. **Warned** via deprecation warnings at least one minor version before removal

## Python Version Support

appinfra supports Python versions that are not end-of-life:

| Python Version | appinfra Support |
|----------------|------------------|
| 3.11+ | Fully supported |
| 3.10 and below | Not supported |

When a Python version reaches end-of-life, support may be dropped in the next minor release.

## Reporting API Issues

If you encounter unexpected behavior or breaking changes:

1. Check the [CHANGELOG](../CHANGELOG.md) for documented changes
2. Search existing [GitHub Issues](https://github.com/your-org/appinfra/issues)
3. Open a new issue with:
   - appinfra version
   - Python version
   - Minimal reproduction code
   - Expected vs actual behavior

## Summary

| Phase | API Stability | Breaking Changes | Deprecation Period |
|-------|---------------|------------------|-------------------|
| 0.x (pre-1.0) | Evolving | May occur in minor | Best effort |
| 1.x+ | Stable | Major versions only | 1+ minor release |

**Key takeaways:**

- Pre-1.0: Pin exact versions, expect some changes
- Post-1.0: Semantic versioning strictly followed
- Deprecations always warned before removal
- Check CHANGELOG.md before upgrading
