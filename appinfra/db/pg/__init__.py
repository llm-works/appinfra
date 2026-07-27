from .ensure import ensure_object, index_exists, table_exists, with_object_lock
from .interface import Interface
from .pg import PG, ScopedPG
from .schema import SchemaManager, create_all_in_schema, validate_schema_name
from .vector import create_vector_index, enable_pgvector

__all__ = [
    "PG",
    "ScopedPG",
    "Interface",
    "Vector",
    "enable_pgvector",
    "create_vector_index",
    "SchemaManager",
    "create_all_in_schema",
    "validate_schema_name",
    "with_object_lock",
    "ensure_object",
    "table_exists",
    "index_exists",
]


def __getattr__(name: str) -> object:
    """Defer `Vector` resolution so importing appinfra.db.pg does not pull
    in pgvector/numpy for consumers that never touch vector features."""
    if name == "Vector":
        from .vector import Vector

        globals()["Vector"] = Vector
        return Vector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
