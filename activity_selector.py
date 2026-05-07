import re
import logging
from typing import Dict, List, Optional, Any

from nanozyme_models import EnzymeType

logger = logging.getLogger(__name__)

VALID_ENZYME_TYPES = {
    "peroxidase_like", "oxidase_like", "catalase_like",
    "superoxide_dismutase_like", "glucose_oxidase_like",
    "laccase_like", "phosphatase_like", "esterase_like",
    "nuclease_like", "nitroreductase_like", "hydrolase_like",
    "haloperoxidase_like", "other", "unknown",
}


def normalize_enzyme_type(raw: Optional[str]) -> str:
    if not raw:
        return "unknown"
    canonical = EnzymeType.normalize_canonical(raw)
    if canonical and canonical != raw:
        return canonical.replace("-", "_")
    return "unknown"


class ActivitySelector:
    def __init__(self):
        self.warnings: List[str] = []

    def select_main_activity(
        self,
        activities: List[Dict[str, Any]],
        selected_nanozyme: str,
        title: str = "",
        abstract: str = "",
        applications: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not activities:
            self.warnings.append("no_kinetics_found")
            return None

        filtered = self._filter_for_nanozyme(activities, selected_nanozyme)
        if not filtered:
            filtered = activities

        if len(filtered) == 1:
            return self._build_main_activity(filtered[0])

        scored = []
        for act in filtered:
            score = 0
            enzyme_type = act.get("enzyme_like_type", "") or act.get("enzyme_type", "")
            norm_enzyme = normalize_enzyme_type(enzyme_type)

            title_abs = (title + " " + abstract).lower()
            if norm_enzyme.replace("_", " ") in title_abs:
                score += 10
            elif norm_enzyme.replace("_", "-") in title_abs:
                score += 10
            else:
                for variant in [enzyme_type.lower(), norm_enzyme.replace("_", "-"), norm_enzyme.replace("_", " ")]:
                    if variant and variant in title_abs:
                        score += 8
                        break

            kinetics = act.get("kinetics", [])
            if isinstance(kinetics, list) and any(
                isinstance(k, dict) and k.get("value") is not None
                for k in kinetics
            ):
                score += 5
            kinetics_from_table = act.get("kinetics_from_table", [])
            if isinstance(kinetics_from_table, list) and kinetics_from_table:
                score += 3

            if applications:
                act_type_lower = norm_enzyme.replace("_", "-")
                for app in applications:
                    app_desc = (app.get("application_description", "") or "").lower()
                    app_type = (app.get("application_type", "") or "").lower()
                    if act_type_lower in app_desc or act_type_lower in app_type:
                        score += 4
                        break

            substrates = act.get("substrates", [])
            if isinstance(substrates, list):
                score += min(len(substrates), 3)

            evidence_refs = act.get("evidence_refs", [])
            if isinstance(evidence_refs, list):
                score += min(len(evidence_refs), 2)

            scored.append((score, act))

        scored.sort(key=lambda x: x[0], reverse=True)

        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            self.warnings.append("main_activity_uncertain")

        best = scored[0][1] if scored else None
        if best is None:
            self.warnings.append("main_activity_uncertain")
            return None

        return self._build_main_activity(best)

    def _filter_for_nanozyme(
        self,
        activities: List[Dict[str, Any]],
        selected_nanozyme: str,
    ) -> List[Dict[str, Any]]:
        if not selected_nanozyme:
            return activities
        sel_lower = selected_nanozyme.lower().strip()
        matched = []
        for act in activities:
            sys_name = (act.get("system_name") or act.get("material_name_raw") or "").lower().strip()
            if not sys_name or sel_lower in sys_name or sys_name in sel_lower:
                matched.append(act)
        return matched if matched else activities

    def _build_main_activity(self, act: Dict[str, Any]) -> Dict[str, Any]:
        raw_type = act.get("enzyme_like_type", "") or act.get("enzyme_type", "")
        norm_type = normalize_enzyme_type(raw_type)

        substrates = act.get("substrates", [])
        if isinstance(substrates, str):
            substrates = [s.strip() for s in substrates.split(",") if s.strip()]

        kinetics_raw = act.get("kinetics", [])
        kinetics_candidates = []
        if isinstance(kinetics_raw, list):
            for k in kinetics_raw:
                if isinstance(k, dict) and k.get("value") is not None:
                    kinetics_candidates.append(k)

        kinetics_from_table = act.get("kinetics_from_table", [])
        if isinstance(kinetics_from_table, list):
            for kt in kinetics_from_table:
                if not isinstance(kt, dict):
                    continue
                if kt.get("Km_value") is not None:
                    kinetics_candidates.append({
                        "parameter": "Km",
                        "value": kt["Km_value"],
                        "unit": kt.get("Km_unit"),
                        "substrate": kt.get("substrate"),
                        "source": "table",
                        "evidence_text": kt.get("evidence_text", ""),
                    })
                if kt.get("Vmax_value") is not None:
                    kinetics_candidates.append({
                        "parameter": "Vmax",
                        "value": kt["Vmax_value"],
                        "unit": kt.get("Vmax_unit"),
                        "substrate": kt.get("substrate"),
                        "source": "table",
                        "evidence_text": kt.get("evidence_text", ""),
                    })

        return {
            "enzyme_like_type": norm_type,
            "substrates": substrates,
            "kinetics_candidates": kinetics_candidates,
            "conditions": act.get("conditions"),
            "pH_profile": act.get("pH_profile"),
            "temperature_profile": act.get("temperature_profile"),
            "mechanism": act.get("mechanism"),
            "pH_opt": act.get("pH_opt") or act.get("pH"),
            "T_opt": act.get("T_opt") or act.get("temperature"),
            "evidence_refs": act.get("evidence_refs", []),
            "evidence_text": act.get("evidence_text", ""),
        }

    def get_warnings(self) -> List[str]:
        return list(dict.fromkeys(self.warnings))
