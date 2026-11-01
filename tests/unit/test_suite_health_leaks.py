# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The leak check of appinfra/_suite_health.py: what counts as a unit test's own change."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from appinfra import _suite_health


def _frames(*filenames: str) -> Any:
    """A frame chain, innermost first, with each frame's code from a file."""
    frame = None
    for filename in reversed(filenames):
        frame = SimpleNamespace(
            f_code=SimpleNamespace(co_filename=filename), f_back=frame
        )
    return frame


def _state(**env: str) -> dict[str, Any]:
    return {"signals": {}, "timer": False, "env": env, "cwd": "/"}


class TestImporting:
    @pytest.mark.parametrize(
        "machinery",
        [
            "<frozen importlib._bootstrap>",
            "<frozen importlib._bootstrap_external>",
            "/usr/lib/python3.12/importlib/_bootstrap.py",  # -X frozen_modules=off
        ],
    )
    def test_the_import_machinery_on_the_stack_is_an_import(
        self, machinery: str
    ) -> None:
        frames = _frames("/venv/lib/torch/_inductor/config.py", machinery, "/proj/t.py")
        assert _suite_health._importing(frames)

    def test_a_test_setting_env_itself_is_not(self) -> None:
        assert not _suite_health._importing(
            _frames("/usr/lib/python3.12/os.py", "/proj/t.py")
        )


class TestChanged:
    def test_an_env_var_a_test_set_is_a_leak(self) -> None:
        assert _suite_health._changed(_state(), _state(X="1"), {}) == ["$X"]

    def test_an_env_var_left_as_an_import_set_it_is_not(self) -> None:
        before, after = _state(), _state(TORCHINDUCTOR_CACHE_DIR="/tmp/c")
        import_env = {"TORCHINDUCTOR_CACHE_DIR": "/tmp/c"}
        assert _suite_health._changed(before, after, import_env) == []

    def test_an_env_var_an_import_removed_is_not(self) -> None:
        assert _suite_health._changed(_state(X="1"), _state(), {"X": None}) == []

    def test_a_test_changing_what_an_import_set_is_a_leak(self) -> None:
        changed = _suite_health._changed(_state(X="1"), _state(X="2"), {"X": "1"})
        assert changed == ["$X"]

    def test_a_test_removing_what_an_import_set_is_a_leak(self) -> None:
        assert _suite_health._changed(_state(X="1"), _state(), {"X": "1"}) == ["$X"]


class TestNoteImportEnv:
    @pytest.fixture
    def written(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, str | None]:
        """The values the hook keeps, by variable."""
        values: dict[str, str | None] = {}
        monkeypatch.setattr(_suite_health, "_import_env", values)
        return values

    def test_keeps_the_value_an_import_set_or_removed(
        self, monkeypatch: pytest.MonkeyPatch, written: dict[str, str | None]
    ) -> None:
        monkeypatch.setattr(_suite_health, "_importing", lambda frame: True)
        _suite_health._note_import_env("os.putenv", (b"VLLM_LOGGING_LEVEL", b"INFO"))
        _suite_health._note_import_env("os.unsetenv", (b"VLLM_HOST_IP",))
        assert written == {"VLLM_LOGGING_LEVEL": "INFO", "VLLM_HOST_IP": None}

    def test_ignores_a_var_set_outside_an_import(
        self, monkeypatch: pytest.MonkeyPatch, written: dict[str, str | None]
    ) -> None:
        monkeypatch.setattr(_suite_health, "_importing", lambda frame: False)
        _suite_health._note_import_env("os.putenv", (b"X", b"1"))
        assert written == {}

    def test_ignores_other_events_and_pytest_s_own_var(
        self, monkeypatch: pytest.MonkeyPatch, written: dict[str, str | None]
    ) -> None:
        monkeypatch.setattr(_suite_health, "_importing", lambda frame: True)
        _suite_health._note_import_env("open", ("/tmp/x", "r", 0))
        _suite_health._note_import_env("os.putenv", (b"PYTEST_CURRENT_TEST", b"t"))
        assert written == {}
