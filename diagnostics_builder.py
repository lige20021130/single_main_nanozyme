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
}


class DiagnosticsBuilder:
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

        return {
            "status": status,
            "confidence": confidence,
            "needs_review": needs_review,
            "warnings": warnings,
        }

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
