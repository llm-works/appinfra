"""
pgvector support for PostgreSQL.

Provides utilities for working with vector embeddings in PostgreSQL using
the pgvector extension. Includes type wrapper, extension enabler, and
index creation helpers.

Example:
    from appinfra.db.pg.vector import Vector, enable_pgvector, create_vector_index

    # Model definition
    class Content(Base):
        __tablename__ = "content"
        id = Column(Integer, primary_key=True)
        embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)

    # Migration helper
    def upgrade():
        op.execute(enable_pgvector())
        op.execute(create_vector_index(
            table="content",
            column="embedding",
            method="ivfflat",
            ops="vector_cosine_ops",
            lists=100,
        ))
"""

from typing import Literal


def __getattr__(name: str) -> object:
    """Lazily resolve `Vector` so importing this module does not pull in
    pgvector (and its numpy dependency). Returns None if pgvector is not
    installed, matching the previous eager-import fallback."""
    if name == "Vector":
        try:
            from pgvector.sqlalchemy import Vector as _Vector
        except ImportError:
            return None
        return _Vector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def enable_pgvector() -> str:
    """
    Return SQL to enable the pgvector extension.

    Returns:
        SQL string to create the vector extension if not exists.

    Example:
        op.execute(enable_pgvector())
    """
    return "CREATE EXTENSION IF NOT EXISTS vector"


def create_vector_index(
    table: str,
    column: str,
    method: Literal["ivfflat", "hnsw"] = "ivfflat",
    ops: str = "vector_cosine_ops",
    lists: int = 100,
    m: int = 16,
    ef_construction: int = 64,
    index_name: str | None = None,
) -> str:
    """
    Generate SQL for creating a vector index.

    Args:
        table: Table name containing the vector column.
        column: Column name with vector data.
        method: Index method - "ivfflat" or "hnsw".
        ops: Distance operator class. Options:
            - vector_l2_ops: Euclidean distance
            - vector_ip_ops: Inner product
            - vector_cosine_ops: Cosine distance (most common for embeddings)
        lists: Number of lists for IVFFlat (default 100). Higher = slower build,
            faster search. Rule of thumb: sqrt(row_count) for up to 1M rows.
        m: Max connections per layer for HNSW (default 16). Higher = better
            recall but more memory.
        ef_construction: Size of dynamic candidate list for HNSW (default 64).
            Higher = better recall but slower build.
        index_name: Custom index name. Defaults to idx_{table}_{column}.

    Returns:
        SQL string to create the vector index.

    Example:
        # IVFFlat index for cosine similarity
        sql = create_vector_index(
            table="content",
            column="embedding",
            method="ivfflat",
            ops="vector_cosine_ops",
            lists=100,
        )

        # HNSW index for better search performance
        sql = create_vector_index(
            table="documents",
            column="embedding",
            method="hnsw",
            ops="vector_cosine_ops",
            m=32,
            ef_construction=128,
        )
    """
    if index_name is None:
        index_name = f"idx_{table}_{column}"

    if method == "ivfflat":
        return (
            f"CREATE INDEX {index_name} ON {table} "
            f"USING ivfflat ({column} {ops}) "
            f"WITH (lists = {lists})"
        )
    elif method == "hnsw":
        return (
            f"CREATE INDEX {index_name} ON {table} "
            f"USING hnsw ({column} {ops}) "
            f"WITH (m = {m}, ef_construction = {ef_construction})"
        )
    else:
        raise ValueError(f"Unknown index method: {method}. Use 'ivfflat' or 'hnsw'.")
