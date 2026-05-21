import re
import logging
from typing import Dict, List, Optional, Any

from domain_knowledge import get_domain_knowledge as _get_dk
from nanozyme_models import get_application_type_enum_string

_DK = _get_dk()

APPLICATION_TYPES = {et["value"] for et in _DK.application_types}

APPLICATION_TYPE_PATTERNS = _DK.get_application_type_regex_patterns()

METHOD_PATTERNS = _DK.get_method_regex_patterns()

SAMPLE_TYPE_PATTERNS = _DK.get_sample_type_regex_patterns()

_KNOWN_SUBSTRATES = set(_DK.get_all_substrates())

_KNOWN_ANALYTES = _DK.get_known_analytes()

_PROBE_MOLECULES = _DK.get_probe_molecules()

_INVALID_ANALYTE_PHRASES = _DK.get_invalid_analyte_phrases()

def is_valid_analyte(analyte: str) -> bool:
    if not analyte or not isinstance(analyte, str):
        return False
    t = analyte.lower().strip()
    if not t or len(t) < 2:
        return False
    if any(p in t for p in _PROBE_MOLECULES if len(p) > 2):
        return False
    if t in _INVALID_ANALYTE_PHRASES:
        return False
    return True


async def llm_validate_analyte(analyte: str, context: str, client) -> bool:
    if not analyte or not context or not client:
        return True
    prompt = f"""In a nanozyme paper, the extraction system identified "{analyte}" as a target_analyte (the molecule/cell/tissue being detected/quantified/degraded/killed by the nanozyme platform).

Context from the paper:
{context[:1500]}

Question: Is "{analyte}" truly a target_analyte (the detection, degradation, or therapeutic target), or is it actually:
- A substrate (consumed in the catalytic reaction, like TMB, H2O2, ABTS, OPD)?
- A probe molecule (used as a signal indicator to verify activity, like crystal violet, methylene blue, R6G)?
- A completely vague/invalid description (like "catalytic reactions", "enzyme activity", "various substrates")?

IMPORTANT: The following are VALID target analytes:
- Broad but meaningful categories: "organic pollutants", "carcinogenic organic pollutants", "pesticides", "heavy metals"
- Biological targets in therapeutic applications: "cancer cells", "tumor cells", "bacteria", "biofilm", "inflammation"
- Only reject if it is clearly a substrate, probe, or meaningless phrase.

Answer with ONLY one word: "valid" if it is a genuine target analyte, or "invalid" if it is a substrate, probe, or meaningless phrase."""

    try:
        resp = await client.chat_completion_text(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=10,
        )
        if resp and isinstance(resp, str):
            answer = resp.strip().lower()
            return answer.startswith("valid")
    except Exception as e:
        logger.warning(f"LLM analyte validation failed: {e}")
    return True


def classify_application_type(desc: str, app_type_raw: str = "") -> str:
    combined = (desc + " " + app_type_raw).lower()
    for app_type, patterns in APPLICATION_TYPE_PATTERNS.items():
        for pat in patterns:
            if pat.search(combined):
                return app_type
    return "other"


def extract_method(desc: str) -> Optional[str]:
    for method, pat in METHOD_PATTERNS.items():
        if pat.search(desc):
            return method
    return None


def extract_sample_type(desc: str) -> Optional[str]:
    for stype, pat in SAMPLE_TYPE_PATTERNS.items():
        if pat.search(desc):
            return stype
    return None


def is_analyte(term: str) -> bool:
    if not term:
        return False
    t = term.lower().strip()
    if t in _KNOWN_ANALYTES:
        return True
    if re.search(r'(?i)\b(?:detect|sens|determin|quantif|monitor)\b', term):
        return True
    ion_match = re.search(r'[A-Z][a-z]?\d*[+-]\+?', t)
    if ion_match:
        return True
    if t.endswith(" cells"):
        return True
    return False


def is_substrate(term: str) -> bool:
    if not term:
        return False
    t = term.lower().strip()
    return t in _KNOWN_SUBSTRATES


class ApplicationExtractor:
    def __init__(self):
        self.warnings: List[str] = []

    def extract_applications(
        self,
        raw_applications: List[Dict[str, Any]],
        selected_nanozyme: str,
        table_summaries: Optional[List[Dict[str, Any]]] = None,
        main_activity_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not raw_applications:
            return []

        results: List[Dict[str, Any]] = []
        sel_lower = selected_nanozyme.lower().strip() if selected_nanozyme else ""

        for raw_app in raw_applications:
            if not isinstance(raw_app, dict):
                continue

            app_material = (raw_app.get("system_name") or raw_app.get("material_name_raw") or "").lower().strip()
            if sel_lower and app_material and sel_lower not in app_material and app_material not in sel_lower:
                continue

            app = self._build_application(raw_app, main_activity_type)
            if app:
                results.append(app)

        if table_summaries:
            table_apps = self._extract_from_tables(table_summaries, selected_nanozyme, main_activity_type)
            results.extend(table_apps)

        results = self._deduplicate(results)

        if not results:
            self.warnings.append("application_missing")

        return results

    def _build_application(
        self,
        raw: Dict[str, Any],
        main_activity_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        desc = raw.get("application_description", "") or ""
        app_type_raw = raw.get("application_type", "") or ""
        app_type = classify_application_type(desc, app_type_raw)

        target_analyte = raw.get("target_analyte", "")
        if not target_analyte:
            target_analyte = self._infer_analyte_from_desc(desc)

        if target_analyte:
            target_analyte = self._filter_analyte(target_analyte)

        substrates = raw.get("substrates", [])
        if isinstance(substrates, str):
            substrates = [s.strip() for s in substrates.split(",") if s.strip()]
        cleaned_substrates = []
        for s in substrates:
            if is_analyte(s) and not is_substrate(s):
                if not target_analyte:
                    target_analyte = s
                continue
            cleaned_substrates.append(s)

        method = raw.get("method", "") or extract_method(desc)
        sample_type = raw.get("sample_type", "") or extract_sample_type(desc)

        linear_range = raw.get("linear_range", "")
        if not linear_range:
            lr_low = raw.get("linear_range_low")
            lr_high = raw.get("linear_range_high")
            lr_unit = raw.get("linear_range_unit") or raw.get("unit", "")
            if lr_low is not None and lr_high is not None:
                linear_range = f"{lr_low}–{lr_high} {lr_unit}".strip()

        detection_limit = raw.get("detection_limit", "")
        if not detection_limit:
            dl_val = raw.get("LOD_value") or raw.get("detection_limit_value")
            dl_unit = raw.get("LOD_unit") or raw.get("detection_limit_unit", "")
            if dl_val is not None:
                detection_limit = f"{dl_val} {dl_unit}".strip()

        notes = raw.get("notes", "") or raw.get("selectivity_notes", "") or ""
        if not notes and raw.get("performance_comparison"):
            notes = raw.get("performance_comparison", "")

        return {
            "application_type": app_type,
            "target_analyte": target_analyte or None,
            "method": method or None,
            "linear_range": linear_range or None,
            "detection_limit": detection_limit or None,
            "sample_type": sample_type or None,
            "notes": notes or None,
        }

    def _infer_analyte_from_desc(self, desc: str) -> str:
        if not desc:
            return ""
        for analyte in _KNOWN_ANALYTES:
            if analyte.lower() in desc.lower():
                return analyte
        detect_match = re.search(
            r'(?i)detect(?:ion|ing)?\s+(?:of\s+)?([A-Za-z0-9+\-]+(?:\s+[A-Za-z0-9+\-]+){0,3})',
            desc
        )
        if detect_match:
            return detect_match.group(1).strip()
        return ""

    def _filter_analyte(self, analyte: str) -> str:
        if not analyte:
            return ""
        t = analyte.lower().strip()
        if any(p in t for p in _PROBE_MOLECULES if len(p) > 2):
            logger.info(f"[AppExtractor] Filtered out probe molecule as analyte: {analyte}")
            return ""
        if t in _INVALID_ANALYTE_PHRASES:
            logger.info(f"[AppExtractor] Filtered out invalid analyte phrase: {analyte}")
            return ""
        return analyte

    def _extract_from_tables(
        self,
        table_summaries: List[Dict[str, Any]],
        selected_nanozyme: str,
        main_activity_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        sel_lower = selected_nanozyme.lower().strip() if selected_nanozyme else ""

        for tbl in table_summaries:
            tbl_type = tbl.get("table_type", "")
            if tbl_type != "sensing_performance_table":
                continue

            records = tbl.get("records", [])
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                mat = (rec.get("material") or "").lower().strip()
                if sel_lower and mat and sel_lower not in mat and mat not in sel_lower:
                    continue

                target = rec.get("target_analyte", "")
                if not target:
                    continue

                method = None
                if rec.get("method"):
                    method = rec["method"]

                lr_low = rec.get("linear_range_low")
                lr_high = rec.get("linear_range_high")
                lr_unit = rec.get("linear_range_unit") or rec.get("unit", "")
                linear_range = None
                if lr_low is not None and lr_high is not None:
                    linear_range = f"{lr_low}–{lr_high} {lr_unit}".strip()

                dl_val = rec.get("LOD_value") or rec.get("detection_limit")
                dl_unit = rec.get("LOD_unit") or rec.get("detection_limit_unit", "")
                detection_limit = None
                if dl_val is not None:
                    detection_limit = f"{dl_val} {dl_unit}".strip()

                results.append({
                    "application_type": "biosensing",
                    "target_analyte": target,
                    "method": method,
                    "linear_range": linear_range,
                    "detection_limit": detection_limit,
                    "sample_type": rec.get("sample_type"),
                    "notes": rec.get("notes"),
                })

        return results

    def _deduplicate(self, apps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: set = set()
        unique: List[Dict[str, Any]] = []
        for app in apps:
            key = (
                app.get("application_type", ""),
                app.get("target_analyte", ""),
                app.get("method", ""),
            )
            if key not in seen:
                seen.add(key)
                unique.append(app)
        return unique

    def get_warnings(self) -> List[str]:
        return list(dict.fromkeys(self.warnings))
