# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests that importing appinfra.db defers pgvector and numpy until Vector is used.
"""

import subprocess
import sys
import textwrap


class TestDeferredPgvectorImport:
    """Regression: importing appinfra.db must not pull pgvector or numpy.

    Runs in a subprocess to get a clean sys.modules — otherwise other tests
    in the session will have already imported these transitively.
    """

    def _probe(self, import_stmt: str) -> set[str]:
        """Return the set of pgvector/numpy modules loaded after `import_stmt`."""
        script = textwrap.dedent(
            f"""
            import sys
            before = set(sys.modules)
            {import_stmt}
            after = set(sys.modules)
            leaked = sorted(
                m for m in (after - before)
                if m == "pgvector" or m.startswith("pgvector.")
                or m == "numpy" or m.startswith("numpy.")
            )
            for m in leaked:
                print(m)
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
        )
        return set(result.stdout.split()) if result.stdout.strip() else set()

    def test_db_utils_import_does_not_load_pgvector(self):
        """`from appinfra.db.utils import detach` must not import pgvector/numpy."""
        leaked = self._probe("from appinfra.db.utils import detach  # noqa: F401")
        assert leaked == set(), (
            f"Importing appinfra.db.utils leaked heavy modules: {sorted(leaked)}"
        )

    def test_db_pg_package_import_does_not_load_pgvector(self):
        """`import appinfra.db.pg` must not import pgvector/numpy."""
        leaked = self._probe("import appinfra.db.pg  # noqa: F401")
        assert leaked == set(), (
            f"Importing appinfra.db.pg leaked heavy modules: {sorted(leaked)}"
        )

    def test_vector_module_import_does_not_load_pgvector(self):
        """Importing the vector module for its helpers must not load pgvector."""
        leaked = self._probe(
            "from appinfra.db.pg.vector import enable_pgvector  # noqa: F401"
        )
        assert leaked == set(), (
            f"Importing appinfra.db.pg.vector leaked heavy modules: {sorted(leaked)}"
        )

    def test_vector_attribute_access_loads_pgvector(self):
        """Accessing `Vector` explicitly IS allowed to load pgvector."""
        script = textwrap.dedent(
            """
            import sys
            import appinfra.db.pg.vector as v
            assert "pgvector.sqlalchemy" not in sys.modules, (
                "pgvector was loaded before attribute access"
            )
            _ = v.Vector  # triggers __getattr__
            # Either pgvector is now loaded (installed) or Vector is None (not installed)
            if v.Vector is not None:
                assert "pgvector.sqlalchemy" in sys.modules
            print("ok")
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == "ok", result.stderr
