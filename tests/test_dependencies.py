import pytest
import dependencies


class TestDependencies:

    def setup_method(self):
        dependencies.clear_cache()

    def test_is_available_builtin(self):
        assert dependencies.is_available("json") is True
        assert dependencies.is_available("os") is True

    def test_is_available_missing(self):
        assert dependencies.is_available("nonexistent_module_xyz") is False

    def test_get_module_builtin(self):
        mod = dependencies.get_module("json")
        assert mod is not None

    def test_get_module_missing(self):
        mod = dependencies.get_module("nonexistent_module_xyz")
        assert mod is None

    def test_get_attr(self):
        dumps = dependencies.get_attr("json", "dumps")
        assert dumps is not None
        assert callable(dumps)

    def test_get_attr_missing_module(self):
        result = dependencies.get_attr("nonexistent_module_xyz", "foo")
        assert result is None

    def test_require_builtin(self):
        mod = dependencies.require("json")
        assert mod is not None

    def test_require_missing(self):
        with pytest.raises(ImportError, match="nonexistent_module_xyz"):
            dependencies.require("nonexistent_module_xyz")

    def test_get_import_error(self):
        dependencies.is_available("nonexistent_module_xyz")
        error = dependencies.get_import_error("nonexistent_module_xyz")
        assert error is not None

    def test_cache_consistency(self):
        assert dependencies.is_available("json") is True
        assert dependencies.is_available("json") is True
        mod1 = dependencies.get_module("json")
        mod2 = dependencies.get_module("json")
        assert mod1 is mod2

    def test_clear_cache(self):
        dependencies.is_available("json")
        dependencies.clear_cache()
        assert dependencies.get_module("json") is not None
