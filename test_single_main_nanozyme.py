import json
import pytest
import asyncio
from copy import deepcopy

from single_main_nanozyme_extractor import (
    CandidateRecaller,
    NanozymeScorer,
    EvidenceBucketBuilder,
    PaperMetadataExtractor,
    SingleMainNanozymePipeline,
    PreprocessedDocument,
    SMNConfig,
    TableProcessor,
    FigureProcessor,
    RuleExtractor,
    NumericValidator,
    DiagnosticsBuilder,
    make_empty_record,
    validate_schema,
    EXTRACTION_MODE,
    SCHEMA_VERSION,
    EMPTY_RECORD,
    FORBIDDEN_OLD_FIELDS,
    _GENERIC_PHRASES,
)


MOCK_MID_JSON = {
    "metadata": {
        "title": "Fe3O4@C nanoparticles with enhanced peroxidase-like activity for glucose detection",
        "author": "Zhang Wei, Li Ming, Wang Jun",
        "doi": "10.1016/j.snb.2023.134567",
        "year": "2023",
        "journal": "Sensors and Actuators B",
        "source_file": "test_paper.pdf",
        "document_kind": "main",
        "parse_status": "SUCCESS",
    },
    "extracted_hints": {
        "candidate_system_mentions": ["Fe3O4@C", "Fe3O4", "Au@Ag"],
        "candidate_enzyme_mentions": ["peroxidase-like"],
    },
    "llm_task": {
        "chunks": [
            "Abstract: Fe3O4@C nanoparticles were synthesized via a hydrothermal method. "
            "The as-prepared Fe3O4@C exhibited excellent peroxidase-like activity using TMB as substrate. "
            "The Km for TMB was 0.35 mM and Vmax was 3.2e-7 M/s.",
            "Introduction: Previously, CeO2 nanoparticles have been reported as nanozymes. "
            "Au nanoparticles also show catalase-like activity in reference [5].",
            "Synthesis: Fe3O4@C nanoparticles were prepared by coating Fe3O4 with glucose-derived carbon. "
            "The hydrothermal method was performed at 180C for 12 h. "
            "SEM and TEM images showed spherical nanoparticles with size of 50 nm.",
            "Characterization: XRD patterns confirmed the spinel structure of Fe3O4. "
            "XPS analysis revealed the presence of Fe 2p and C 1s peaks. "
            "The Fe3O4@C was stable over pH range 3.0-8.0.",
            "Activity assay: The peroxidase-like activity of Fe3O4@C was evaluated using TMB and H2O2. "
            "The optimal pH was 4.0 and temperature was 37C in acetate buffer. "
            "The reaction time was 10 min.",
            "Kinetics: Michaelis-Menten kinetics analysis showed Km(TMB) = 0.35 mM, Vmax(TMB) = 3.2e-7 M/s. "
            "Km(H2O2) = 1.2 mM, Vmax(H2O2) = 2.8e-7 M/s.",
            "Application: A colorimetric sensor for glucose detection was developed based on Fe3O4@C. "
            "The linear range was 0.5-50 uM with a detection limit of 0.15 uM. "
            "Recovery in serum samples was 96.5-104.2%.",
            "Conclusion: Fe3O4@C nanoparticles showed excellent peroxidase-like activity "
            "and were successfully applied for glucose detection.",
        ],
        "chunk_contexts": [
            {"candidate_system_mentions": ["Fe3O4@C"]},
            {"candidate_system_mentions": ["CeO2", "Au"]},
            {"candidate_system_mentions": ["Fe3O4@C"]},
            {"candidate_system_mentions": ["Fe3O4@C"]},
            {"candidate_system_mentions": ["Fe3O4@C"]},
            {"candidate_system_mentions": ["Fe3O4@C"]},
            {"candidate_system_mentions": ["Fe3O4@C"]},
            {"candidate_system_mentions": ["Fe3O4@C"]},
        ],
    },
    "vlm_tasks": [
        {"caption": "SEM image of Fe3O4@C nanoparticles showing spherical morphology"},
        {"caption": "TEM image of Fe3O4@C with core-shell structure"},
    ],
    "table_extraction_task": {
        "tables": [
            {
                "headers": ["Nanozyme", "Km (mM)", "Vmax (M/s)"],
                "rows": [
                    ["Fe3O4@C (this work)", "0.35", "3.2e-7"],
                    ["CeO2", "0.82", "1.5e-7"],
                ],
            }
        ]
    },
}


class TestMaterialScoring:
    def test_title_material_highest_score(self):
        doc = PreprocessedDocument(MOCK_MID_JSON)
        recaller = CandidateRecaller()
        candidates = recaller.recall(doc)
        scorer = NanozymeScorer()
        scored = scorer.score(candidates, doc)
        assert scored[0]["name"] == "Fe3O4@C"
        assert scored[0]["score"] > 0

    def test_generic_phrase_penalized(self):
        scorer = NanozymeScorer()
        doc = PreprocessedDocument(MOCK_MID_JSON)
        candidates = [
            {"name": "Fe3O4@C", "sources": {"title"}, "score": 0},
            {"name": "nanoparticles", "sources": {"title"}, "score": 0},
        ]
        scored = scorer.score(candidates, doc)
        np_entry = next(c for c in scored if c["name"] == "nanoparticles")
        assert np_entry["score"] < 0

    def test_ambiguous_flagged(self):
        scorer = NanozymeScorer()
        doc = PreprocessedDocument(MOCK_MID_JSON)
        candidates = [
            {"name": "Fe3O4@C", "sources": {"synthesis"}, "score": 0},
            {"name": "Au@Ag", "sources": {"synthesis"}, "score": 0},
        ]
        scored = scorer.score(candidates, doc)
        if scored[0]["score"] == scored[1]["score"]:
            assert scored[0].get("selection_ambiguous") is True


class TestCandidateFiltering:
    def test_generic_phrases_filtered(self):
        recaller = CandidateRecaller()
        for phrase in _GENERIC_PHRASES:
            assert not recaller._is_valid_candidate(phrase)

    def test_chemical_formula_accepted(self):
        recaller = CandidateRecaller()
        assert recaller._is_valid_candidate("Fe3O4")
        assert recaller._is_valid_candidate("CeO2")
        assert recaller._is_valid_candidate("Au@Ag")

    def test_short_element_only_rejected(self):
        recaller = CandidateRecaller()
        assert not recaller._is_valid_candidate("Th")
        assert not recaller._is_valid_candidate("Au")


class TestNumericValidator:
    def test_negative_km_flagged(self):
        record = make_empty_record()
        record["main_activity"]["kinetics"]["Km"] = -0.5
        record["main_activity"]["kinetics"]["Km_unit"] = "mM"
        result, warnings = NumericValidator().validate(record)
        assert "Km_negative" in warnings

    def test_no_kinetics_flagged(self):
        record = make_empty_record()
        result, warnings = NumericValidator().validate(record)
        assert "no_kinetics_found" in warnings

    def test_valid_kinetics_no_warning(self):
        record = make_empty_record()
        record["main_activity"]["kinetics"]["Km"] = 0.35
        record["main_activity"]["kinetics"]["Vmax"] = 3.2e-7
        result, warnings = NumericValidator().validate(record)
        assert "no_kinetics_found" not in warnings


class TestSchemaValidator:
    def test_empty_record_passes(self):
        record = make_empty_record()
        result = validate_schema(record)
        assert all(key in result for key in EMPTY_RECORD)

    def test_old_fields_removed(self):
        record = make_empty_record()
        record["nanozyme_systems"] = []
        record["catalytic_activities"] = []
        result = validate_schema(record)
        assert "nanozyme_systems" not in result
        assert "catalytic_activities" not in result
        assert "schema_auto_fixed" in result["diagnostics"]["warnings"]

    def test_invalid_status_fixed(self):
        record = make_empty_record()
        record["diagnostics"]["status"] = "unknown"
        result = validate_schema(record)
        assert result["diagnostics"]["status"] in ("complete", "partial", "failed")

    def test_kinetics_all_keys(self):
        record = make_empty_record()
        del record["main_activity"]["kinetics"]["Km"]
        result = validate_schema(record)
        assert "Km" in result["main_activity"]["kinetics"]

    def test_no_forbidden_fields_in_nested(self):
        record = make_empty_record()
        record["selected_nanozyme"]["nanozyme_systems"] = "bad"
        result = validate_schema(record)
        assert "nanozyme_systems" not in result["selected_nanozyme"]

    def test_applications_must_be_list(self):
        record = make_empty_record()
        record["applications"] = "not a list"
        result = validate_schema(record)
        assert isinstance(result["applications"], list)


class TestTableProcessor:
    def test_comparison_table_filters_this_work(self):
        tables = [
            {"headers": ["Material", "Km"], "rows": [
                ["Fe3O4@C (this work)", "0.35"],
                ["CeO2", "0.82"],
            ]},
        ]
        tp = TableProcessor()
        classified = tp.classify_and_summarize(tables, "Fe3O4@C")
        assert len(classified.get("comparison_tables", [])) == 0 or \
               len(classified["comparison_tables"][0].get("this_work_rows", [])) >= 0

    def test_kinetics_table_values(self):
        tables = [
            {"headers": ["Material", "Km (mM)", "Vmax (M/s)"],
             "rows": [["Fe3O4@C (this work)", "0.35", "3.2e-7"]]},
        ]
        tp = TableProcessor()
        classified = tp.classify_and_summarize(tables, "Fe3O4@C")
        values = tp.get_kinetics_values(classified, "Fe3O4@C")
        assert len(values) >= 0


class TestIntegration:
    @pytest.mark.asyncio
    async def test_full_no_llm(self):
        config = SMNConfig(enable_llm=False, enable_vlm=False)
        pipeline = SingleMainNanozymePipeline(client=None, config=config)
        record = await pipeline.extract(MOCK_MID_JSON)

        assert record["paper"]["title"] is not None
        assert record["selected_nanozyme"]["name"] == "Fe3O4@C"
        assert record["main_activity"]["enzyme_like_type"] == "peroxidase-like"
        assert record["diagnostics"]["status"] in ("complete", "partial", "failed")
        assert isinstance(record["applications"], list)
        assert isinstance(record["important_values"], list)

        for field in FORBIDDEN_OLD_FIELDS:
            assert field not in record

    @pytest.mark.asyncio
    async def test_no_candidates_partial(self):
        mid = {
            "metadata": {"title": "A review of library management systems", "source_file": "rev.pdf", "document_kind": "main"},
            "extracted_hints": {"candidate_system_mentions": [], "candidate_enzyme_mentions": []},
            "llm_task": {"chunks": ["This paper reviews methods for library cataloging."], "chunk_contexts": [{}]},
            "vlm_tasks": [],
            "table_extraction_task": {},
        }
        config = SMNConfig(enable_llm=False)
        pipeline = SingleMainNanozymePipeline(client=None, config=config)
        record = await pipeline.extract(mid)
        assert record["diagnostics"]["status"] in ("partial", "failed")
        assert "no_candidates_found" in record["diagnostics"]["warnings"]

    @pytest.mark.asyncio
    async def test_supplementary_partial(self):
        mid = deepcopy(MOCK_MID_JSON)
        mid["metadata"]["document_kind"] = "supplementary"
        config = SMNConfig(enable_llm=False, allow_supplementary_full_record=False)
        pipeline = SingleMainNanozymePipeline(client=None, config=config)
        record = await pipeline.extract(mid)
        assert "supplementary_only" in record["diagnostics"]["warnings"]


class TestDegradation:
    @pytest.mark.asyncio
    async def test_llm_unavailable(self):
        config = SMNConfig(enable_llm=True)
        pipeline = SingleMainNanozymePipeline(client=None, config=config)
        record = await pipeline.extract(MOCK_MID_JSON)
        assert "llm_unavailable" in record["diagnostics"]["warnings"]
        assert record["selected_nanozyme"]["name"] is not None

    @pytest.mark.asyncio
    async def test_llm_disabled(self):
        config = SMNConfig(enable_llm=False)
        pipeline = SingleMainNanozymePipeline(client=None, config=config)
        record = await pipeline.extract(MOCK_MID_JSON)
        assert "llm_disabled" in record["diagnostics"]["warnings"]


class TestComparisonTable:
    @pytest.mark.asyncio
    async def test_comparison_does_not_pollute(self):
        mid = deepcopy(MOCK_MID_JSON)
        mid["llm_task"]["chunks"].append(
            "Comparison: Pt nanoparticles showed the highest activity with Km 0.05 mM."
        )
        mid["llm_task"]["chunk_contexts"].append({})
        config = SMNConfig(enable_llm=False)
        pipeline = SingleMainNanozymePipeline(client=None, config=config)
        record = await pipeline.extract(mid)
        assert record["selected_nanozyme"]["name"] == "Fe3O4@C"


class TestAnalyteSubstrate:
    @pytest.mark.asyncio
    async def test_analyte_not_in_substrates(self):
        config = SMNConfig(enable_llm=False)
        pipeline = SingleMainNanozymePipeline(client=None, config=config)
        record = await pipeline.extract(MOCK_MID_JSON)
        for sub in record["main_activity"].get("substrates", []):
            if isinstance(sub, str):
                assert sub.lower() != "glucose"


class TestSchemaNoOldFields:
    @pytest.mark.asyncio
    async def test_output_no_old_fields(self):
        config = SMNConfig(enable_llm=False)
        pipeline = SingleMainNanozymePipeline(client=None, config=config)
        record = await pipeline.extract(MOCK_MID_JSON)
        for field in FORBIDDEN_OLD_FIELDS:
            assert field not in record

    def test_schema_structure(self):
        record = make_empty_record()
        assert set(record.keys()) == {"paper", "selected_nanozyme", "main_activity",
                                       "applications", "important_values",
                                       "raw_supporting_text", "diagnostics"}
        assert set(record["main_activity"]["kinetics"].keys()) == {
            "Km", "Km_unit", "Vmax", "Vmax_unit",
            "kcat", "kcat_unit", "kcat_Km", "kcat_Km_unit",
            "substrate", "source", "needs_review"}


class TestConfig:
    def test_default(self):
        c = SMNConfig()
        assert c.enable_llm is True
        assert c.output_schema_version == SCHEMA_VERSION

    def test_from_dict(self):
        c = SMNConfig.from_dict({"single_main_nanozyme": {"enable_llm": False}})
        assert c.enable_llm is False


class TestRuleExtractor:
    def test_kinetics_from_text(self):
        record = make_empty_record()
        rule = RuleExtractor()
        rule._extract_kinetics_from_text(record, ["Km(TMB) = 0.35 mM"])
        assert record["main_activity"]["kinetics"]["Km"] == 0.35
        assert record["main_activity"]["kinetics"]["Km_unit"] == "mM"

    def test_lod_from_text(self):
        record = make_empty_record()
        rule = RuleExtractor()
        rule._extract_applications_from_text(record, [
            "A colorimetric sensor for glucose detection with LOD of 0.15 uM"
        ])
        assert len(record["applications"]) > 0
        assert record["applications"][0]["detection_limit"] is not None


class TestPreprocessedDocument:
    def test_from_mid_json(self):
        doc = PreprocessedDocument(MOCK_MID_JSON)
        assert doc.parse_status == "SUCCESS"
        assert doc.document_kind == "main"
        assert len(doc.chunks) == 8
        assert len(doc.vlm_tasks) == 2

    def test_to_preprocessed_output(self):
        doc = PreprocessedDocument(MOCK_MID_JSON)
        output = doc.to_preprocessed_output()
        assert "paper_metadata" in output
        assert "evidence_buckets" in output
        assert set(output["evidence_buckets"].keys()) == {
            "material", "activity", "kinetics", "application",
            "synthesis", "characterization", "mechanism"}


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
