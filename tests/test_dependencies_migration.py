import pytest
import dependencies


class TestDependenciesMigration:

    def setup_method(self):
        dependencies.clear_cache()

    def test_api_client_uses_dependencies_module(self):
        from api_client import CONFIG_MANAGER_AVAILABLE
        expected = dependencies.is_available("config_manager")
        assert CONFIG_MANAGER_AVAILABLE == expected

    def test_run_extraction_uses_dependencies_module(self):
        assert dependencies.is_available("nanozyme_preprocessor_midjson") is not None

    def test_extraction_agents_norm_unit(self):
        from extraction_agents import _norm_unit, _is_concentration_unit, _is_rate_unit
        assert callable(_norm_unit)
        assert callable(_is_concentration_unit)
        assert callable(_is_rate_unit)
        assert _norm_unit("mM") is not None
        assert _norm_unit(None) is None
        assert _norm_unit("") == ""

    def test_extraction_agents_concentration_unit(self):
        from extraction_agents import _is_concentration_unit
        assert _is_concentration_unit("mM") is True
        assert _is_concentration_unit("") is False
        assert _is_concentration_unit(None) is False

    def test_extraction_agents_rate_unit(self):
        from extraction_agents import _is_rate_unit
        assert _is_rate_unit("M/s") is True
        assert _is_rate_unit("") is False
        assert _is_rate_unit(None) is False

    def test_smn_extractor_issue_severity_available(self):
        from single_main_nanozyme_extractor import IssueSeverity
        assert hasattr(IssueSeverity, 'LOW')
        assert hasattr(IssueSeverity, 'HIGH')

    def test_smn_extractor_class_deps_checkable(self):
        expected_modules = [
            "extraction_agents",
            "cross_validation_agent",
            "consistency_agent",
            "extraction_verifier",
            "vlm_extractor",
            "consistency_guard_agentic",
        ]
        for mod in expected_modules:
            result = dependencies.is_available(mod)
            assert result is not None
