# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for pgvector support module.
"""

import pytest

from appinfra.db.pg.vector import create_vector_index, enable_pgvector


class TestEnablePgvector:
    """Test enable_pgvector function."""

    def test_returns_create_extension_sql(self):
        """Test returns correct SQL for enabling pgvector."""
        sql = enable_pgvector()
        assert sql == "CREATE EXTENSION IF NOT EXISTS vector"


class TestCreateVectorIndex:
    """Test create_vector_index function."""

    def test_ivfflat_index_default(self):
        """Test IVFFlat index with default options."""
        sql = create_vector_index(
            table="content",
            column="embedding",
        )
        assert "CREATE INDEX idx_content_embedding ON content" in sql
        assert "USING ivfflat" in sql
        assert "vector_cosine_ops" in sql
        assert "lists = 100" in sql

    def test_ivfflat_index_custom_options(self):
        """Test IVFFlat index with custom options."""
        sql = create_vector_index(
            table="documents",
            column="vectors",
            method="ivfflat",
            ops="vector_l2_ops",
            lists=200,
        )
        assert "idx_documents_vectors" in sql
        assert "USING ivfflat" in sql
        assert "vector_l2_ops" in sql
        assert "lists = 200" in sql

    def test_hnsw_index(self):
        """Test HNSW index generation."""
        sql = create_vector_index(
            table="embeddings",
            column="vector",
            method="hnsw",
            ops="vector_ip_ops",
            m=32,
            ef_construction=128,
        )
        assert "idx_embeddings_vector" in sql
        assert "USING hnsw" in sql
        assert "vector_ip_ops" in sql
        assert "m = 32" in sql
        assert "ef_construction = 128" in sql

    def test_custom_index_name(self):
        """Test custom index name."""
        sql = create_vector_index(
            table="content",
            column="embedding",
            index_name="my_custom_index",
        )
        assert "CREATE INDEX my_custom_index ON content" in sql

    def test_invalid_method_raises(self):
        """Test invalid method raises ValueError."""
        with pytest.raises(ValueError, match="Unknown index method"):
            create_vector_index(
                table="content",
                column="embedding",
                method="invalid",  # type: ignore[arg-type]
            )

    def test_hnsw_default_values(self):
        """Test HNSW uses correct default values."""
        sql = create_vector_index(
            table="content",
            column="embedding",
            method="hnsw",
        )
        assert "m = 16" in sql
        assert "ef_construction = 64" in sql


class TestVectorImport:
    """Test Vector type import."""

    def test_vector_import(self):
        """Test Vector can be imported (may be None if pgvector not installed)."""
        from appinfra.db.pg.vector import Vector

        # Vector is either the pgvector type or None
        # We can't assume pgvector is installed in test environment
        assert Vector is None or hasattr(Vector, "__call__")

    def test_vector_available_via_pg_package(self):
        """Vector resolves to the same object when accessed via appinfra.db.pg."""
        from appinfra.db.pg import Vector as VectorFromPg
        from appinfra.db.pg.vector import Vector as VectorFromModule

        assert VectorFromPg is VectorFromModule
