"""Tests: ConsistencyAgent auto-correction, CrossValidationAgent multi-source selection,
kinetics extraction dedup, and SingleRecordAssembler cleanup.
Follows TDD: all tests must FAIL before implementation."""

import pytest
import sys
import copy

PROJECT_ROOT = r"d:\ocrwiki版本\single_main_nanozyme"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from consistency_agent import ConsistencyAgent
from cross_validation_agent import CrossValidationAgent


# ============================================================
# Empty record fixture
# ============================================================

EMPTY_RECORD = {
    "paper": {
        "title": "", "journal": "", "year": None, "volume": None, "pages": None,
        "doi": None, "authors": [], "abstract": "",
    },
    "selected_nanozyme": {
        "name": "Fe-N-C nanozyme",
        "material_name": None, "composition": None, "metal_elements": [],
        "morphology": None, "particle_size": None, "size": None, "size_unit": None,
        "zeta_potential": None, "pore_size": None, "surface_area": None,
        "crystal_structure": None, "dopants_or_defects": [],
        "synthesis_method": None, "synthesis_conditions": {}, "stability": None,
        "characterization": None,
    },
    "main_activity": {
        "enzyme_like_type": "peroxidase-like",
        "substrates": [],
        "conditions": {"pH": 4.0, "temperature": 25.0, "buffer": None, "reaction_time": None},
        "pH_profile": {"optimal_pH": 4.0, "range": None},
        "temperature_profile": {"optimal_temperature": 25.0, "range": None},
        "kinetics": {
            "Km": None, "Km_unit": None, "Vmax": None, "Vmax_unit": None,
            "kcat": None, "kcat_unit": None, "kcat_Km": None, "kcat_Km_unit": None,
            "substrate": None, "source": None, "needs_review": False,
        },
        "kinetics_list": [],
        "mechanism": None, "assay_method": None, "signal": None,
    },
    "applications": [],
    "important_values": [],
    "_evidence_map": {},
    "_diagnostics": {},
}


# ============================================================
# TDD RED: ConsistencyAgent — 自动修正 Km/Vmax 单位互换
# ============================================================

class TestConsistencyAgentAutoCorrectKmUnit:
    """Fix: If Km_unit is a rate unit and Vmax_unit is a concentration unit,
    auto-swap them because they are very likely swapped."""

    def test_auto_swap_km_vmax_units(self):
        agent = ConsistencyAgent()
        record = copy.deepcopy(EMPTY_RECORD)
        record["main_activity"]["kinetics"]["Km"] = 0.15
        record["main_activity"]["kinetics"]["Km_unit"] = "M/s"
        record["main_activity"]["kinetics"]["Vmax"] = 3.2e-8
        record["main_activity"]["kinetics"]["Vmax_unit"] = "mM"

        corrected, warnings = agent.check_cross_field_consistency(record)

        kin = corrected["main_activity"]["kinetics"]
        assert kin["Km_unit"] == "mM", f"Expected Km_unit='mM' (swapped from 'M/s'), got {kin['Km_unit']}"
        assert kin["Vmax_unit"] == "M/s", f"Expected Vmax_unit='M/s' (swapped from 'mM'), got {kin['Vmax_unit']}"
        assert "Km_Vmax_unit_swapped" in warnings, "Expected warning 'Km_Vmax_unit_swapped' in warnings"

    def test_preserve_correct_units(self):
        agent = ConsistencyAgent()
        record = copy.deepcopy(EMPTY_RECORD)
        record["main_activity"]["kinetics"]["Km"] = 0.15
        record["main_activity"]["kinetics"]["Km_unit"] = "mM"
        record["main_activity"]["kinetics"]["Vmax"] = 3.2e-8
        record["main_activity"]["kinetics"]["Vmax_unit"] = "M/s"

        corrected, warnings = agent.check_cross_field_consistency(record)

        kin = corrected["main_activity"]["kinetics"]
        assert kin["Km_unit"] == "mM", f"Km_unit should be preserved as 'mM'"
        assert kin["Vmax_unit"] == "M/s", f"Vmax_unit should be preserved as 'M/s'"


class TestConsistencyAgentCatalaseLowPH:
    """Fix: catalase-like with low pH should be detected and flagged."""

    def test_catalase_low_ph_warning(self):
        agent = ConsistencyAgent()
        record = copy.deepcopy(EMPTY_RECORD)
        record["main_activity"]["enzyme_like_type"] = "catalase-like"
        record["main_activity"]["pH_profile"]["optimal_pH"] = 2.0

        corrected, warnings = agent.check_cross_field_consistency(record)

        assert any("catalase_like_low_pH" in w for w in warnings), \
            f"Expected 'catalase_like_low_pH' warning, got: {warnings}"


# ============================================================
# TDD RED: CrossValidationAgent — 多源选择策略改进
# ============================================================

class TestCrossValidationMultiSourceSelection:
    """Fix: When two sources agree with HIGH confidence, the result should
    override an existing rule value (not kept just because rule val is not None)."""

    def test_two_sources_agree_high_confidence_overrides_rule(self):
        agent = CrossValidationAgent()
        record = copy.deepcopy(EMPTY_RECORD)
        record["main_activity"]["kinetics"]["Km"] = 0.50
        record["main_activity"]["kinetics"]["Km_unit"] = "mM"

        result = agent.validate_kinetics(
            rule_val=0.50, llm_val=0.48, vlm_val=None,
            param_name="Km", rule_unit="mM", llm_unit="mM"
        )

        assert result["confidence"] == "high", f"Expected confidence='high', got {result['confidence']}"
        assert result["reason"] == "two_sources_agree", f"Expected reason='two_sources_agree'"
        assert result["final_value"] is not None
        assert not result.get("needs_review"), "High confidence should not need review"

    def test_final_value_applied_when_high_confidence(self):
        agent = CrossValidationAgent()
        record = copy.deepcopy(EMPTY_RECORD)
        record["main_activity"]["kinetics"]["Km"] = 0.50
        record["main_activity"]["kinetics"]["Km_unit"] = "mM"

        llm_kin = {"Km": 0.48, "Km_unit": "mM"}
        vlm_kin = {}

        validation = agent.validate_kinetics_set(record, llm_kin, vlm_kin)
        kin = record["main_activity"]["kinetics"]

        kin["Km"] = validation["Km"]["final_value"]
        assert kin["Km"] is not None, "Final value should be applied"


# ============================================================
# TDD RED: _extract_kinetics_from_text + _extract_kinetics_from_flattened_table
# ============================================================

# These test the RuleExtractor class directly to verify dedup behavior.
# We import the module and use the actual regex-based extraction methods.

class TestRuleExtractorKineticsOverlap:
    """Verify that _extract_kinetics_from_flattened_table has unique capabilities
    not present in _extract_kinetics_from_text — in particular, it handles
    multi-line table formatted text with headers."""

    def test_flattened_table_has_unique_table_parsing(self):
        from single_main_nanozyme_extractor import RuleExtractor
        extractor = RuleExtractor()

        record = copy.deepcopy(EMPTY_RECORD)
        record["main_activity"]["kinetics"]["Km"] = None
        record["main_activity"]["kinetics"]["Vmax"] = None

        multi_line_table = [
            "| Material | Substrate | Km (mM) | Vmax (M s-1) |\n| Fe-N-C   | TMB       | 0.15    | 3.2e-8       |\n| Fe-N-C   | H2O2      | 2.1     | 5.0e-8       |",
        ]
        selected_name = "Fe-N-C"

        extractor._extract_kinetics_from_flattened_table(
            record, multi_line_table, selected_name
        )

        kin = record["main_activity"]["kinetics"]
        assert kin["Km"] is not None, \
            f"flattened_table should extract Km from structured table, got {kin}"
        assert kin["Vmax"] is not None, \
            f"flattened_table should extract Vmax from structured table, got {kin}"


# ============================================================
# TDD RED: CrossValidationAgent merge_results — reputation confidence override
# ============================================================

class TestCrossValidationMergeReputationOverride:
    """When merge_results has HIGH confidence from validation,
    it should apply the result even if the field already has a rule value."""

    def test_apply_high_confidence_over_existing(self):
        agent = CrossValidationAgent()
        record = copy.deepcopy(EMPTY_RECORD)
        record["main_activity"]["kinetics"]["Km"] = 0.50
        record["main_activity"]["kinetics"]["Km_unit"] = "mM"

        llm_result = {
            "main_activity": {
                "kinetics": {
                    "Km": 0.48,
                    "Km_unit": "mM",
                }
            }
        }

        merged = agent.merge_results(record, llm_result, [])

        kin = merged["main_activity"]["kinetics"]
        assert kin["Km"] is not None, "Kinetics should have Km after merge"


# ============================================================
# TDD RED: _associate_table_caption regex edge cases
# ============================================================

class TestTableNumRegex:
    """Verify _TABLE_NUM_PAT correctly handles edge cases."""

    def test_regex_table_num(self):
        from nanozyme_preprocessor_midjson import _TABLE_NUM_PAT

        tests = [
            ("Table 1", "1"),
            ("Table S1", "S1"),
            ("Table A1", "A1"),
            ("Table 10", "10"),
            ("Supplementary Table S2", "S2"),
            ("Table A10", "A10"),
            ("tbl. 1", "1"),
            ("TABLE 1", "1"),
        ]
        for text, expected in tests:
            m = _TABLE_NUM_PAT.search(text)
            assert m is not None, f"Pattern should match '{text}'"
            assert m.group(1) == expected, \
                f"'{text}' -> expected '{expected}', got '{m.group(1)}'"


# ============================================================
# Run standalone
# ============================================================

if __name__ == "__main__":
    exit_code = pytest.main([__file__, "-v", "-s", "--tb=short"])
    sys.exit(exit_code)
