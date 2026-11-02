# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for Envelope as a pydantic field type."""

import json

import pytest

pydantic = pytest.importorskip("pydantic")

from appinfra.envelope import Envelope  # noqa: E402


class Settings(pydantic.BaseModel):
    """A model with an Envelope field and no arbitrary_types_allowed."""

    key: Envelope
    name: str = "app"


class TestEnvelopePydantic:
    """Envelope validates, masks in JSON output, and has a JSON schema."""

    def test_str_is_wrapped(self):
        settings = Settings(key="hunter2")

        assert isinstance(settings.key, Envelope)
        assert settings.key.reveal() == "hunter2"

    def test_envelope_passes_through(self):
        envelope = Envelope("hunter2")

        assert Settings(key=envelope).key is envelope

    def test_non_str_is_a_validation_error(self):
        with pytest.raises(pydantic.ValidationError, match="Envelope requires a str"):
            Settings(key=42)

    def test_python_dump_keeps_the_envelope(self):
        settings = Settings(key="hunter2")

        dumped = settings.model_dump()

        assert dumped["key"] is settings.key
        assert Settings.model_validate(dumped) == settings

    def test_json_dump_writes_the_mask(self):
        dumped = Settings(key="hunter2").model_dump_json()

        assert json.loads(dumped) == {"key": "***", "name": "app"}
        assert "hunter2" not in dumped

    def test_json_mode_python_dump_writes_the_mask(self):
        dumped = Settings(key="hunter2").model_dump(mode="json")

        assert dumped["key"] == "***"

    def test_json_schema_is_a_write_only_string(self):
        key = Settings.model_json_schema()["properties"]["key"]

        assert (key["type"], key["format"], key["writeOnly"]) == (
            "string",
            "password",
            True,
        )

    def test_optional_field_accepts_none(self):
        class Optional(pydantic.BaseModel):
            key: Envelope | None = None

        assert Optional().key is None
        assert Optional(key="hunter2").key == Envelope("hunter2")
