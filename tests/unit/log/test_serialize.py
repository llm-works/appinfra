# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for ``appinfra.log.serialize`` and its integration with the JSON
formatter and the multiprocessing queue handler.

Covers:

- ``coerce_leaf`` coerces ``sqlalchemy.engine.url.URL`` via ``str()``.
- ``coerce_tree`` recurses through dict/list/tuple containers.
- ``sanitize_extra`` emits the coerced form.
- ``MPQueueHandler`` preserves coerced values across its pickle sanitizer.
"""

import pytest

from appinfra.log.builder.json import JSONFormatter
from appinfra.log.mp.queue_handler import MPQueueHandler
from appinfra.log.serialize import (
    coerce_leaf,
    coerce_tree,
    record_traceback,
    sanitize_extra,
)

try:
    from sqlalchemy.engine.url import URL as SAURL

    _HAVE_SA = True
except ImportError:
    SAURL = None
    _HAVE_SA = False


def _make_url(password: str = "secret"):
    """Build a sqlalchemy URL for coercion tests. Callers must guard with _HAVE_SA."""
    return SAURL.create(
        "postgresql",
        username="u",
        password=password,
        host="h",
        port=5432,
        database="db",
    )


# =============================================================================
# coerce_leaf
# =============================================================================


class TestCoerceLeaf:
    def test_returns_scalar_unchanged(self):
        for value in ("s", 1, 1.5, True, None):
            assert coerce_leaf(value) is value

    def test_returns_container_unchanged_when_no_match(self):
        d = {"a": 1}
        lst = [1, 2]
        tup = (1, 2)
        assert coerce_leaf(d) is d
        assert coerce_leaf(lst) is lst
        assert coerce_leaf(tup) is tup

    @pytest.mark.skipif(not _HAVE_SA, reason="sqlalchemy not installed")
    def test_coerces_sqlalchemy_url(self):
        coerced = coerce_leaf(_make_url())
        assert isinstance(coerced, str)
        assert "u" in coerced and "h" in coerced and "5432" in coerced
        assert "secret" not in coerced


# =============================================================================
# coerce_tree
# =============================================================================


class TestCoerceTree:
    @pytest.mark.skipif(not _HAVE_SA, reason="sqlalchemy not installed")
    def test_recurses_into_dict(self):
        url = _make_url()
        out = coerce_tree({"k": url})
        assert isinstance(out["k"], str)
        assert "secret" not in out["k"]

    @pytest.mark.skipif(not _HAVE_SA, reason="sqlalchemy not installed")
    def test_recurses_into_list(self):
        url = _make_url()
        out = coerce_tree([url, 1, "x"])
        assert isinstance(out[0], str)
        assert out[1:] == [1, "x"]

    @pytest.mark.skipif(not _HAVE_SA, reason="sqlalchemy not installed")
    def test_recurses_into_tuple(self):
        url = _make_url()
        out = coerce_tree((url, 1))
        assert isinstance(out[0], str)
        assert out[1] == 1

    @pytest.mark.skipif(not _HAVE_SA, reason="sqlalchemy not installed")
    def test_nested(self):
        url = _make_url()
        out = coerce_tree({"a": [{"b": url}]})
        assert isinstance(out["a"][0]["b"], str)
        assert "secret" not in out["a"][0]["b"]

    def test_cyclic_dict_returns_marker(self):
        d: dict = {"key": "value"}
        d["self"] = d
        out = coerce_tree(d)
        assert out["key"] == "value"
        assert out["self"] == "<cyclic reference>"

    def test_cyclic_list_returns_marker(self):
        lst: list = [1, 2]
        lst.append(lst)
        out = coerce_tree(lst)
        assert out[0] == 1
        assert out[1] == 2
        assert out[2] == "<cyclic reference>"

    def test_deeply_nested_cycle(self):
        inner: dict = {"inner": True}
        outer = {"level1": {"level2": inner}}
        inner["back"] = outer
        out = coerce_tree(outer)
        assert out["level1"]["level2"]["inner"] is True
        assert out["level1"]["level2"]["back"] == "<cyclic reference>"

    @pytest.mark.skipif(not _HAVE_SA, reason="sqlalchemy not installed")
    def test_url_in_dict(self):
        out = coerce_tree({"url": _make_url()})
        assert isinstance(out["url"], str)
        assert "secret" not in out["url"]


# =============================================================================
# JSONFormatter integration
# =============================================================================


class TestJSONFormatterSanitize:
    @pytest.mark.skipif(not _HAVE_SA, reason="sqlalchemy not installed")
    def test_url_rendered_as_string(self):
        out = sanitize_extra({"url": _make_url()})
        assert isinstance(out["url"], str)
        assert "secret" not in out["url"]

    @pytest.mark.skipif(not _HAVE_SA, reason="sqlalchemy not installed")
    def test_url_nested_in_dict(self):
        out = sanitize_extra({"cfg": {"url": _make_url()}})
        assert isinstance(out["cfg"]["url"], str)
        assert "secret" not in out["cfg"]["url"]

    def test_plain_values_unchanged(self):
        extra = {"s": "x", "n": 1, "lst": [1, 2], "d": {"a": 1}}
        out = sanitize_extra(extra)
        assert out == extra

    def test_envelope_masked_in_extra(self):
        from appinfra.security.envelope import Envelope

        out = sanitize_extra({"pwd": Envelope("hunter2")})
        assert "hunter2" not in str(out)

    @pytest.mark.skipif(not _HAVE_SA, reason="sqlalchemy not installed")
    def test_format_end_to_end_url_not_destructured(self):
        """Regression guard: rendered JSON must carry the URL as a string."""
        import json
        import logging

        formatter = JSONFormatter()
        url = _make_url(password="topsecret")
        record = logging.LogRecord(
            name="t",
            level=logging.INFO,
            pathname="/x.py",
            lineno=1,
            msg="m",
            args=(),
            exc_info=None,
        )
        # setattr bypasses Python name-mangling of __infra__extra inside the
        # class body (2 leading underscores, 0 trailing → mangled).
        setattr(record, "__infra__extra", {"url": url})

        rendered = formatter.format(record)
        payload = json.loads(rendered)

        assert isinstance(payload["extra"]["url"], str)
        assert "topsecret" not in rendered


# =============================================================================
# MPQueueHandler integration
# =============================================================================


class TestQueueHandlerSanitize:
    @pytest.mark.skipif(not _HAVE_SA, reason="sqlalchemy not installed")
    def test_url_preserved_as_string(self):
        import multiprocessing

        handler = MPQueueHandler(multiprocessing.Queue())
        out = handler._sanitize_for_pickle({"url": _make_url()}, set())
        assert isinstance(out["url"], str)
        assert "secret" not in out["url"]


# =============================================================================
# record_traceback
# =============================================================================


def _raised(msg: str) -> ValueError:
    try:
        raise ValueError(msg)
    except ValueError as e:
        return e


def _raised_elsewhere(msg: str) -> ValueError:
    try:
        raise ValueError(msg)
    except ValueError as e:
        return e


def _record(exc_info=None, extra=None):
    import logging

    record = logging.LogRecord("t", logging.ERROR, "t.py", 1, "m", (), exc_info)
    if extra is not None:
        setattr(record, "__infra__extra", extra)
    return record


class TestRecordTraceback:
    def test_none_without_exception(self):
        assert record_traceback(_record(extra={"k": 1})) is None

    def test_exc_info_formats_the_supplied_traceback(self):
        # The tuple's traceback wins over the exception's own __traceback__
        exc, other = _raised("first"), _raised_elsewhere("second")
        text = record_traceback(
            _record(exc_info=(ValueError, exc, other.__traceback__))
        )
        assert "ValueError: first" in text
        assert "in _raised_elsewhere" in text
        assert "in _raised\n" not in text

    def test_exc_text_from_queue_preparation(self):
        record = _record()
        record.exc_text = "Traceback ...\nValueError: prepared"
        assert record_traceback(record) == "Traceback ...\nValueError: prepared"

    def test_extra_exception(self):
        text = record_traceback(_record(extra={"exception": _raised("boom")}))
        assert "Traceback (most recent call last)" in text
        assert "ValueError: boom" in text

    def test_extra_exception_formatted_from_queue_preparation(self):
        extra = {"exception_formatted": "Traceback ...\nValueError: boom"}
        assert record_traceback(_record(extra=extra)) == extra["exception_formatted"]

    def test_formatting_failure_falls_back_to_message(self):
        text = record_traceback(_record(exc_info=(ValueError, ValueError("x"), 42)))
        assert text == "Exception formatting failed: x"
