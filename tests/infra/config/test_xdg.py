# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.config.xdg — XDG Base Directory helpers."""

from pathlib import Path

import pytest

from appinfra.config import xdg_candidates


@pytest.fixture
def clean_xdg_env(monkeypatch):
    """Ensure no XDG_* env vars leak in from the host."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_DIRS", raising=False)


@pytest.mark.unit
class TestXdgCandidatesDefaults:
    """Behavior when XDG_CONFIG_HOME / XDG_CONFIG_DIRS are unset."""

    def test_defaults_use_spec_fallbacks(self, clean_xdg_env):
        candidates = xdg_candidates("llm-works", "llm-kelt")
        home = Path.home() / ".config"
        assert candidates == [
            home / "llm-works" / "llm-kelt.yaml",
            home / "llm-works" / "config.yaml",
            Path("/etc/xdg") / "llm-works" / "llm-kelt.yaml",
            Path("/etc/xdg") / "llm-works" / "config.yaml",
        ]

    def test_empty_env_values_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "")
        monkeypatch.setenv("XDG_CONFIG_DIRS", "")
        candidates = xdg_candidates("ns", "pkg")
        assert candidates[0].parent.parent == Path.home() / ".config"
        assert candidates[2].parent.parent == Path("/etc/xdg")


@pytest.mark.unit
class TestXdgCandidatesEnvOverrides:
    """Behavior when XDG env vars are set."""

    def test_home_override_only(self, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "/custom/home")
        monkeypatch.delenv("XDG_CONFIG_DIRS", raising=False)
        candidates = xdg_candidates("ns", "pkg")
        assert candidates[0] == Path("/custom/home/ns/pkg.yaml")
        assert candidates[1] == Path("/custom/home/ns/config.yaml")
        assert candidates[2] == Path("/etc/xdg/ns/pkg.yaml")

    def test_dirs_override_only(self, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("XDG_CONFIG_DIRS", "/a:/b")
        candidates = xdg_candidates("ns", "pkg")
        home = Path.home() / ".config"
        assert candidates == [
            home / "ns" / "pkg.yaml",
            home / "ns" / "config.yaml",
            Path("/a/ns/pkg.yaml"),
            Path("/a/ns/config.yaml"),
            Path("/b/ns/pkg.yaml"),
            Path("/b/ns/config.yaml"),
        ]

    def test_both_overrides(self, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "/h")
        monkeypatch.setenv("XDG_CONFIG_DIRS", "/s1:/s2")
        candidates = xdg_candidates("ns", "pkg")
        assert [c.parent.parent for c in candidates] == [
            Path("/h"),
            Path("/h"),
            Path("/s1"),
            Path("/s1"),
            Path("/s2"),
            Path("/s2"),
        ]


@pytest.mark.unit
class TestXdgCandidatesSkippedEntries:
    """Malformed XDG_CONFIG_DIRS entries per XDG spec."""

    def test_empty_entries_skipped(self, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "/h")
        monkeypatch.setenv("XDG_CONFIG_DIRS", ":/a::/b:")
        candidates = xdg_candidates("ns", "pkg")
        dirs = [c.parent.parent for c in candidates]
        assert dirs == [
            Path("/h"),
            Path("/h"),
            Path("/a"),
            Path("/a"),
            Path("/b"),
            Path("/b"),
        ]

    def test_relative_entries_skipped(self, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "/h")
        monkeypatch.setenv("XDG_CONFIG_DIRS", "relative:/abs:./also-relative")
        candidates = xdg_candidates("ns", "pkg")
        dirs = [c.parent.parent for c in candidates]
        assert dirs == [Path("/h"), Path("/h"), Path("/abs"), Path("/abs")]


@pytest.mark.unit
class TestXdgCandidatesOrdering:
    """Order invariants: home before system; per-package before unified per dir."""

    def test_home_before_system(self, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "/h")
        monkeypatch.setenv("XDG_CONFIG_DIRS", "/s")
        candidates = xdg_candidates("ns", "pkg")
        assert candidates[0].is_relative_to("/h")
        assert candidates[-1].is_relative_to("/s")

    def test_per_package_before_unified_per_dir(self, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "/h")
        monkeypatch.setenv("XDG_CONFIG_DIRS", "/s")
        candidates = xdg_candidates("ns", "pkg")
        assert candidates[0].name == "pkg.yaml"
        assert candidates[1].name == "config.yaml"
        assert candidates[2].name == "pkg.yaml"
        assert candidates[3].name == "config.yaml"


@pytest.mark.unit
class TestXdgCandidatesInterpolation:
    """Namespace and package strings appear verbatim in the paths."""

    def test_namespace_and_package_appear_in_paths(self, clean_xdg_env):
        candidates = xdg_candidates("my-ns", "my-pkg")
        for c in candidates:
            assert c.parent.name == "my-ns"
        assert candidates[0].name == "my-pkg.yaml"
        assert candidates[1].name == "config.yaml"

    def test_no_filesystem_probing(self, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "/nonexistent/path")
        monkeypatch.setenv("XDG_CONFIG_DIRS", "/also/does/not/exist")
        candidates = xdg_candidates("ns", "pkg")
        assert len(candidates) == 4
        for c in candidates:
            assert not c.exists()
