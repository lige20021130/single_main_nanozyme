import re
import logging
from typing import Dict, List, Optional, Any, Tuple, Set
from copy import deepcopy

logger = logging.getLogger(__name__)

_VERIFICATION_STATUSES = frozenset({
    "verified", "unverified", "hallucination_suspect",
    "vlm_unverified", "llm_no_evidence",
    "cross_material_mismatch", "condition_mismatch",
    "activity_application_mismatch",
})

_NUMERIC_FIELDS = frozenset({"Km", "Vmax", "kcat", "kcat_Km"})

_TEXT_FIELDS_KEYWORDS = {
    "enzyme_like_type": {
        "peroxidase-like": ["peroxidase", "pod-like", "pod"],
        "oxidase-like": ["oxidase", "oxd-like", "oxd"],
        "catalase-like": ["catalase", "cat-like", "cat"],
        "superoxide-dismutase-like": ["superoxide dismutase", "sod-like", "sod"],
        "glutathione-peroxidase-like": ["glutathione peroxidase", "gpx-like", "gpx"],
        "glucose-oxidase-like": ["glucose oxidase", "gox-like", "gox"],
        "phosphatase-like": ["phosphatase", "alp-like", "alp"],
        "laccase-like": ["laccase"],
        "esterase-like": ["esterase"],
        "nitroreductase-like": ["nitroreductase", "ntr-like", "ntr"],
        "hydrolase-like": ["hydrolase"],
        "haloperoxidase-like": ["haloperoxidase"],
        "nuclease-like": ["nuclease"],
        "tyrosinase-like": ["tyrosinase"],
        "cascade-enzymatic": ["cascade", "multi-enzymatic"],
    },
    "synthesis_method": {
        "hydrothermal": ["hydrothermal", "solvothermal"],
        "calcination": ["calcination", "annealing", "calcined", "annealed"],
        "coprecipitation": ["coprecipitation", "co-precipitation", "coprecipitated"],
        "sol-gel": ["sol-gel", "sol gel"],
        "pyrolysis": ["pyrolysis", "pyrolyzed", "carbonization", "carbonized"],
        "electrospinning": ["electrospinning", "electrospun"],
        "chemical_vapor_deposition": ["chemical vapor deposition", "cvd"],
        "green_synthesis": ["green synthesis", "biosynthesis", "bio-inspired synthesis"],
        "microwave": ["microwave"],
        "ultrasonic": ["ultrasonic", "sonication", "sonochemical"],
        "template": ["template", "templated", "hard template", "soft template"],
        "self-assembly": ["self-assembly", "self-assembled"],
        "deposition": ["deposition", "deposited"],
        "impregnation": ["impregnation", "impregnated"],
        "combustion": ["combustion", "combustion synthesis"],
    },
}

_PH_PATTERN = re.compile(r'pH\s*[=:≈~]\s*([\d.]+)', re.I)
_TEMP_PATTERN = re.compile(r'(\d+)\s*°?\s*[Cc]', re.I)
_MATERIAL_IN_SENTENCE_RE = re.compile(
    r'\b(?:Fe|Co|Ni|Mn|Cu|Zn|Ce|Au|Ag|Pt|Pd|Ti|V|Cr|Mo|W|Ru|Rh|Ir|La)\d*(?:O\d*)?(?:[A-Z][a-z]?\d*(?:O\d*)?)*\b',
    re.I,
)


def _normalize_numeric_for_search(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = value.strip()
        try:
            return float(value)
        except ValueError:
            pass
        m = re.match(
            r'([\d.]+)\s*[×x\u00d7]\s*10[\u207b\u2212\u2013\-]?\s*(\d+)',
            value,
        )
        if m:
            base = float(m.group(1))
            exp = int(m.group(2))
            has_neg = bool(re.search(r'10[\u207b\u2212\u2013\-]', value))
            if has_neg:
                return base * (10 ** -exp)
            return base * (10 ** exp)
        m = re.match(r'([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)', value)
        if m:
            base = float(m.group(1))
            exp = int(m.group(2).replace('−', '-').replace('\u2212', '-'))
            return base * (10 ** exp)
    return None


def _extract_all_numbers_from_text(text: str) -> List[float]:
    numbers = []
    for m in re.finditer(r'([\d.]+)\s*[×x\u00d7]\s*10[\u207b\u2212\u2013\-]?\s*(\d+)', text):
        try:
            base = float(m.group(1))
            exp = int(m.group(2))
            has_neg = bool(re.search(r'10[\u207b\u2212\u2013\-]', m.group(0)))
            if has_neg:
                numbers.append(base * (10 ** -exp))
            else:
                numbers.append(base * (10 ** exp))
        except (ValueError, IndexError):
            pass
    for m in re.finditer(r'([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)', text):
        try:
            base = float(m.group(1))
            exp = int(m.group(2).replace('−', '-').replace('\u2212', '-'))
            val = base * (10 ** exp)
            if val not in numbers:
                numbers.append(val)
        except (ValueError, IndexError):
            pass
    for m in re.finditer(r'(?<![\d.eE×x\u00d7])(\d+\.?\d*)(?![\d.eE×x\u00d7])', text):
        try:
            val = float(m.group(1))
            if val not in numbers:
                numbers.append(val)
        except ValueError:
            pass
    return numbers


def _values_match(val1: float, val2: float, tolerance: float = 0.05) -> bool:
    if val1 == 0 and val2 == 0:
        return True
    denom = max(abs(val1), abs(val2))
    if denom == 0:
        return True
    return abs(val1 - val2) / denom <= tolerance


def _extract_ph_from_text(text: str) -> Optional[float]:
    m = _PH_PATTERN.search(text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def _extract_temp_from_text(text: str) -> Optional[float]:
    m = _TEMP_PATTERN.search(text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def _find_materials_in_text(text: str) -> List[str]:
    return [m.group(0) for m in _MATERIAL_IN_SENTENCE_RE.finditer(text)]


class ExtractionVerifier:
    def __init__(
        self,
        text_chunks: Optional[List[str]] = None,
        selected_name: str = "",
        all_candidates: Optional[List[str]] = None,
    ):
        self.text_chunks = text_chunks or []
        self.selected_name = selected_name
        self.selected_lower = selected_name.lower().strip() if selected_name else ""
        self.other_candidates = set()
        if all_candidates:
            for c in all_candidates:
                cl = c.lower().strip()
                if cl and cl != self.selected_lower:
                    self.other_candidates.add(cl)
        self._full_text = " ".join(self.text_chunks)
        self._full_text_lower = self._full_text.lower()

    def _find_numeric_in_source(
        self,
        value: Any,
        field_name: str = "",
        evidence_text: str = "",
    ) -> Dict[str, Any]:
        numeric_val = _normalize_numeric_for_search(value)
        if numeric_val is None:
            return {"found": False, "reason": "not_numeric", "matched_in": ""}

        search_pool = self._full_text
        if evidence_text:
            search_pool = evidence_text + " " + search_pool

        all_numbers = _extract_all_numbers_from_text(search_pool)

        for num in all_numbers:
            if _values_match(numeric_val, num, tolerance=0.05):
                return {
                    "found": True,
                    "reason": "exact_or_near_match",
                    "matched_value": num,
                    "matched_in": "evidence_text" if _values_match(numeric_val, num) and evidence_text else "source_text",
                }

        for num in all_numbers:
            if _values_match(numeric_val, num, tolerance=0.15):
                return {
                    "found": True,
                    "reason": "approximate_match",
                    "matched_value": num,
                    "matched_in": "source_text",
                }

        val_str = f"{abs(numeric_val):.4f}"
        for num in all_numbers:
            num_str = f"{abs(num):.4f}"
            if len(val_str) >= 3 and num_str.startswith(val_str[:3]):
                return {
                    "found": True,
                    "reason": "prefix_match",
                    "matched_value": num,
                    "matched_in": "source_text",
                }

        return {"found": False, "reason": "value_not_in_source", "matched_in": ""}

    def _find_text_in_source(
        self,
        value: str,
        field_name: str = "",
    ) -> Dict[str, Any]:
        if not value or not isinstance(value, str):
            return {"found": False, "reason": "empty_value"}

        value_lower = value.lower().strip()

        if value_lower in self._full_text_lower:
            return {"found": True, "reason": "exact_match"}

        keywords_map = _TEXT_FIELDS_KEYWORDS.get(field_name, {})
        keywords = keywords_map.get(value, [])
        if keywords:
            for kw in keywords:
                if kw.lower() in self._full_text_lower:
                    return {"found": True, "reason": "keyword_match", "matched_keyword": kw}

        core = value_lower.split("-")[0].strip()
        if core and len(core) >= 4 and core in self._full_text_lower:
            return {"found": True, "reason": "partial_match"}

        return {"found": False, "reason": "value_not_in_source"}

    def _detect_cross_context_mismatch(
        self,
        record: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        mismatches = []
        kin = record.get("main_activity", {}).get("kinetics", {})
        if not isinstance(kin, dict):
            return mismatches

        field_evidences = {}
        for param in _NUMERIC_FIELDS:
            ev_key = f"_evidence_{param}"
            ev = kin.get(ev_key, "")
            if ev:
                field_evidences[param] = ev

        if len(field_evidences) < 2:
            return mismatches

        materials_per_field = {}
        for param, ev_text in field_evidences.items():
            materials = _find_materials_in_text(ev_text)
            materials_lower = {m.lower() for m in materials}
            materials_per_field[param] = materials_lower

        params = list(field_evidences.keys())
        for i in range(len(params)):
            for j in range(i + 1, len(params)):
                p1, p2 = params[i], params[j]
                m1 = materials_per_field.get(p1, set())
                m2 = materials_per_field.get(p2, set())
                if m1 and m2:
                    overlap = m1 & m2
                    only_p1 = m1 - m2
                    only_p2 = m2 - m1
                    if only_p1 and only_p2:
                        other_in_p1 = only_p1 & self.other_candidates
                        other_in_p2 = only_p2 & self.other_candidates
                        if other_in_p1 or other_in_p2:
                            mismatches.append({
                                "type": "cross_material_mismatch",
                                "field1": f"kinetics.{p1}",
                                "field2": f"kinetics.{p2}",
                                "materials_field1": list(only_p1),
                                "materials_field2": list(only_p2),
                                "detail": f"{p1} evidence mentions {only_p1}, {p2} evidence mentions {only_p2}",
                            })

        ph_per_field = {}
        for param, ev_text in field_evidences.items():
            ph = _extract_ph_from_text(ev_text)
            if ph is not None:
                ph_per_field[param] = ph

        if len(ph_per_field) >= 2:
            ph_vals = list(ph_per_field.values())
            for i in range(len(ph_vals)):
                for j in range(i + 1, len(ph_vals)):
                    if abs(ph_vals[i] - ph_vals[j]) > 2.0:
                        params_with_ph = list(ph_per_field.keys())
                        mismatches.append({
                            "type": "condition_mismatch",
                            "field1": f"kinetics.{params_with_ph[i]}",
                            "field2": f"kinetics.{params_with_ph[j]}",
                            "detail": f"pH differs: {params_with_ph[i]} at pH={ph_vals[i]}, {params_with_ph[j]} at pH={ph_vals[j]}",
                        })

        etype = record.get("main_activity", {}).get("enzyme_like_type", "")
        apps = record.get("applications", [])
        if etype and apps:
            etype_lower = etype.lower()
            for idx, app in enumerate(apps):
                if not isinstance(app, dict):
                    continue
                app_ev = app.get("_evidence", "")
                if not app_ev:
                    continue
                if "peroxidase" in etype_lower and "catalase" in app_ev.lower():
                    mismatches.append({
                        "type": "activity_application_mismatch",
                        "field1": "enzyme_like_type",
                        "field2": f"applications[{idx}]",
                        "detail": f"enzyme_like_type={etype} but application evidence mentions catalase",
                    })
                elif "catalase" in etype_lower and "peroxidase" in app_ev.lower():
                    mismatches.append({
                        "type": "activity_application_mismatch",
                        "field1": "enzyme_like_type",
                        "field2": f"applications[{idx}]",
                        "detail": f"enzyme_like_type={etype} but application evidence mentions peroxidase",
                    })

        return mismatches

    def verify_llm_results(
        self,
        record: Dict[str, Any],
        llm_result: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        record = deepcopy(record)
        verification = {
            "field_status": {},
            "hallucination_suspects": [],
            "mismatches": [],
            "unverified_fields": [],
        }

        llm_act = llm_result.get("main_activity", {})
        if isinstance(llm_act, dict):
            llm_kin = llm_act.get("kinetics", {})
            if isinstance(llm_kin, dict):
                for param in _NUMERIC_FIELDS:
                    llm_val = llm_kin.get(param)
                    if llm_val is None:
                        continue
                    ev_text = llm_kin.get("evidence_text", "") or llm_kin.get(f"_evidence_{param}", "")
                    if not ev_text:
                        verification["field_status"][f"llm.kinetics.{param}"] = "llm_no_evidence"
                        verification["unverified_fields"].append(f"llm.kinetics.{param}")
                        logger.warning(f"[Verifier] LLM {param} has no evidence_text, marking llm_no_evidence")
                        continue

                    result = self._find_numeric_in_source(llm_val, param, ev_text)
                    if result["found"]:
                        verification["field_status"][f"llm.kinetics.{param}"] = "verified"
                        logger.info(f"[Verifier] LLM {param}={llm_val} verified in source ({result['reason']})")
                    else:
                        verification["field_status"][f"llm.kinetics.{param}"] = "hallucination_suspect"
                        verification["hallucination_suspects"].append(f"llm.kinetics.{param}")
                        logger.warning(
                            f"[Verifier] LLM {param}={llm_val} NOT found in source text. "
                            f"Marking as hallucination_suspect."
                        )

            llm_etype = llm_act.get("enzyme_like_type")
            if llm_etype and isinstance(llm_etype, str):
                result = self._find_text_in_source(llm_etype, "enzyme_like_type")
                if result["found"]:
                    verification["field_status"]["llm.enzyme_like_type"] = "verified"
                else:
                    verification["field_status"]["llm.enzyme_like_type"] = "hallucination_suspect"
                    verification["hallucination_suspects"].append("llm.enzyme_like_type")
                    logger.warning(f"[Verifier] LLM enzyme_like_type='{llm_etype}' NOT found in source text")

        llm_sel = llm_result.get("selected_nanozyme", {})
        if isinstance(llm_sel, dict):
            llm_synth = llm_sel.get("synthesis_method")
            if llm_synth and isinstance(llm_synth, str):
                result = self._find_text_in_source(llm_synth, "synthesis_method")
                if result["found"]:
                    verification["field_status"]["llm.synthesis_method"] = "verified"
                else:
                    verification["field_status"]["llm.synthesis_method"] = "hallucination_suspect"
                    verification["hallucination_suspects"].append("llm.synthesis_method")
                    logger.warning(f"[Verifier] LLM synthesis_method='{llm_synth}' NOT found in source text")

        return record, verification

    def verify_vlm_results(
        self,
        record: Dict[str, Any],
        vlm_results: List[Dict[str, Any]],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        record = deepcopy(record)
        verification = {
            "field_status": {},
            "hallucination_suspects": [],
            "mismatches": [],
            "unverified_fields": [],
        }

        for vi, vr in enumerate(vlm_results):
            if not isinstance(vr, dict):
                continue
            ev = vr.get("extracted_values", {})
            if not isinstance(ev, dict):
                continue
            caption = vr.get("caption", "") or vr.get("_source_caption", "")

            for param in _NUMERIC_FIELDS:
                items = ev.get(param, [])
                if not isinstance(items, list):
                    items = [items] if items else []
                for ii, item in enumerate(items):
                    if not isinstance(item, dict):
                        continue
                    val = item.get("value")
                    if val is None:
                        continue
                    field_key = f"vlm[{vi}].{param}"
                    search_text = caption
                    result = self._find_numeric_in_source(val, param, search_text)
                    if result["found"]:
                        verification["field_status"][field_key] = "verified"
                        logger.info(f"[Verifier] VLM {param}={val} verified ({result['reason']})")
                    else:
                        verification["field_status"][field_key] = "vlm_unverified"
                        verification["unverified_fields"].append(field_key)
                        logger.warning(
                            f"[Verifier] VLM {param}={val} NOT found in source or caption. "
                            f"Marking as vlm_unverified."
                        )

            sp = ev.get("sensing_performance")
            if isinstance(sp, dict):
                for sp_field in ("LOD", "linear_range"):
                    sp_val = sp.get(sp_field)
                    if sp_val is not None:
                        field_key = f"vlm[{vi}].sensing_{sp_field}"
                        sp_str = str(sp_val)
                        num_match = re.search(r'([\d.]+)', sp_str)
                        if num_match:
                            num_val = float(num_match.group(1))
                            result = self._find_numeric_in_source(num_val, sp_field, caption)
                            if result["found"]:
                                verification["field_status"][field_key] = "verified"
                            else:
                                verification["field_status"][field_key] = "vlm_unverified"
                                verification["unverified_fields"].append(field_key)
                        else:
                            verification["field_status"][field_key] = "vlm_unverified"
                            verification["unverified_fields"].append(field_key)

        return record, verification

    def verify_record(
        self,
        record: Dict[str, Any],
    ) -> Dict[str, Any]:
        field_status: Dict[str, str] = {}
        hallucination_suspects: List[str] = []
        unverified_fields: List[str] = []

        kin = record.get("main_activity", {}).get("kinetics", {})
        if isinstance(kin, dict):
            for param in _NUMERIC_FIELDS:
                val = kin.get(param)
                if val is None:
                    continue
                ev_text = kin.get(f"_evidence_{param}", "") or kin.get("evidence_text", "")
                field_key = f"kinetics.{param}"

                if not ev_text:
                    field_status[field_key] = "unverified"
                    unverified_fields.append(field_key)
                    continue

                result = self._find_numeric_in_source(val, param, ev_text)
                if result["found"]:
                    field_status[field_key] = "verified"
                else:
                    field_status[field_key] = "hallucination_suspect"
                    hallucination_suspects.append(field_key)

        etype = record.get("main_activity", {}).get("enzyme_like_type")
        if etype and isinstance(etype, str):
            result = self._find_text_in_source(etype, "enzyme_like_type")
            field_status["enzyme_like_type"] = "verified" if result["found"] else "unverified"
            if not result["found"]:
                unverified_fields.append("enzyme_like_type")

        sel = record.get("selected_nanozyme", {})
        if isinstance(sel, dict):
            synth = sel.get("synthesis_method")
            if synth and isinstance(synth, str):
                result = self._find_text_in_source(synth, "synthesis_method")
                field_status["synthesis_method"] = "verified" if result["found"] else "unverified"
                if not result["found"]:
                    unverified_fields.append("synthesis_method")

        apps = record.get("applications", [])
        for idx, app in enumerate(apps):
            if not isinstance(app, dict):
                continue
            dl = app.get("detection_limit")
            if dl:
                field_key = f"applications[{idx}].detection_limit"
                dl_str = str(dl)
                num_match = re.search(r'([\d.]+)', dl_str)
                if num_match:
                    num_val = float(num_match.group(1))
                    ev_text = app.get("_evidence", "")
                    result = self._find_numeric_in_source(num_val, "detection_limit", ev_text)
                    if result["found"]:
                        field_status[field_key] = "verified"
                    else:
                        field_status[field_key] = "unverified"
                        unverified_fields.append(field_key)
                else:
                    field_status[field_key] = "unverified"
                    unverified_fields.append(field_key)

        mismatches = self._detect_cross_context_mismatch(record)

        for mm in mismatches:
            mm_type = mm.get("type", "")
            f1 = mm.get("field1", "")
            f2 = mm.get("field2", "")
            if f1 in field_status and field_status[f1] == "verified":
                field_status[f1] = mm_type
            if f2 in field_status and field_status[f2] == "verified":
                field_status[f2] = mm_type

        rate = self._compute_verification_rate(field_status)

        return {
            "field_status": field_status,
            "hallucination_suspects": hallucination_suspects,
            "mismatches": mismatches,
            "unverified_fields": unverified_fields,
            "overall_verification_rate": rate,
        }

    def _compute_verification_rate(self, field_status: Dict[str, str]) -> float:
        if not field_status:
            return 0.0
        total = len(field_status)
        verified = sum(1 for s in field_status.values() if s == "verified")
        return round(verified / total, 3) if total > 0 else 0.0

    @staticmethod
    def adjust_confidence_by_verification(
        diagnostics: Dict[str, Any],
        verification: Dict[str, Any],
    ) -> Dict[str, Any]:
        rate = verification.get("overall_verification_rate", 0.0)
        hallucination_count = len(verification.get("hallucination_suspects", []))
        mismatch_count = len(verification.get("mismatches", []))

        if rate < 0.5:
            diagnostics["confidence"] = "low"
            diagnostics["needs_review"] = True
        elif rate < 0.8:
            if diagnostics.get("confidence") == "high":
                diagnostics["confidence"] = "medium"
            diagnostics["needs_review"] = True
        else:
            if hallucination_count > 0 or mismatch_count > 0:
                if diagnostics.get("confidence") == "high":
                    diagnostics["confidence"] = "medium"
                diagnostics["needs_review"] = True

        return diagnostics

    def demote_hallucinated_kinetics(
        self,
        record: Dict[str, Any],
        verification: Dict[str, Any],
    ) -> Dict[str, Any]:
        record = deepcopy(record)
        suspects = verification.get("hallucination_suspects", [])

        for suspect in suspects:
            if not suspect.startswith("kinetics."):
                continue
            param = suspect.replace("kinetics.", "")
            if param not in _NUMERIC_FIELDS:
                continue

            kin = record.get("main_activity", {}).get("kinetics", {})
            val = kin.get(param)
            unit = kin.get(f"{param}_unit", "")
            if val is None:
                continue

            record["important_values"].append({
                "name": f"{param}_hallucination_suspect",
                "value": str(val),
                "unit": unit,
                "source": kin.get("source", "unknown"),
                "needs_review": True,
                "context": f"Demoted from kinetics: value not found in source text (hallucination_suspect)",
            })

            record["main_activity"]["kinetics"][param] = None
            record["main_activity"]["kinetics"][f"{param}_unit"] = None
            record["main_activity"]["kinetics"]["needs_review"] = True

            logger.warning(
                f"[Verifier] Demoted {param}={val} from kinetics to important_values "
                f"(hallucination_suspect)"
            )

        return record
