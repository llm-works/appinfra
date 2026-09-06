# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.config.spec — ConfigSpec identity and resolution."""

import dataclasses
import runpy
from pathlib import Path

import pytest

from appinfra.config import AUTO, ConfigFile, ConfigSpec


@pytest.fixture
def clean_xdg_env(monkeypatch):
    """Ensure no XDG_* env vars leak in from the host."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_DIRS", raising=False)


@pytest.fixture
def bundled_base(tmp_path):
    base = tmp_path / "pkg" / "etc" / "myapp.yaml"
    base.parent.mkdir(parents=True)
    base.write_text("")
    return base


def _spec(namespace: str = "ns", name: str = "pkg") -> ConfigSpec:
    """A spec with an explicit path, for tests that never touch the base."""
    return ConfigSpec(namespace, name, path=f"/pkg/etc/{name}.yaml")


def _fake_home(monkeypatch, home_path):
    """Point ``Path.home()`` at ``home_path`` for this test."""
    monkeypatch.setenv("HOME", str(home_path))


def _module_with_base(tmp_path, module: str, filename: str) -> Path:
    """Create an importable package ``module`` under tmp_path shipping etc/<filename>."""
    (tmp_path / module).mkdir()
    (tmp_path / module / "__init__.py").write_text("")
    etc = tmp_path / module / "etc"
    etc.mkdir()
    base = etc / filename
    base.write_text("")
    return base


# =============================================================================
# Construction: AUTO origin
# =============================================================================


@pytest.mark.unit
class TestAutoOrigin:
    """With ``origin`` left AUTO, the base is found in the named module or the caller."""

    def test_locates_module_shipping_the_base(self, tmp_path, monkeypatch):
        base = _module_with_base(tmp_path, "mypkg", "mypkg.yaml")
        monkeypatch.syspath_prepend(str(tmp_path))
        assert ConfigSpec("ns", "mypkg").base_config == base.resolve()

    def test_maps_hyphen_to_underscore_for_the_module(self, tmp_path, monkeypatch):
        """Config ``my-pkg`` → module ``my_pkg``, file ``etc/my-pkg.yaml``."""
        base = _module_with_base(tmp_path, "my_pkg", "my-pkg.yaml")
        monkeypatch.syspath_prepend(str(tmp_path))
        assert ConfigSpec("ns", "my-pkg").base_config == base.resolve()

    def test_does_not_import_the_module(self, tmp_path, monkeypatch):
        _module_with_base(tmp_path, "boom", "boom.yaml")
        (tmp_path / "boom" / "__init__.py").write_text(
            "raise RuntimeError('imported')\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        assert ConfigSpec("ns", "boom").base_config.name == "boom.yaml"

    def test_falls_back_to_the_calling_script(self, tmp_path):
        """No module of that name: the base beside the calling script is used."""
        etc = tmp_path / "etc"
        etc.mkdir()
        (etc / "zz-caller-demo.yaml").write_text("")
        script = tmp_path / "script.py"
        script.write_text(
            "from appinfra.config import ConfigSpec\n"
            "BASE = ConfigSpec('ns', 'zz-caller-demo').base_config\n"
        )
        result = runpy.run_path(str(script))
        assert result["BASE"] == (etc / "zz-caller-demo.yaml").resolve()

    def test_module_without_the_file_falls_through_to_caller(
        self, tmp_path, monkeypatch
    ):
        """A module that exists but ships no base does not win over the caller."""
        (tmp_path / "bare_mod").mkdir()
        (tmp_path / "bare_mod" / "__init__.py").write_text("")
        monkeypatch.syspath_prepend(str(tmp_path))
        # This test module is the caller and has no etc/bare-mod.yaml beside it.
        with pytest.raises(
            ValueError, match="module 'bare_mod'.*does not exist.*calling script"
        ):
            ConfigSpec("ns", "bare-mod")

    def test_unknown_name_raises_naming_both_places(self, tmp_path, monkeypatch):
        monkeypatch.syspath_prepend(str(tmp_path))
        with pytest.raises(
            ValueError, match="not found.*calling script.*origin= or path="
        ):
            ConfigSpec("ns", "no-such-config-anywhere")

    def test_namespace_package_has_no_location(self, tmp_path, monkeypatch):
        """A directory without __init__.py cannot anchor; the error says so."""
        (tmp_path / "nspkg").mkdir()
        monkeypatch.syspath_prepend(str(tmp_path))
        with pytest.raises(ValueError, match="module 'nspkg': not found"):
            ConfigSpec("ns", "nspkg")

    def test_etc_dir_and_filename_apply_to_the_module(self, tmp_path, monkeypatch):
        base = _module_with_base(tmp_path, "appinfra_like", "infra.yaml")
        monkeypatch.syspath_prepend(str(tmp_path))
        spec = ConfigSpec("ns", "appinfra-like", filename="infra.yaml")
        assert spec.base_config == base.resolve()


# =============================================================================
# Construction: explicit parts
# =============================================================================


@pytest.mark.unit
class TestExplicitParts:
    """``origin``, ``etc_dir``, ``filename`` and ``path``; no probing."""

    def test_origin_file_anchors_on_its_directory(self, tmp_path):
        script = tmp_path / "examples" / "demo.py"
        spec = ConfigSpec("ns", "demo-app", origin=script)
        assert (
            spec.base_config
            == (tmp_path / "examples" / "etc" / "demo-app.yaml").resolve()
        )

    def test_origin_directory_is_used_as_is(self, tmp_path):
        spec = ConfigSpec("ns", "demo", origin=tmp_path)
        assert spec.base_config == (tmp_path / "etc" / "demo.yaml").resolve()

    def test_origin_accepts_string_and_expands_tilde(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        spec = ConfigSpec("ns", "demo", origin="~/x.py")
        assert spec.base_config == (tmp_path / "etc" / "demo.yaml").resolve()

    def test_etc_dir_empty_means_beside_the_origin(self, tmp_path):
        spec = ConfigSpec("ns", "bday", origin=tmp_path / "s.py", etc_dir="")
        assert spec.base_config == (tmp_path / "bday.yaml").resolve()

    def test_etc_dir_custom_subdirectory(self, tmp_path):
        spec = ConfigSpec("ns", "demo", origin=tmp_path, etc_dir="conf")
        assert spec.base_config == (tmp_path / "conf" / "demo.yaml").resolve()

    def test_etc_dir_absolute_replaces_the_origin(self, tmp_path):
        spec = ConfigSpec("ns", "demo", origin=tmp_path, etc_dir="/opt/cfg")
        assert spec.base_config == Path("/opt/cfg/demo.yaml")

    def test_filename_overrides_the_stem(self, tmp_path):
        spec = ConfigSpec("ns", "appinfra", origin=tmp_path, filename="infra.yaml")
        assert spec.base_config == (tmp_path / "etc" / "infra.yaml").resolve()

    def test_parts_combine(self, tmp_path):
        spec = ConfigSpec(
            "ns",
            "hot-reload",
            origin=tmp_path / "s.py",
            etc_dir="",
            filename="happy.yaml",
        )
        assert spec.base_config == (tmp_path / "happy.yaml").resolve()

    def test_path_is_taken_verbatim(self, tmp_path):
        base = tmp_path / "anywhere" / "infra.yaml"
        assert ConfigSpec("ns", "appinfra", path=base).base_config == base.resolve()

    def test_path_expands_tilde_and_resolves(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        spec = ConfigSpec("ns", "pkg", path="~/etc/app.yaml")
        assert spec.base_config == (tmp_path / "etc" / "app.yaml").resolve()

    def test_path_resolves_symlink(self, tmp_path):
        real_etc = tmp_path / "real" / "etc"
        real_etc.mkdir(parents=True)
        (real_etc / "app.yaml").write_text("")
        link_etc = tmp_path / "link" / "etc"
        link_etc.parent.mkdir()
        link_etc.symlink_to(real_etc)
        spec = ConfigSpec("ns", "pkg", path=link_etc / "app.yaml")
        assert spec.base_config == (real_etc / "app.yaml").resolve()

    @pytest.mark.parametrize(
        "extra",
        [{"origin": "/x/s.py"}, {"filename": "y.yaml"}, {"etc_dir": ""}],
        ids=["origin", "filename", "etc_dir"],
    )
    def test_path_excludes_the_other_parts(self, tmp_path, extra):
        with pytest.raises(ValueError, match="path excludes"):
            ConfigSpec("ns", "pkg", path=tmp_path / "x.yaml", **extra)

    def test_none_is_not_auto(self, tmp_path):
        with pytest.raises(TypeError, match="not None"):
            ConfigSpec("ns", "pkg", origin=None)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="not None"):
            ConfigSpec("ns", "pkg", origin=tmp_path, filename=None)  # type: ignore[arg-type]

    def test_auto_is_the_default_and_reprs_as_such(self):
        assert repr(AUTO) == "AUTO"

    def test_empty_identity_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            ConfigSpec("", "pkg", path="/x.yaml")
        with pytest.raises(ValueError, match="non-empty"):
            ConfigSpec("ns", "", path="/x.yaml")

    def test_is_frozen_and_hashable(self):
        spec = _spec()
        with pytest.raises(dataclasses.FrozenInstanceError):
            spec.name = "other"  # type: ignore[misc]
        assert spec == _spec()
        assert hash(spec) == hash(_spec())
        assert spec != _spec(name="other")

    def test_records_etc_dir_and_include_root(self, bundled_base, tmp_path):
        spec = ConfigSpec("ns", "myapp", path=bundled_base)
        assert spec.etc_dir == "etc"
        assert spec.include_root == bundled_base.parent.resolve()
        assert ConfigSpec("ns", "d", origin=tmp_path, etc_dir="conf").etc_dir == "conf"


# =============================================================================
# xdg_candidates
# =============================================================================


@pytest.mark.unit
class TestXdgCandidatesDefaults:
    """Behavior when XDG_CONFIG_HOME / XDG_CONFIG_DIRS are unset."""

    def test_defaults_use_spec_fallbacks(self, clean_xdg_env):
        candidates = _spec("llm-works", "my-app").xdg_candidates()
        home = Path.home() / ".config"
        assert candidates == [
            home / "llm-works" / "my-app.yaml",
            home / "llm-works" / "config.yaml",
            Path("/etc/xdg") / "llm-works" / "my-app.yaml",
            Path("/etc/xdg") / "llm-works" / "config.yaml",
        ]

    def test_empty_env_values_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "")
        monkeypatch.setenv("XDG_CONFIG_DIRS", "")
        candidates = _spec().xdg_candidates()
        assert candidates[0].parent.parent == Path.home() / ".config"
        assert candidates[2].parent.parent == Path("/etc/xdg")


@pytest.mark.unit
class TestXdgCandidatesEnvOverrides:
    """Behavior when XDG env vars are set."""

    def test_home_override_only(self, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "/custom/home")
        monkeypatch.delenv("XDG_CONFIG_DIRS", raising=False)
        candidates = _spec().xdg_candidates()
        assert candidates[0] == Path("/custom/home/ns/pkg.yaml")
        assert candidates[1] == Path("/custom/home/ns/config.yaml")
        assert candidates[2] == Path("/etc/xdg/ns/pkg.yaml")

    def test_dirs_override_only(self, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("XDG_CONFIG_DIRS", "/a:/b")
        candidates = _spec().xdg_candidates()
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
        candidates = _spec().xdg_candidates()
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
        dirs = [c.parent.parent for c in _spec().xdg_candidates()]
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
        dirs = [c.parent.parent for c in _spec().xdg_candidates()]
        assert dirs == [Path("/h"), Path("/h"), Path("/abs"), Path("/abs")]

    def test_relative_home_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "relative/path")
        monkeypatch.setenv("XDG_CONFIG_DIRS", "/s")
        candidates = _spec().xdg_candidates()
        home = Path.home() / ".config"
        assert candidates[0].parent.parent == home
        assert candidates[1].parent.parent == home


@pytest.mark.unit
class TestXdgCandidatesOrdering:
    """Order invariants: home before system; per-config before unified per dir."""

    def test_home_before_system(self, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "/h")
        monkeypatch.setenv("XDG_CONFIG_DIRS", "/s")
        candidates = _spec().xdg_candidates()
        assert candidates[0].is_relative_to("/h")
        assert candidates[-1].is_relative_to("/s")

    def test_per_config_before_unified_per_dir(self, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "/h")
        monkeypatch.setenv("XDG_CONFIG_DIRS", "/s")
        candidates = _spec().xdg_candidates()
        assert [c.name for c in candidates] == [
            "pkg.yaml",
            "config.yaml",
            "pkg.yaml",
            "config.yaml",
        ]


@pytest.mark.unit
class TestXdgCandidatesInterpolation:
    """Namespace and name strings appear verbatim in the paths."""

    def test_namespace_and_name_appear_in_paths(self, clean_xdg_env):
        candidates = _spec("my-ns", "my-cfg").xdg_candidates()
        for c in candidates:
            assert c.parent.name == "my-ns"
        assert candidates[0].name == "my-cfg.yaml"
        assert candidates[1].name == "config.yaml"

    def test_no_filesystem_probing(self, monkeypatch):
        spec = _spec()

        def fail_on_exists(self):
            raise AssertionError("xdg_candidates must not probe the filesystem")

        monkeypatch.setattr(Path, "exists", fail_on_exists)
        monkeypatch.setenv("XDG_CONFIG_HOME", "/h")
        monkeypatch.setenv("XDG_CONFIG_DIRS", "/s")
        candidates = spec.xdg_candidates()
        assert len(candidates) == 4
        assert candidates[0] == Path("/h/ns/pkg.yaml")


# =============================================================================
# resolve(): rules 3, 5, 6
# =============================================================================


@pytest.mark.unit
class TestResolveEtcDirXdgBase:
    """``resolve`` walks the rule-6 precedence chain."""

    def test_etc_dir_wins(self, bundled_base, tmp_path, clean_xdg_env):
        custom = tmp_path / "user_etc"
        custom.mkdir()
        cf = ConfigSpec("myorg", "myapp", path=bundled_base).resolve(etc_dir=custom)
        assert cf == ConfigFile(custom.resolve() / "myapp.yaml", custom.resolve(), 3)

    def test_etc_dir_not_pre_validated(self, bundled_base, tmp_path):
        """Missing file under --etc-dir is not this helper's error to raise."""
        custom = tmp_path / "user_etc"
        custom.mkdir()
        cf = ConfigSpec("myorg", "myapp", path=bundled_base).resolve(etc_dir=custom)
        assert not cf.path.exists()
        assert cf.project_root == custom.resolve()

    def test_etc_dir_string_accepted(self, bundled_base, tmp_path):
        custom = tmp_path / "user_etc"
        custom.mkdir()
        cf = ConfigSpec("myorg", "myapp", path=bundled_base).resolve(
            etc_dir=str(custom)
        )
        assert cf.path == custom.resolve() / "myapp.yaml"

    def test_etc_dir_expands_tilde(self, bundled_base, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "user_etc").mkdir()
        cf = ConfigSpec("myorg", "myapp", path=bundled_base).resolve(
            etc_dir="~/user_etc"
        )
        assert cf.project_root == (tmp_path / "user_etc").resolve()

    def test_etc_dir_uses_base_filename_not_name(self, tmp_path, clean_xdg_env):
        """The etc-dir tier looks for the file the spec declares, not <name>.yaml."""
        bundled = tmp_path / "pkg" / "etc" / "infra.yaml"
        bundled.parent.mkdir(parents=True)
        bundled.write_text("")
        custom = tmp_path / "user_etc"
        custom.mkdir()
        cf = ConfigSpec("llm-works", "appinfra", path=bundled).resolve(etc_dir=custom)
        assert cf.path == custom.resolve() / "infra.yaml"

    def test_xdg_overlay_when_no_override(self, bundled_base, monkeypatch, tmp_path):
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        overlay = xdg_home / "myorg" / "myapp.yaml"
        overlay.write_text("")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        monkeypatch.delenv("XDG_CONFIG_DIRS", raising=False)
        cf = ConfigSpec("myorg", "myapp", path=bundled_base).resolve()
        assert cf == ConfigFile(overlay, bundled_base.parent.resolve(), 5)

    def test_fallback_to_bundled_base(self, bundled_base, clean_xdg_env, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "/nonexistent/home")
        monkeypatch.setenv("XDG_CONFIG_DIRS", "/nonexistent/system")
        cf = ConfigSpec("myorg", "myapp", path=bundled_base).resolve()
        assert cf == ConfigFile(
            bundled_base.resolve(), bundled_base.parent.resolve(), 6
        )

    def test_etc_dir_wins_over_existing_xdg(self, bundled_base, monkeypatch, tmp_path):
        """Explicit --etc-dir must not be shadowed by an existing XDG overlay."""
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        (xdg_home / "myorg" / "myapp.yaml").write_text("")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        custom = tmp_path / "user_etc"
        custom.mkdir()
        cf = ConfigSpec("myorg", "myapp", path=bundled_base).resolve(etc_dir=custom)
        assert cf.path == custom.resolve() / "myapp.yaml"
        assert cf.rule == 3

    def test_per_config_overlay_preferred_over_unified(
        self, bundled_base, monkeypatch, tmp_path
    ):
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        (xdg_home / "myorg" / "myapp.yaml").write_text("")
        (xdg_home / "myorg" / "config.yaml").write_text("")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        monkeypatch.delenv("XDG_CONFIG_DIRS", raising=False)
        cf = ConfigSpec("myorg", "myapp", path=bundled_base).resolve()
        assert cf.path.name == "myapp.yaml"

    def test_unified_used_when_per_config_absent(
        self, bundled_base, monkeypatch, tmp_path
    ):
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        (xdg_home / "myorg" / "config.yaml").write_text("")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        monkeypatch.delenv("XDG_CONFIG_DIRS", raising=False)
        cf = ConfigSpec("myorg", "myapp", path=bundled_base).resolve()
        assert cf.path.name == "config.yaml"


# =============================================================================
# resolve(): rules 1 and 2 (--config)
# =============================================================================


@pytest.mark.unit
class TestResolveConfigFile:
    """``config_file``: direct path or bare filename, always bypasses XDG."""

    @pytest.fixture
    def spec(self, bundled_base):
        return ConfigSpec("myorg", "myapp", path=bundled_base)

    def test_absolute_path_loaded_directly(self, spec, tmp_path):
        target = tmp_path / "elsewhere" / "custom.yaml"
        target.parent.mkdir()
        target.write_text("")
        cf = spec.resolve(config_file=str(target))
        assert cf == ConfigFile(target, target.parent, 1)

    def test_absolute_path_ignores_etc_dir(self, spec, tmp_path):
        target = tmp_path / "elsewhere" / "custom.yaml"
        target.parent.mkdir()
        target.write_text("")
        etc = tmp_path / "user_etc"
        etc.mkdir()
        cf = spec.resolve(etc_dir=etc, config_file=str(target))
        assert cf.path == target
        assert cf.project_root == target.parent

    def test_absolute_path_with_dotdot_is_canonicalized(self, spec, tmp_path):
        target = tmp_path / "elsewhere" / "custom.yaml"
        target.parent.mkdir()
        target.write_text("")
        non_canonical = str(tmp_path / "elsewhere" / ".." / "elsewhere" / "custom.yaml")
        cf = spec.resolve(config_file=non_canonical)
        assert cf.path == target.resolve()
        assert cf.project_root == target.parent.resolve()
        assert ".." not in str(cf.path)

    def test_explicit_relative_path_resolves_from_cwd(
        self, spec, tmp_path, monkeypatch
    ):
        target = tmp_path / "custom.yaml"
        target.write_text("")
        monkeypatch.chdir(tmp_path)
        cf = spec.resolve(config_file="./custom.yaml")
        assert cf.path == target.resolve()
        assert cf.project_root == target.resolve().parent
        assert cf.rule == 1

    def test_parent_relative_path_resolves_from_cwd(self, spec, tmp_path, monkeypatch):
        target = tmp_path / "custom.yaml"
        target.write_text("")
        sub = tmp_path / "sub"
        sub.mkdir()
        monkeypatch.chdir(sub)
        cf = spec.resolve(config_file="../custom.yaml")
        assert cf.path == target.resolve()
        assert cf.project_root == target.resolve().parent

    def test_bare_filename_composes_with_etc_dir(self, spec, tmp_path):
        etc = tmp_path / "user_etc"
        etc.mkdir()
        cf = spec.resolve(etc_dir=etc, config_file="alt.yaml")
        assert cf == ConfigFile(etc.resolve() / "alt.yaml", etc.resolve(), 2)

    def test_bare_filename_no_etc_dir_falls_to_cwd(self, spec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cf = spec.resolve(config_file="alt.yaml")
        assert cf == ConfigFile(tmp_path / "alt.yaml", tmp_path, 2)

    def test_config_file_bypasses_xdg_overlay(self, spec, tmp_path, monkeypatch):
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        (xdg_home / "myorg" / "myapp.yaml").write_text("")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        monkeypatch.chdir(tmp_path)
        cf = spec.resolve(config_file="alt.yaml")
        assert cf.path == tmp_path / "alt.yaml"

    def test_config_file_bypasses_packaged_base(
        self, spec, bundled_base, tmp_path, clean_xdg_env, monkeypatch
    ):
        """--config must not fall back to the packaged base if the file is missing."""
        monkeypatch.chdir(tmp_path)
        cf = spec.resolve(config_file="missing.yaml")
        assert cf.path == tmp_path / "missing.yaml"
        assert cf.path != bundled_base.resolve()

    def test_config_file_matching_name_still_bypasses(
        self, spec, tmp_path, monkeypatch
    ):
        """--config myapp.yaml has no special case; still direct, no XDG."""
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        (xdg_home / "myorg" / "myapp.yaml").write_text("")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        monkeypatch.chdir(tmp_path)
        cf = spec.resolve(config_file="myapp.yaml")
        assert cf.path == tmp_path / "myapp.yaml"

    def test_absolute_path_expands_tilde(self, spec, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "custom.yaml").write_text("")
        cf = spec.resolve(config_file="~/custom.yaml")
        assert cf.path == (tmp_path / "custom.yaml").resolve()
        assert cf.project_root == tmp_path.resolve()

    def test_tilde_no_slash_is_bare_filename(self, spec, monkeypatch, tmp_path):
        """``~config.yaml`` is a bare filename; ``expanduser`` would raise for ``~user``."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "~config.yaml").write_text("tilde_key: value\n")
        cf = spec.resolve(config_file="~config.yaml")
        assert cf.path == (tmp_path / "~config.yaml").resolve()
        assert cf.rule == 2

    def test_dot_tilde_filename_not_expanded(self, spec, monkeypatch, tmp_path):
        """``./~config.yaml`` is literal; the ``./`` prefix makes it direct."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "~config.yaml").write_text("dot_tilde_key: value\n")
        cf = spec.resolve(config_file="./~config.yaml")
        assert cf.path == (tmp_path / "~config.yaml").resolve()
        assert cf.rule == 1


# =============================================================================
# resolve(): rule 4 (project-local walk-up)
# =============================================================================


@pytest.mark.unit
class TestProjectLocal:
    """Rule 4: walk up from cwd for ``<etc_dir>/<filename>``."""

    @pytest.fixture
    def spec(self, bundled_base):
        return ConfigSpec("myorg", "myapp", path=bundled_base)

    def _project_with_local(self, tmp_path, etc_dir: str = "etc"):
        home = tmp_path / "home"
        project = home / "project"
        etc = project / etc_dir if etc_dir else project
        etc.mkdir(parents=True, exist_ok=True)
        local = etc / "myapp.yaml"
        local.write_text("")
        return home, project, etc, local

    def test_cwd_etc_is_used_when_present(
        self, spec, tmp_path, monkeypatch, clean_xdg_env
    ):
        home, project, etc, local = self._project_with_local(tmp_path)
        _fake_home(monkeypatch, home)
        monkeypatch.chdir(project)
        assert spec.resolve() == ConfigFile(local, etc, 4)

    def test_walk_up_finds_ancestor_etc(
        self, spec, tmp_path, monkeypatch, clean_xdg_env
    ):
        home, project, etc, local = self._project_with_local(tmp_path)
        deep = project / "tests" / "sub" / "deeper"
        deep.mkdir(parents=True)
        _fake_home(monkeypatch, home)
        monkeypatch.chdir(deep)
        assert spec.resolve() == ConfigFile(local, etc, 4)

    def test_walk_up_uses_the_declared_etc_dir(
        self, tmp_path, monkeypatch, clean_xdg_env
    ):
        home, project, conf, local = self._project_with_local(tmp_path, "conf")
        (project / "etc").mkdir()
        (project / "etc" / "myapp.yaml").write_text("")  # the default layout; must lose
        spec = ConfigSpec("myorg", "myapp", origin=tmp_path / "pkg", etc_dir="conf")
        _fake_home(monkeypatch, home)
        monkeypatch.chdir(project)
        assert spec.resolve() == ConfigFile(local, conf, 4)

    def test_walk_up_with_empty_etc_dir_looks_beside_ancestors(
        self, tmp_path, monkeypatch, clean_xdg_env
    ):
        home, project, _etc, local = self._project_with_local(tmp_path, "")
        spec = ConfigSpec("myorg", "myapp", origin=tmp_path / "pkg", etc_dir="")
        _fake_home(monkeypatch, home)
        monkeypatch.chdir(project)
        assert spec.project_local() == local

    def test_absolute_etc_dir_has_no_project_local(
        self, tmp_path, monkeypatch, clean_xdg_env
    ):
        home, project, _etc, _local = self._project_with_local(tmp_path)
        spec = ConfigSpec("myorg", "myapp", origin=tmp_path / "pkg", etc_dir="/opt/cfg")
        _fake_home(monkeypatch, home)
        monkeypatch.chdir(project)
        assert spec.project_local() is None

    def test_stops_before_home(
        self, spec, bundled_base, tmp_path, monkeypatch, clean_xdg_env
    ):
        """An etc/<name> sitting AT $HOME must not be picked up."""
        home = tmp_path / "home"
        (home / "etc").mkdir(parents=True)
        (home / "etc" / "myapp.yaml").write_text("")
        project = home / "project"
        project.mkdir()
        _fake_home(monkeypatch, home)
        monkeypatch.chdir(project)
        assert spec.resolve().path == bundled_base.resolve()

    def test_no_probing_when_cwd_is_home(
        self, spec, bundled_base, tmp_path, monkeypatch, clean_xdg_env
    ):
        home = tmp_path / "home"
        home.mkdir()
        _fake_home(monkeypatch, home)
        monkeypatch.chdir(home)
        assert spec.project_local() is None
        assert spec.resolve().path == bundled_base.resolve()

    def test_project_local_beats_xdg(self, spec, tmp_path, monkeypatch, clean_xdg_env):
        home, project, _etc, local = self._project_with_local(tmp_path)
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        (xdg_home / "myorg" / "myapp.yaml").write_text("")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        _fake_home(monkeypatch, home)
        monkeypatch.chdir(project)
        assert spec.resolve().path == local

    def test_etc_dir_beats_project_local(
        self, spec, tmp_path, monkeypatch, clean_xdg_env
    ):
        home, project, _etc, _local = self._project_with_local(tmp_path)
        explicit = tmp_path / "explicit"
        explicit.mkdir()
        _fake_home(monkeypatch, home)
        monkeypatch.chdir(project)
        cf = spec.resolve(etc_dir=explicit)
        assert cf.path == explicit.resolve() / "myapp.yaml"
        assert cf.rule == 3

    def test_config_file_beats_project_local(
        self, spec, tmp_path, monkeypatch, clean_xdg_env
    ):
        home, project, _etc, _local = self._project_with_local(tmp_path)
        explicit_file = tmp_path / "explicit.yaml"
        explicit_file.write_text("")
        _fake_home(monkeypatch, home)
        monkeypatch.chdir(project)
        assert (
            spec.resolve(config_file=str(explicit_file)).path == explicit_file.resolve()
        )

    def test_empty_filename_short_circuits(self, tmp_path, monkeypatch, clean_xdg_env):
        """A base whose ``.name`` is empty (``Path('/')``) must not probe."""
        home = tmp_path / "home"
        (home / "project").mkdir(parents=True)
        _fake_home(monkeypatch, home)
        monkeypatch.chdir(home / "project")
        assert ConfigSpec("ns", "pkg", path="/").project_local() is None

    def test_uses_base_filename_not_name(self, tmp_path, monkeypatch, clean_xdg_env):
        """Search filename comes from the base, so etc/infra.yaml matches name appinfra."""
        home = tmp_path / "home"
        bundled = tmp_path / "pkg" / "etc" / "infra.yaml"
        bundled.parent.mkdir(parents=True)
        bundled.write_text("")
        project = home / "project"
        etc = project / "etc"
        etc.mkdir(parents=True)
        local = etc / "infra.yaml"
        local.write_text("")
        (etc / "appinfra.yaml").write_text("")  # the naive default; must not be picked
        _fake_home(monkeypatch, home)
        monkeypatch.chdir(project)
        cf = ConfigSpec("llm-works", "appinfra", path=bundled).resolve()
        assert cf.path == local

    def test_returns_none_when_cwd_raises_oserror(self, monkeypatch):
        spec = _spec()

        def raise_oserror():
            raise OSError("cwd deleted")

        monkeypatch.setattr(Path, "cwd", raise_oserror)
        assert spec.project_local() is None

    def test_returns_none_when_home_raises_runtimeerror(self, monkeypatch, tmp_path):
        spec = _spec()

        def raise_runtimeerror():
            raise RuntimeError("HOME unset")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", raise_runtimeerror)
        assert spec.project_local() is None
