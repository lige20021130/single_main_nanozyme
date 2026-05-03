import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

VALID_STATUSES = {"complete", "partial", "failed"}
VALID_CONFIDENCES = {"high", "medium", "low"}

WARNING_ENUMS = {
    "parse_protocol_error",
    "supplementary_only",
    "selected_material_ambiguous",
    "no_kinetics_found",
    "kinetics_from_figure_candidate",
    "caption_match_low_confidence",
    "numeric_validation_failed",
    "application_missing",
    "main_activity_uncertain",
    "no_pH_profile",
    "no_temperature_profile",
    "no_synthesis_method",
    "no_size_info",
    "Km_negative",
    "Vmax_negative",
    "Vmax_empty_string",
    "suspect_Km_unit",
    "suspect_Vmax_unit",
    "LOD_no_numeric_value",
    "material_mismatch",
    "attribution_mismatch",
    "Km_unit_not_concentration",
    "Vmax_unit_not_rate",
    "kcat_Km_unreasonable",
    "catalase_like_low_pH",
    "peroxidase_like_high_pH",
    "hydrothermal_low_temperature",
    "calcination_low_temperature",
    "llm_failed",
    "llm_disabled",
    "llm_unavailable",
    "vlm_failed_or_no_results",
    "vlm_disabled",
    "vlm_unavailable",
    "no_candidates_found",
    "sparse_evidence",
    "kinetics_bucket_fallback_applied",
    "application_bucket_fallback_applied",
    "mechanism_bucket_fallback_applied",
    "schema_auto_fixed",
    "hallucination_suspect",
    "vlm_unverified",
    "cross_material_mismatch",
    "condition_mismatch",
    "activity_application_mismatch",
    "llm_no_evidence",
}


class DiagnosticsBuilder:
    _regex_hit_stats: Dict[str, int] = {}

    @classmethod
    def record_regex_hit(cls, pattern_name: str):
        cls._regex_hit_stats[pattern_name] = cls._regex_hit_stats.get(pattern_name, 0) + 1

    @classmethod
    def get_regex_hit_stats(cls) -> Dict[str, int]:
        return dict(cls._regex_hit_stats)

    @classmethod
    def reset_regex_hit_stats(cls):
        cls._regex_hit_stats = {}

    def __init__(self):
        self._parse_status: Optional[str] = None
        self._is_supplementary: bool = False
        self._selected_nanozyme: Optional[str] = None
        self._selected_nanozyme_ambiguous: bool = False
        self._main_activity: Optional[Dict[str, Any]] = None
        self._kinetics: Optional[Dict[str, Any]] = None
        self._applications: List[Dict[str, Any]] = []
        self._numeric_warnings: List[str] = []
        self._table_warnings: List[str] = []
        self._figure_warnings: List[str] = []
        self._activity_warnings: List[str] = []
        self._application_warnings: List[str] = []
        self._caption_low_confidence: bool = False
        self._kinetics_from_figure: bool = False
        self._verification: Optional[Dict[str, Any]] = None

    def set_parse_status(self, status: Optional[str]) -> "DiagnosticsBuilder":
        self._parse_status = status
        return self

    def set_supplementary(self, is_supp: bool) -> "DiagnosticsBuilder":
        self._is_supplementary = is_supp
        return self

    def set_selected_nanozyme(
        self,
        name: Optional[str],
        ambiguous: bool = False,
    ) -> "DiagnosticsBuilder":
        self._selected_nanozyme = name
        self._selected_nanozyme_ambiguous = ambiguous
        return self

    def set_main_activity(self, activity: Optional[Dict[str, Any]]) -> "DiagnosticsBuilder":
        self._main_activity = activity
        return self

    def set_kinetics(self, kinetics: Optional[Dict[str, Any]]) -> "DiagnosticsBuilder":
        self._kinetics = kinetics
        return self

    def set_applications(self, apps: List[Dict[str, Any]]) -> "DiagnosticsBuilder":
        self._applications = apps or []
        return self

    def add_numeric_warnings(self, warnings: List[str]) -> "DiagnosticsBuilder":
        self._numeric_warnings.extend(warnings)
        return self

    def add_table_warnings(self, warnings: List[str]) -> "DiagnosticsBuilder":
        self._table_warnings.extend(warnings)
        return self

    def add_figure_warnings(self, warnings: List[str]) -> "DiagnosticsBuilder":
        self._figure_warnings.extend(warnings)
        return self

    def add_activity_warnings(self, warnings: List[str]) -> "DiagnosticsBuilder":
        self._activity_warnings.extend(warnings)
        return self

    def add_application_warnings(self, warnings: List[str]) -> "DiagnosticsBuilder":
        self._application_warnings.extend(warnings)
        return self

    def set_caption_low_confidence(self, flag: bool) -> "DiagnosticsBuilder":
        self._caption_low_confidence = flag
        return self

    def set_kinetics_from_figure(self, flag: bool) -> "DiagnosticsBuilder":
        self._kinetics_from_figure = flag
        return self

    def set_verification(self, verification: Dict[str, Any]) -> "DiagnosticsBuilder":
        self._verification = verification
        return self

    def compute_field_coverage(self, record: Dict[str, Any]) -> Dict[str, str]:
        coverage = {}
        sel = record.get("selected_nanozyme", {})
        act = record.get("main_activity", {})
        kin = act.get("kinetics", {})

        field_paths = {
            "selected_nanozyme.name": sel.get("name"),
            "selected_nanozyme.synthesis_method": sel.get("synthesis_method"),
            "selected_nanozyme.size": sel.get("size"),
            "selected_nanozyme.morphology": sel.get("morphology"),
            "selected_nanozyme.crystal_structure": sel.get("crystal_structure"),
            "selected_nanozyme.surface_area": sel.get("surface_area"),
            "main_activity.enzyme_like_type": act.get("enzyme_like_type"),
            "main_activity.substrates": act.get("substrates"),
            "main_activity.kinetics.Km": kin.get("Km"),
            "main_activity.kinetics.Vmax": kin.get("Vmax"),
            "main_activity.kinetics.kcat": kin.get("kcat"),
            "main_activity.kinetics.kcat_Km": kin.get("kcat_Km"),
            "main_activity.pH_profile.optimal_pH": act.get("pH_profile", {}).get("optimal_pH"),
            "main_activity.temperature_profile.optimal_temperature": act.get("temperature_profile", {}).get("optimal_temperature"),
            "applications": record.get("applications"),
        }

        for path, value in field_paths.items():
            if value is None or value == [] or value == "" or value == "unknown":
                coverage[path] = "missing"
            elif value == 0 or (isinstance(value, float) and value == 0.0):
                coverage[path] = "extracted"
            else:
                coverage[path] = "extracted"

        return coverage

    def build(self) -> Dict[str, Any]:
        warnings: List[str] = []

        if self._parse_status and self._parse_status not in ("ok", "success", "complete"):
            warnings.append("parse_protocol_error")

        if self._is_supplementary:
            warnings.append("supplementary_only")

        if self._selected_nanozyme_ambiguous:
            warnings.append("selected_material_ambiguous")

        if not self._selected_nanozyme:
            warnings.append("selected_material_ambiguous")

        has_kinetics = False
        if self._kinetics:
            km = self._kinetics.get("Km")
            vmax = self._kinetics.get("Vmax")
            if km is not None or vmax is not None:
                has_kinetics = True

        if not has_kinetics:
            warnings.append("no_kinetics_found")

        if self._kinetics_from_figure:
            warnings.append("kinetics_from_figure_candidate")

        if self._caption_low_confidence:
            warnings.append("caption_match_low_confidence")

        for w in self._numeric_warnings:
            if w in WARNING_ENUMS and w not in warnings:
                warnings.append(w)

        for w in self._activity_warnings:
            if w in WARNING_ENUMS and w not in warnings:
                warnings.append(w)

        if not self._applications:
            if "application_missing" not in warnings:
                warnings.append("application_missing")
        for w in self._application_warnings:
            if w in WARNING_ENUMS and w not in warnings:
                warnings.append(w)

        for w in self._table_warnings:
            if w in WARNING_ENUMS and w not in warnings:
                warnings.append(w)

        for w in self._figure_warnings:
            if w in WARNING_ENUMS and w not in warnings:
                warnings.append(w)

        if not self._main_activity:
            if "main_activity_uncertain" not in warnings:
                warnings.append("main_activity_uncertain")

        status = self._determine_status(warnings)
        confidence = self._determine_confidence(status, warnings)
        needs_review = confidence != "high" or bool(warnings)

        result = {
            "status": status,
            "confidence": confidence,
            "needs_review": needs_review,
            "warnings": warnings,
        }

        if self._verification is not None:
            result["verification"] = self._verification

            for field_info in self._verification.get("hallucination_suspects", []):
                if isinstance(field_info, dict):
                    w = field_info.get("warning_type", "hallucination_suspect")
                else:
                    w = "hallucination_suspect"
                if w in WARNING_ENUMS and w not in result["warnings"]:
                    result["warnings"].append(w)

            mismatch_types = set()
            for mm in self._verification.get("mismatches", []):
                if isinstance(mm, dict):
                    mt = mm.get("mismatch_type", "")
                else:
                    mt = str(mm)
                if mt and mt in WARNING_ENUMS and mt not in result["warnings"]:
                    result["warnings"].append(mt)
                    mismatch_types.add(mt)

            rate = self._verification.get("overall_verification_rate")
            if isinstance(rate, (int, float)):
                if rate < 0.5:
                    result["confidence"] = "low"
                    result["needs_review"] = True
                elif rate < 0.8:
                    if result["confidence"] == "high":
                        result["confidence"] = "medium"
                        result["needs_review"] = True
                else:
                    has_suspects = bool(self._verification.get("hallucination_suspects"))
                    has_mismatches = bool(self._verification.get("mismatches"))
                    if (has_suspects or has_mismatches) and result["confidence"] == "high":
                        result["confidence"] = "medium"

        return result

    def _determine_status(self, warnings: List[str]) -> str:
        if not self._selected_nanozyme:
            return "failed"

        if "parse_protocol_error" in warnings and not self._selected_nanozyme:
            return "failed"

        critical_warnings = {"supplementary_only", "selected_material_ambiguous"}
        if any(w in critical_warnings for w in warnings):
            return "partial"

        has_kinetics = False
        if self._kinetics:
            km = self._kinetics.get("Km")
            vmax = self._kinetics.get("Vmax")
            if km is not None or vmax is not None:
                has_kinetics = True

        has_app = bool(self._applications)
        has_activity = self._main_activity is not None

        if has_activity and (has_kinetics or has_app):
            minor_warnings = {"no_kinetics_found", "application_missing", "caption_match_low_confidence"}
            remaining = [w for w in warnings if w not in minor_warnings]
            if not remaining:
                return "complete"

        if has_activity or has_kinetics or has_app:
            return "partial"

        return "failed"

    def _determine_confidence(self, status: str, warnings: List[str]) -> str:
        if status == "failed":
            return "low"

        high_risk = {"numeric_validation_failed", "kinetics_from_figure_candidate", "selected_material_ambiguous"}
        if any(w in high_risk for w in warnings):
            return "low"

        medium_risk = {"supplementary_only", "caption_match_low_confidence", "main_activity_uncertain"}
        if any(w in medium_risk for w in warnings):
            return "medium"

        if status == "complete" and len(warnings) <= 1:
            return "high"

        if status == "partial":
            return "medium"

        return "medium"


def generate_batch_report(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not records:
        return {"total": 0, "field_rates": {}, "summary": "No records to analyze"}

    builder = DiagnosticsBuilder()
    all_coverage = [builder.compute_field_coverage(r) for r in records]

    field_rates = {}
    for field in all_coverage[0].keys():
        extracted_count = sum(1 for c in all_coverage if c.get(field) == "extracted")
        field_rates[field] = round(extracted_count / len(records) * 100, 1)

    status_counts = {}
    for r in records:
        s = r.get("diagnostics", {}).get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    avg_warnings = sum(len(r.get("diagnostics", {}).get("warnings", [])) for r in records) / len(records)

    return {
        "total": len(records),
        "field_rates": field_rates,
        "status_distribution": status_counts,
        "avg_warnings_per_record": round(avg_warnings, 1),
        "low_rate_fields": {k: v for k, v in field_rates.items() if v < 50},
        "regex_hit_stats": DiagnosticsBuilder.get_regex_hit_stats(),
    }
