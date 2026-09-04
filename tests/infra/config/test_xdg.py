# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.config.xdg — XDG Base Directory helpers."""

from pathlib import Path

import pytest

from appinfra.config import (
    include_root_for,
    resolve_config_source,
    xdg_candidates,
)


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

    def test_relative_home_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "relative/path")
        monkeypatch.setenv("XDG_CONFIG_DIRS", "/s")
        candidates = xdg_candidates("ns", "pkg")
        home = Path.home() / ".config"
        assert candidates[0].parent.parent == home
        assert candidates[1].parent.parent == home


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
        def fail_on_exists(self):
            raise AssertionError("xdg_candidates must not probe the filesystem")

        monkeypatch.setattr(Path, "exists", fail_on_exists)
        monkeypatch.setenv("XDG_CONFIG_HOME", "/h")
        monkeypatch.setenv("XDG_CONFIG_DIRS", "/s")
        candidates = xdg_candidates("ns", "pkg")
        assert len(candidates) == 4
        assert candidates[0] == Path("/h/ns/pkg.yaml")


@pytest.mark.unit
class TestIncludeRootFor:
    """`include_root_for(base_config)` returns the base's parent dir."""

    def test_returns_parent_of_base_config(self, tmp_path):
        base = tmp_path / "myapp" / "etc" / "myapp.yaml"
        base.parent.mkdir(parents=True)
        base.write_text("")
        assert include_root_for(base) == (tmp_path / "myapp" / "etc").resolve()

    def test_accepts_string(self, tmp_path):
        base = tmp_path / "etc" / "app.yaml"
        base.parent.mkdir(parents=True)
        base.write_text("")
        assert include_root_for(str(base)) == (tmp_path / "etc").resolve()

    def test_expands_tilde(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        assert include_root_for("~/etc/app.yaml") == (tmp_path / "etc").resolve()

    def test_resolves_symlink(self, tmp_path):
        real_etc = tmp_path / "real" / "etc"
        real_etc.mkdir(parents=True)
        (real_etc / "app.yaml").write_text("")
        link_etc = tmp_path / "link" / "etc"
        link_etc.parent.mkdir()
        link_etc.symlink_to(real_etc)
        assert include_root_for(link_etc / "app.yaml") == real_etc.resolve()


@pytest.mark.unit
class TestResolveConfigSource:
    """`resolve_config_source` walks the v1 precedence chain."""

    @pytest.fixture
    def bundled_base(self, tmp_path):
        base = tmp_path / "pkg" / "etc" / "myapp.yaml"
        base.parent.mkdir(parents=True)
        base.write_text("")
        return base

    def test_custom_etc_dir_wins(self, bundled_base, tmp_path, clean_xdg_env):
        custom = tmp_path / "user_etc"
        custom.mkdir()
        path, root = resolve_config_source(
            "myorg", "myapp", bundled_base, custom_etc_dir=custom
        )
        assert path == custom.resolve() / "myapp.yaml"
        assert root == custom.resolve()

    def test_custom_etc_dir_not_pre_validated(self, bundled_base, tmp_path):
        """Missing file under --etc-dir is not this helper's error to raise."""
        custom = tmp_path / "user_etc"
        custom.mkdir()
        # <custom>/myapp.yaml does not exist; helper still returns the path.
        path, root = resolve_config_source(
            "myorg", "myapp", bundled_base, custom_etc_dir=custom
        )
        assert not path.exists()
        assert root == custom.resolve()

    def test_custom_etc_dir_string_accepted(self, bundled_base, tmp_path):
        custom = tmp_path / "user_etc"
        custom.mkdir()
        path, root = resolve_config_source(
            "myorg", "myapp", bundled_base, custom_etc_dir=str(custom)
        )
        assert path == custom.resolve() / "myapp.yaml"

    def test_custom_etc_dir_expands_tilde(self, bundled_base, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "user_etc").mkdir()
        path, root = resolve_config_source(
            "myorg", "myapp", bundled_base, custom_etc_dir="~/user_etc"
        )
        assert root == (tmp_path / "user_etc").resolve()

    def test_xdg_overlay_when_no_custom(self, bundled_base, monkeypatch, tmp_path):
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        overlay = xdg_home / "myorg" / "myapp.yaml"
        overlay.write_text("")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        monkeypatch.delenv("XDG_CONFIG_DIRS", raising=False)
        path, root = resolve_config_source("myorg", "myapp", bundled_base)
        assert path == overlay
        assert root == bundled_base.parent.resolve()

    def test_fallback_to_bundled_base(self, bundled_base, clean_xdg_env, monkeypatch):
        # Point XDG at empty dirs so no overlay is found.
        monkeypatch.setenv("XDG_CONFIG_HOME", "/nonexistent/home")
        monkeypatch.setenv("XDG_CONFIG_DIRS", "/nonexistent/system")
        path, root = resolve_config_source("myorg", "myapp", bundled_base)
        assert path == bundled_base.resolve()
        assert root == bundled_base.parent.resolve()

    def test_custom_wins_over_existing_xdg(self, bundled_base, monkeypatch, tmp_path):
        """Explicit --etc-dir must not be shadowed by an existing XDG overlay."""
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        (xdg_home / "myorg" / "myapp.yaml").write_text("")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        custom = tmp_path / "user_etc"
        custom.mkdir()
        path, root = resolve_config_source(
            "myorg", "myapp", bundled_base, custom_etc_dir=custom
        )
        assert path == custom.resolve() / "myapp.yaml"
        assert root == custom.resolve()

    def test_per_package_overlay_preferred_over_unified(
        self, bundled_base, monkeypatch, tmp_path
    ):
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        (xdg_home / "myorg" / "myapp.yaml").write_text("")
        (xdg_home / "myorg" / "config.yaml").write_text("")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        monkeypatch.delenv("XDG_CONFIG_DIRS", raising=False)
        path, _ = resolve_config_source("myorg", "myapp", bundled_base)
        assert path.name == "myapp.yaml"

    def test_unified_used_when_per_package_absent(
        self, bundled_base, monkeypatch, tmp_path
    ):
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        (xdg_home / "myorg" / "config.yaml").write_text("")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        monkeypatch.delenv("XDG_CONFIG_DIRS", raising=False)
        path, _ = resolve_config_source("myorg", "myapp", bundled_base)
        assert path.name == "config.yaml"


@pytest.mark.unit
class TestResolveCustomConfig:
    """`--config` override: direct path or bare filename, always bypasses XDG."""

    @pytest.fixture
    def bundled_base(self, tmp_path):
        base = tmp_path / "pkg" / "etc" / "myapp.yaml"
        base.parent.mkdir(parents=True)
        base.write_text("")
        return base

    def test_absolute_path_loaded_directly(self, bundled_base, tmp_path):
        target = tmp_path / "elsewhere" / "custom.yaml"
        target.parent.mkdir()
        target.write_text("")
        path, root = resolve_config_source(
            "myorg", "myapp", bundled_base, custom_config=str(target)
        )
        assert path == target
        assert root == target.parent

    def test_absolute_path_ignores_etc_dir(self, bundled_base, tmp_path):
        target = tmp_path / "elsewhere" / "custom.yaml"
        target.parent.mkdir()
        target.write_text("")
        etc = tmp_path / "user_etc"
        etc.mkdir()
        path, root = resolve_config_source(
            "myorg",
            "myapp",
            bundled_base,
            custom_etc_dir=etc,
            custom_config=str(target),
        )
        assert path == target
        assert root == target.parent

    def test_absolute_path_with_dotdot_is_canonicalized(self, bundled_base, tmp_path):
        """Absolute path with .. segments is resolved to canonical form."""
        target = tmp_path / "elsewhere" / "custom.yaml"
        target.parent.mkdir()
        target.write_text("")
        # Pass non-canonical path: /tmp.../elsewhere/../elsewhere/custom.yaml
        non_canonical = str(tmp_path / "elsewhere" / ".." / "elsewhere" / "custom.yaml")
        path, root = resolve_config_source(
            "myorg", "myapp", bundled_base, custom_config=non_canonical
        )
        assert path == target.resolve()
        assert root == target.parent.resolve()
        # Verify it's actually canonical (no .. in path)
        assert ".." not in str(path)

    def test_explicit_relative_path_resolves_from_cwd(
        self, bundled_base, tmp_path, monkeypatch
    ):
        target = tmp_path / "custom.yaml"
        target.write_text("")
        monkeypatch.chdir(tmp_path)
        path, root = resolve_config_source(
            "myorg", "myapp", bundled_base, custom_config="./custom.yaml"
        )
        assert path == target.resolve()
        assert root == target.resolve().parent

    def test_parent_relative_path_resolves_from_cwd(
        self, bundled_base, tmp_path, monkeypatch
    ):
        target = tmp_path / "custom.yaml"
        target.write_text("")
        sub = tmp_path / "sub"
        sub.mkdir()
        monkeypatch.chdir(sub)
        path, root = resolve_config_source(
            "myorg", "myapp", bundled_base, custom_config="../custom.yaml"
        )
        assert path == target.resolve()
        assert root == target.resolve().parent

    def test_bare_filename_composes_with_etc_dir(self, bundled_base, tmp_path):
        etc = tmp_path / "user_etc"
        etc.mkdir()
        path, root = resolve_config_source(
            "myorg",
            "myapp",
            bundled_base,
            custom_etc_dir=etc,
            custom_config="alt.yaml",
        )
        assert path == etc.resolve() / "alt.yaml"
        assert root == etc.resolve()

    def test_bare_filename_no_etc_dir_falls_to_cwd(
        self, bundled_base, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        path, root = resolve_config_source(
            "myorg", "myapp", bundled_base, custom_config="alt.yaml"
        )
        assert path == tmp_path / "alt.yaml"
        assert root == tmp_path

    def test_custom_config_bypasses_xdg_overlay(
        self, bundled_base, tmp_path, monkeypatch
    ):
        """Existing XDG overlay must not shadow --config (always-bypass rule)."""
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        (xdg_home / "myorg" / "myapp.yaml").write_text("")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        monkeypatch.chdir(tmp_path)
        path, _ = resolve_config_source(
            "myorg", "myapp", bundled_base, custom_config="alt.yaml"
        )
        assert path == tmp_path / "alt.yaml"

    def test_custom_config_bypasses_packaged_base(
        self, bundled_base, tmp_path, clean_xdg_env, monkeypatch
    ):
        """--config must not fall back to the packaged base if the file is missing."""
        monkeypatch.chdir(tmp_path)
        # Bare filename referring to a nonexistent file: helper still returns
        # that path (not the packaged base). Config(...) will raise at load.
        path, _ = resolve_config_source(
            "myorg", "myapp", bundled_base, custom_config="missing.yaml"
        )
        assert path == tmp_path / "missing.yaml"
        assert path != bundled_base.resolve()

    def test_custom_config_matching_package_name_still_bypasses(
        self, bundled_base, tmp_path, monkeypatch
    ):
        """--config myapp.yaml has no special-case; still direct-load, no XDG."""
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        (xdg_home / "myorg" / "myapp.yaml").write_text("")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        monkeypatch.chdir(tmp_path)
        path, _ = resolve_config_source(
            "myorg", "myapp", bundled_base, custom_config="myapp.yaml"
        )
        assert path == tmp_path / "myapp.yaml"
        assert path != xdg_home / "myorg" / "myapp.yaml"

    def test_absolute_path_expands_tilde(self, bundled_base, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "custom.yaml").write_text("")
        path, root = resolve_config_source(
            "myorg", "myapp", bundled_base, custom_config="~/custom.yaml"
        )
        assert path == (tmp_path / "custom.yaml").resolve()
        assert root == tmp_path.resolve()

    def test_tilde_no_slash_is_bare_filename(self, bundled_base, monkeypatch, tmp_path):
        """~config.yaml is NOT a valid home-dir reference, it's a bare filename.

        expanduser() raises RuntimeError for ~username when the user doesn't exist,
        so we must not recognize ~config.yaml as a direct path — only ~/... or ~.
        """
        monkeypatch.chdir(tmp_path)
        (tmp_path / "~config.yaml").write_text("tilde_key: value\n")
        path, root = resolve_config_source(
            "myorg", "myapp", bundled_base, custom_config="~config.yaml"
        )
        assert path == (tmp_path / "~config.yaml").resolve()
        assert root == tmp_path.resolve()

    def test_dot_tilde_filename_not_expanded(self, bundled_base, monkeypatch, tmp_path):
        """./~config.yaml is literal, not expanded as ~username.

        expanduser() raises RuntimeError for ~username when user doesn't exist.
        The ./ prefix makes it a direct path, but we must not call expanduser()
        on paths that don't start with ~.
        """
        monkeypatch.chdir(tmp_path)
        (tmp_path / "~config.yaml").write_text("dot_tilde_key: value\n")
        path, root = resolve_config_source(
            "myorg", "myapp", bundled_base, custom_config="./~config.yaml"
        )
        assert path == (tmp_path / "~config.yaml").resolve()
        assert root == tmp_path.resolve()


@pytest.mark.unit
class TestProjectLocalResolution:
    """Rule 4 — project-local walk-up from cwd for ``etc/<base_config.name>``."""

    @pytest.fixture
    def bundled_base(self, tmp_path):
        base = tmp_path / "pkg" / "etc" / "myapp.yaml"
        base.parent.mkdir(parents=True)
        base.write_text("")
        return base

    def _fake_home(self, monkeypatch, home_path):
        """Point ``Path.home()`` at ``home_path`` for this test."""
        monkeypatch.setenv("HOME", str(home_path))

    def test_cwd_etc_is_used_when_present(
        self, bundled_base, tmp_path, monkeypatch, clean_xdg_env
    ):
        """cwd/etc/<name> exists → resolves to it, project_root = cwd/etc."""
        home = tmp_path / "home"
        home.mkdir()
        project = tmp_path / "home" / "project"
        etc = project / "etc"
        etc.mkdir(parents=True)
        local = etc / "myapp.yaml"
        local.write_text("")
        self._fake_home(monkeypatch, home)
        monkeypatch.chdir(project)
        path, root = resolve_config_source("myorg", "myapp", bundled_base)
        assert path == local
        assert root == etc

    def test_walk_up_finds_ancestor_etc(
        self, bundled_base, tmp_path, monkeypatch, clean_xdg_env
    ):
        """cwd deep in the tree → walk up until an ancestor has etc/<name>."""
        home = tmp_path / "home"
        home.mkdir()
        project = home / "project"
        etc = project / "etc"
        etc.mkdir(parents=True)
        local = etc / "myapp.yaml"
        local.write_text("")
        deep = project / "tests" / "sub" / "deeper"
        deep.mkdir(parents=True)
        self._fake_home(monkeypatch, home)
        monkeypatch.chdir(deep)
        path, root = resolve_config_source("myorg", "myapp", bundled_base)
        assert path == local
        assert root == etc

    def test_stops_before_home(
        self, bundled_base, tmp_path, monkeypatch, clean_xdg_env
    ):
        """An etc/<name> sitting AT $HOME must not be picked up."""
        home = tmp_path / "home"
        etc = home / "etc"
        etc.mkdir(parents=True)
        (etc / "myapp.yaml").write_text("")  # tempts the walk-up
        project = home / "project"
        project.mkdir()
        self._fake_home(monkeypatch, home)
        monkeypatch.chdir(project)
        path, _root = resolve_config_source("myorg", "myapp", bundled_base)
        # Walk-up skipped $HOME → falls to bundled base.
        assert path == bundled_base.resolve()

    def test_no_probing_when_cwd_is_home(
        self, bundled_base, tmp_path, monkeypatch, clean_xdg_env
    ):
        """cwd == $HOME → project-local returns None immediately."""
        home = tmp_path / "home"
        home.mkdir()
        self._fake_home(monkeypatch, home)
        monkeypatch.chdir(home)
        path, _root = resolve_config_source("myorg", "myapp", bundled_base)
        assert path == bundled_base.resolve()

    def test_project_local_beats_xdg(
        self, bundled_base, tmp_path, monkeypatch, clean_xdg_env
    ):
        """cwd/etc/<name> present + XDG overlay present → project-local wins."""
        home = tmp_path / "home"
        home.mkdir()
        project = home / "project"
        etc = project / "etc"
        etc.mkdir(parents=True)
        local = etc / "myapp.yaml"
        local.write_text("")
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        (xdg_home / "myorg" / "myapp.yaml").write_text("")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        self._fake_home(monkeypatch, home)
        monkeypatch.chdir(project)
        path, _root = resolve_config_source("myorg", "myapp", bundled_base)
        assert path == local

    def test_custom_etc_dir_beats_project_local(
        self, bundled_base, tmp_path, monkeypatch, clean_xdg_env
    ):
        """--etc-dir explicit takes precedence over the project-local walk-up."""
        home = tmp_path / "home"
        home.mkdir()
        project = home / "project"
        (project / "etc").mkdir(parents=True)
        (project / "etc" / "myapp.yaml").write_text("")
        explicit = tmp_path / "explicit"
        explicit.mkdir()
        self._fake_home(monkeypatch, home)
        monkeypatch.chdir(project)
        path, root = resolve_config_source(
            "myorg", "myapp", bundled_base, custom_etc_dir=explicit
        )
        assert path == explicit.resolve() / "myapp.yaml"
        assert root == explicit.resolve()

    def test_custom_config_beats_project_local(
        self, bundled_base, tmp_path, monkeypatch, clean_xdg_env
    ):
        """--config direct path takes precedence over project-local."""
        home = tmp_path / "home"
        home.mkdir()
        project = home / "project"
        (project / "etc").mkdir(parents=True)
        (project / "etc" / "myapp.yaml").write_text("")
        explicit_file = tmp_path / "explicit.yaml"
        explicit_file.write_text("")
        self._fake_home(monkeypatch, home)
        monkeypatch.chdir(project)
        path, _root = resolve_config_source(
            "myorg", "myapp", bundled_base, custom_config=str(explicit_file)
        )
        assert path == explicit_file.resolve()

    def test_empty_filename_short_circuits(self, tmp_path, monkeypatch, clean_xdg_env):
        """A base_config whose .name is empty (e.g. Path('/')) must not probe."""
        from appinfra.config.xdg import _find_project_local

        home = tmp_path / "home"
        home.mkdir()
        self._fake_home(monkeypatch, home)
        (home / "project").mkdir()
        monkeypatch.chdir(home / "project")
        # Path('/').name == '' — guard hits, returns None without any probe
        assert _find_project_local(Path("/")) is None

    def test_project_local_uses_base_config_name_not_package(
        self, tmp_path, monkeypatch, clean_xdg_env
    ):
        """
        Search filename comes from base_config.name, not <package>.yaml —
        so appinfra's infra.yaml matches without a naming special case.
        """
        home = tmp_path / "home"
        home.mkdir()
        # Base ships as "infra.yaml" though the package is "appinfra"
        bundled = tmp_path / "pkg" / "etc" / "infra.yaml"
        bundled.parent.mkdir(parents=True)
        bundled.write_text("")
        project = home / "project"
        etc = project / "etc"
        etc.mkdir(parents=True)
        local = etc / "infra.yaml"
        local.write_text("")
        # etc/appinfra.yaml would be the naive default; make sure it's NOT picked
        (etc / "appinfra.yaml").write_text("")
        self._fake_home(monkeypatch, home)
        monkeypatch.chdir(project)
        path, _root = resolve_config_source("llm-works", "appinfra", bundled)
        assert path == local
