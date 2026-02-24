"""Tests for FieldDict - typed DotDict with field declarations."""

from datetime import datetime
from typing import Any

import pytest

from appinfra import FieldDict, field

# =============================================================================
# Test Basic Field Declarations
# =============================================================================


class SimpleResult(FieldDict):
    """Simple FieldDict with required and optional fields."""

    status: str  # required
    method: str = "sft"  # optional with default


@pytest.mark.unit
class TestBasicFields:
    """Test basic field declaration and access."""

    def test_required_field_provided(self):
        """Test creating instance with required field."""
        result = SimpleResult(status="completed")
        assert result.status == "completed"

    def test_optional_field_default(self):
        """Test optional field gets default value."""
        result = SimpleResult(status="completed")
        assert result.method == "sft"

    def test_optional_field_override(self):
        """Test optional field can be overridden."""
        result = SimpleResult(status="completed", method="dpo")
        assert result.method == "dpo"

    def test_missing_required_field_raises(self):
        """Test missing required field raises TypeError."""
        with pytest.raises(TypeError, match="Missing required field.*status"):
            SimpleResult(method="dpo")

    def test_direct_attribute_access(self):
        """Test fields accessible as attributes."""
        result = SimpleResult(status="ok")
        assert result.status == "ok"
        assert result.method == "sft"

    def test_dict_access(self):
        """Test fields accessible as dict keys."""
        result = SimpleResult(status="ok")
        assert result["status"] == "ok"
        assert result["method"] == "sft"


# =============================================================================
# Test Mutable Defaults
# =============================================================================


class ResultWithLists(FieldDict):
    """FieldDict with mutable defaults using field()."""

    name: str
    errors: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@pytest.mark.unit
class TestMutableDefaults:
    """Test mutable defaults with field(default_factory=...)."""

    def test_each_instance_gets_fresh_list(self):
        """Test each instance gets its own list."""
        r1 = ResultWithLists(name="r1")
        r2 = ResultWithLists(name="r2")

        r1.errors.append("error1")

        assert r1.errors == ["error1"]
        assert r2.errors == []  # Not shared!

    def test_each_instance_gets_fresh_dict(self):
        """Test each instance gets its own dict."""
        r1 = ResultWithLists(name="r1")
        r2 = ResultWithLists(name="r2")

        r1.metadata["key"] = "value"

        assert r1.metadata == {"key": "value"}
        assert r2.metadata == {}  # Not shared!

    def test_mutable_default_without_field_raises(self):
        """Test bare mutable default raises TypeError."""
        with pytest.raises(TypeError, match="Mutable default.*not allowed"):

            class BadClass(FieldDict):
                items: list = []  # Should use field(default_factory=list)

    def test_mutable_dict_default_raises(self):
        """Test bare dict default raises TypeError."""
        with pytest.raises(TypeError, match="Mutable default.*not allowed"):

            class BadClass(FieldDict):
                data: dict = {}

    def test_mutable_set_default_raises(self):
        """Test bare set default raises TypeError."""
        with pytest.raises(TypeError, match="Mutable default.*not allowed"):

            class BadClass(FieldDict):
                tags: set = set()


# =============================================================================
# Test Post Init
# =============================================================================


class RunResult(FieldDict):
    """FieldDict with __post_init__ for computed fields."""

    started_at: datetime
    completed_at: datetime
    duration_seconds: float = 0.0

    def __post_init__(self):
        """Compute duration after init."""
        self.duration_seconds = (self.completed_at - self.started_at).total_seconds()


@pytest.mark.unit
class TestPostInit:
    """Test __post_init__ hook."""

    def test_post_init_called(self):
        """Test __post_init__ is called and computes derived fields."""
        t0 = datetime(2024, 1, 1, 12, 0, 0)
        t1 = datetime(2024, 1, 1, 12, 0, 30)

        result = RunResult(started_at=t0, completed_at=t1)

        assert result.duration_seconds == 30.0

    def test_post_init_can_access_all_fields(self):
        """Test __post_init__ can access required and default fields."""

        class Config(FieldDict):
            host: str
            port: int = 5432
            url: str = ""

            def __post_init__(self):
                self.url = f"{self.host}:{self.port}"

        config = Config(host="localhost")
        assert config.url == "localhost:5432"


# =============================================================================
# Test Strict Mode
# =============================================================================


class StrictConfig(FieldDict, strict=True):
    """Strict FieldDict that rejects unknown fields."""

    host: str
    port: int = 5432


class FlexibleConfig(FieldDict):
    """Default (non-strict) FieldDict that allows extra fields."""

    host: str


@pytest.mark.unit
class TestStrictMode:
    """Test strict mode behavior."""

    def test_strict_rejects_unknown_fields(self):
        """Test strict mode raises on unknown fields."""
        with pytest.raises(TypeError, match="Unknown field.*extra"):
            StrictConfig(host="localhost", extra="not_allowed")

    def test_strict_allows_declared_fields(self):
        """Test strict mode allows all declared fields."""
        config = StrictConfig(host="localhost", port=3306)
        assert config.host == "localhost"
        assert config.port == 3306

    def test_non_strict_allows_extra_fields(self):
        """Test non-strict mode allows extra fields."""
        config = FlexibleConfig(host="localhost", extra="allowed", debug=True)
        assert config.host == "localhost"
        assert config.extra == "allowed"
        assert config.debug is True


# =============================================================================
# Test Dict Behavior
# =============================================================================


@pytest.mark.unit
class TestDictBehavior:
    """Test that FieldDict is still a dict."""

    def test_isinstance_dict(self):
        """Test FieldDict instances are dicts."""
        result = SimpleResult(status="ok")
        assert isinstance(result, dict)

    def test_json_serializable(self):
        """Test FieldDict can be serialized to JSON."""
        import json

        result = SimpleResult(status="ok", method="dpo")
        json_str = json.dumps(result)
        assert json_str == '{"status": "ok", "method": "dpo"}'

    def test_dict_methods_work(self):
        """Test dict methods work."""
        result = SimpleResult(status="ok")
        assert "status" in result
        assert list(result.keys()) == ["status", "method"]
        assert result.get("status") == "ok"
        assert result.get("missing") is None

    def test_to_dict(self):
        """Test to_dict() returns plain dict."""
        result = SimpleResult(status="ok")
        d = result.to_dict()
        assert d == {"status": "ok", "method": "sft"}
        assert type(d) is dict

    def test_positional_dict_argument(self):
        """Test creating instance with positional dict (like DotDict)."""
        result = SimpleResult({"status": "from_dict", "method": "custom"})
        assert result.status == "from_dict"
        assert result.method == "custom"

    def test_positional_dict_with_kwargs_override(self):
        """Test kwargs take precedence over positional dict."""
        result = SimpleResult({"status": "from_dict", "method": "old"}, method="new")
        assert result.status == "from_dict"
        assert result.method == "new"  # kwargs wins

    def test_positional_dict_validates_required(self):
        """Test positional dict still validates required fields."""
        with pytest.raises(TypeError, match="Missing required field.*status"):
            SimpleResult({"method": "only_method"})

    def test_multiple_positional_args_raises(self):
        """Test multiple positional args raises TypeError."""
        with pytest.raises(TypeError, match="takes at most 1 positional argument"):
            SimpleResult({}, {})

    def test_non_dict_positional_raises(self):
        """Test non-dict positional arg raises TypeError."""
        with pytest.raises(TypeError, match="argument must be a dict"):
            SimpleResult(["not", "a", "dict"])


# =============================================================================
# Test Repr
# =============================================================================


@pytest.mark.unit
class TestRepr:
    """Test __repr__ shows class name."""

    def test_repr_shows_class_name(self):
        """Test repr includes the class name."""
        result = SimpleResult(status="ok")
        r = repr(result)
        assert r.startswith("SimpleResult(")
        assert "status" in r


# =============================================================================
# Test Inheritance
# =============================================================================


class BaseResult(FieldDict):
    """Base class with some fields."""

    status: str


class ExtendedResult(BaseResult):
    """Extended class adding more fields."""

    details: str = ""


@pytest.mark.unit
class TestInheritance:
    """Test FieldDict inheritance."""

    def test_subclass_inherits_parent_behavior(self):
        """Test subclass works with parent fields."""
        result = ExtendedResult(status="ok")
        assert result.status == "ok"
        assert result.details == ""

    def test_subclass_can_add_fields(self):
        """Test subclass can add its own fields."""
        result = ExtendedResult(status="ok", details="extra info")
        assert result.details == "extra info"

    def test_subclass_requires_parent_fields(self):
        """Test subclass enforces parent's required fields."""
        with pytest.raises(TypeError, match="Missing required field.*status"):
            ExtendedResult(details="only details")  # missing parent's 'status'

    def test_subclass_can_override_required_with_default(self):
        """Test subclass can provide default for parent's required field."""

        class ChildWithDefault(BaseResult):
            status: str = "default_status"  # Override parent's required with default

        # No longer required - can create without providing status
        result = ChildWithDefault()
        assert result.status == "default_status"

        # Can still override the default
        result2 = ChildWithDefault(status="custom")
        assert result2.status == "custom"

    def test_subclass_factory_overrides_parent_static_default(self):
        """Test subclass factory properly overrides parent's static default."""

        class ParentWithStatic(FieldDict):
            items: list = field(default_factory=list)  # Will be overridden
            config: str = "parent_config"

        class ChildWithFactory(ParentWithStatic):
            config: list = field(default_factory=list)  # Override static with factory

        # Each instance should get its own list (not the parent's static default)
        c1 = ChildWithFactory()
        c2 = ChildWithFactory()
        assert c1.config == []
        assert c2.config == []
        c1.config.append("item")
        assert c1.config == ["item"]
        assert c2.config == []  # Independent - confirms factory is used

    def test_subclass_static_overrides_parent_factory(self):
        """Test subclass static default properly overrides parent's factory."""

        class ParentWithFactory(FieldDict):
            items: list = field(default_factory=list)

        class ChildWithStatic(ParentWithFactory):
            items: str = "static_value"  # Override factory with static

        c1 = ChildWithStatic()
        c2 = ChildWithStatic()
        assert c1.items == "static_value"
        assert c2.items == "static_value"


# =============================================================================
# Test Edge Cases
# =============================================================================


@pytest.mark.unit
class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_classvar_skipped(self):
        """Test ClassVar fields are not treated as instance fields."""
        from typing import ClassVar

        class ConfigWithClassVar(FieldDict):
            name: str
            VERSION: ClassVar[str] = "1.0"

        # ClassVar should not be required
        cfg = ConfigWithClassVar(name="test")
        assert cfg.name == "test"
        # ClassVar should still be accessible as class attribute
        assert ConfigWithClassVar.VERSION == "1.0"
        # But not in instance dict
        assert "VERSION" not in cfg

    def test_classvar_string_annotation_skipped(self):
        """Test ClassVar with string annotation (postponed) is skipped."""

        # Simulate postponed annotation by using __annotations__ directly
        class ConfigWithStringClassVar(FieldDict):
            name: str

        # Manually set a string annotation for ClassVar
        ConfigWithStringClassVar.__annotations__["CACHED"] = "ClassVar[dict]"
        ConfigWithStringClassVar.CACHED = {}

        # Should not fail - ClassVar should be skipped even as string
        cfg = ConfigWithStringClassVar(name="test")
        assert cfg.name == "test"

    def test_none_as_default(self):
        """Test None as default value."""

        class NullableResult(FieldDict):
            value: Any = None

        result = NullableResult()
        assert result.value is None

    def test_empty_class(self):
        """Test FieldDict with no fields."""

        class Empty(FieldDict):
            pass

        e = Empty()
        assert dict(e) == {}

    def test_multiple_required_fields_error_message(self):
        """Test error message lists all missing fields."""

        class MultiRequired(FieldDict):
            a: str
            b: str
            c: str

        with pytest.raises(TypeError) as exc_info:
            MultiRequired()

        # All missing fields should be mentioned
        assert "a" in str(exc_info.value)
        assert "b" in str(exc_info.value)
        assert "c" in str(exc_info.value)
