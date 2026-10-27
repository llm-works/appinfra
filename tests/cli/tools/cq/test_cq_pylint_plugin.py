# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the pylint plugin cq dup loads."""

from pathlib import Path
from unittest.mock import MagicMock

import astroid
import pytest
from astroid.builder import AstroidBuilder
from astroid.manager import AstroidManager

from appinfra.cli.tools.cq.pylint_plugin import register

_SOURCE = "import {mod}\n\nobj = {mod}.C()\nobj.x = 1\n"


def _built_after_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mod: str
) -> bool:
    """Parse code that sets an attribute on an object from mod; report whether mod got built."""
    (tmp_path / f"{mod}.py").write_text("class C:\n    pass\n")
    monkeypatch.syspath_prepend(tmp_path)
    cache = AstroidManager().astroid_cache
    try:
        astroid.parse(_SOURCE.format(mod=mod))
        return mod in cache
    finally:
        cache.pop(mod, None)


@pytest.mark.unit
class TestPylintPlugin:
    """register() turns off astroid's attribute inference."""

    def test_attribute_assignment_builds_its_module_without_plugin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        assert _built_after_parse(tmp_path, monkeypatch, "cq_plugin_dep_plain")

    def test_attribute_assignment_leaves_its_module_unbuilt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            AstroidBuilder, "delayed_assattr", AstroidBuilder.delayed_assattr
        )
        register(MagicMock())
        assert not _built_after_parse(tmp_path, monkeypatch, "cq_plugin_dep_patched")

    def test_fails_when_astroid_lacks_the_method(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delattr(AstroidBuilder, "delayed_assattr")
        with pytest.raises(RuntimeError, match="delayed_assattr"):
            register(MagicMock())
