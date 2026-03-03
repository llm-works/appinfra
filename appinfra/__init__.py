from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

# Lazy imports for heavy modules (db, net) - only loaded when accessed
# This reduces CLI startup time from ~1s to ~100ms
if TYPE_CHECKING:
    from . import db, net

from .config import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_CONFIG_FILENAME,
    ETC_DIR,
    PROJECT_ROOT,
    Config,
    get_config_file_path,
    get_default_config,
    get_etc_dir,
    get_project_root,
)
from .deprecation import deprecated
from .dict import DictInterface
from .dot_dict import DotDict
from .errors import (
    ConfigError,
    DatabaseError,
    DependencyError,
    InfraError,
    LoggingError,
    ObservabilityError,
    ServerError,
    ToolError,
    ValidationError,
)
from .ewma import EWMA
from .field_dict import FieldDict, field
from .rate_limit import Backoff, RateLimiter
from .regex_utils import (
    RegexComplexityError,
    RegexTimeoutError,
    safe_compile,
    safe_findall,
    safe_match,
    safe_search,
)
from .size import InvalidSizeError, size_str, size_to_bytes, validate_size
from .utils import is_int, pretty

# Version is read from package metadata (pyproject.toml)
try:
    __version__ = version("appinfra")
except PackageNotFoundError:
    # Package not installed, use fallback (development mode)
    __version__ = "0.1.0-dev"

# Explicit public API
__all__ = [
    # Version
    "__version__",
    # Modules
    "db",
    "net",
    # Core classes
    "Backoff",
    "FieldDict",
    "DictInterface",
    "DotDict",
    "field",
    "EWMA",
    "RateLimiter",
    "Config",
    # Config utilities
    "get_project_root",
    "get_etc_dir",
    "get_config_file_path",
    "get_default_config",
    "PROJECT_ROOT",
    "ETC_DIR",
    "DEFAULT_CONFIG_FILE",
    "DEFAULT_CONFIG_FILENAME",
    # Utils
    "pretty",
    "is_int",
    # Deprecation
    "deprecated",
    # Exceptions
    "InfraError",
    "ConfigError",
    "DatabaseError",
    "DependencyError",
    "LoggingError",
    "ValidationError",
    "ToolError",
    "ServerError",
    "ObservabilityError",
    # Regex utilities (ReDoS protection)
    "safe_compile",
    "safe_match",
    "safe_search",
    "safe_findall",
    "RegexTimeoutError",
    "RegexComplexityError",
    # Size formatting
    "size_str",
    "size_to_bytes",
    "validate_size",
    "InvalidSizeError",
]


def __getattr__(name: str) -> object:
    """Lazy import for heavy modules (db, net) to speed up CLI startup."""
    import importlib

    if name in ("db", "net"):
        module = importlib.import_module(f".{name}", __name__)
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
