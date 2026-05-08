import re
import logging
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)

SOURCE_PRIORITY = {
    "text": 4,
    "table": 3,
    "figure_caption": 2,
    "figure_candidate": 1,
}

CONCENTRATION_UNITS = {
    "M", "mM", "μM", "uM", "nM", "pM",
    "M/L", "mM/L", "μM/L", "uM/L",
    "M L^-1", "mM L^-1", "μM L^-1", "uM L^-1",
    "mol/L", "mmol/L", "umol/L", "nmol/L",
    "mol L^-1", "mmol L^-1",
}

RATE_UNITS = {
    "M/s", "M s^-1", "M s-1", "M/min", "M min^-1", "M min-1",
    "M h^-1", "M h-1", "M/h",
    "mM/s", "mM s^-1", "mM s-1", "mM/min", "mM min^-1", "mM min-1",
    "mM h^-1", "mM h-1", "mM/h",
    "μM/s", "uM/s", "μM s^-1", "uM s^-1", "μM s-1", "uM s-1",
    "μM/min", "uM/min", "μM min^-1", "uM min^-1", "μM min-1", "uM min-1",
    "μM/h", "uM/h", "μM h^-1", "uM h^-1",
    "nM/s", "nM s^-1", "nM s-1", "nM/min", "nM min^-1", "nM min-1",
    "mol L^-1 s^-1", "mol L-1 s-1",
    "mol/L/h", "mmol/L/h", "umol/L/h",
    "mol L^-1 h^-1", "mmol L^-1 h^-1",
    "M L^-1 s^-1", "mM L^-1 s^-1",
    "U/mg", "U mg^-1", "U mg-1",
}

KCAT_UNITS = {
    "s^-1", "s-1", "s⁻¹", "min^-1", "min-1", "min⁻¹",
}

KCAT_KM_UNITS = {
    "M^-1 s^-1", "M-1 s-1", "M⁻¹ s⁻¹",
    "mM^-1 s^-1", "mM-1 s-1", "mM⁻¹ s⁻¹",
    "μM^-1 s^-1", "uM-1 s-1", "μM⁻¹ s⁻¹",
}

_KM_MAGNITUDE_RANGE = (1e-12, 10.0)
_KM_MAGNITUDE_REVIEW = (1e-9, 1.0)
_VMAX_MAGNITUDE_RANGE = (1e-15, 1e8)
_VMAX_MAGNITUDE_REVIEW = (1e-12, 1e6)
_KCAT_MAGNITUDE_RANGE = (1e-6, 1e10)
_KCAT_MAGNITUDE_REVIEW = (1e-3, 1e8)
_KCAT_KM_MAGNITUDE_RANGE = (1e-3, 1e12)
_KCAT_KM_MAGNITUDE_REVIEW = (1e0, 1e10)

_KM_UNIT_RE = re.compile(
    r'^(?:M|mM|μM|uM|nM|pM|mol/L|mmol/L|umol/L|nmol/L|'
    r'M\s*L\^-?1|mM\s*L\^-?1)$', re.IGNORECASE
)

_VMAX_UNIT_RE = re.compile(
    r'^(?:M|mM|μM|uM|nM|pM)\s*(?:/?\s*(?:s|min|h))\s*[\^-]?\s*\d*'
    r'|^(?:mol|mmol|umol|nmol)\s*L\^-?\d*\s*s\^-?\d*'
    r'|^U\s*/?\s*mg\s*[\^-]?\d*$',
    re.IGNORECASE
)

_LINeweAVER_BURK_RE = re.compile(
    r'(?i)lineweaver.?burk|double.?reciprocal|1/[SV]|1/V\s+vs\s+1/[Ss]'
)

_KM_CONTEXT_RE = re.compile(
    r'(?i)\bK[_\s]?m\b|Kₘ|michaelis.?menten|affinity\s+constant'
)

_VMAX_CONTEXT_RE = re.compile(
    r'(?i)\bV[_\s]?max\b|Vₘₐₓ|maximum\s+velocity|maximal\s+rate'
)

_NUMERIC_VALUE_RE = re.compile(
    r'([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)\s*(mM|μM|uM|nM|pM|M)\s*'
    r'(?:/?\s*(s|min|h))?\s*[\^-]?\s*\d*'
)


def normalize_unit(unit: Optional[str]) -> Optional[str]:
    if not unit:
        return None
    u = unit.strip()
    u = re.sub(r'\s+', ' ', u)
    u = u.replace('⁻¹', '^-1').replace('⁻²', '^-2')
    u = u.replace('⁻', '^-')
    u = u.replace('−', '-').replace('–', '-')
    u = u.replace('·', '/')
    u = u.replace('\u00b7', '/')
    u = re.sub(r'\s*/\s*', '/', u)
    u = re.sub(r'\s*\^\s*', '^', u)
    u = re.sub(r'^[×x\u00d7]\s*10\s*[\^]?\s*[\-−–]?\s*(\d+)$', lambda m: f'×10^{m.group(1)}', u)
    u = re.sub(r'\bMs\b', 'M/s', u)
    u = re.sub(r'\bmMs\b', 'mM/s', u)
    u = re.sub(r'\bM\s+s\b', 'M/s', u)
    u = re.sub(r'\bmM\s+s\b', 'mM/s', u)
    u = re.sub(r'\bM\s+min\b', 'M/min', u)
    u = re.sub(r'\bmM\s+min\b', 'mM/min', u)
    u = re.sub(r'\b(mM|M|μM|uM)\s+s-1\b', r'\1/s', u)
    u = re.sub(r'\b(mM|M|μM|uM)\s+min-1\b', r'\1/min', u)
    u = re.sub(r'\b(mM|M|μM|uM)\s*/?\s*s\^-?1\b', r'\1/s', u)
    u = re.sub(r'\b(mM|M|μM|uM)\s*/?\s*min\^-?1\b', r'\1/min', u)
    u = re.sub(r'\b(mM|M|μM|uM)\s*/\s*s\s*\^-?\s*1\b', r'\1/s', u)
    u = re.sub(r'\b(mM|M|μM|uM)\s*/?\s*s-1\b', r'\1/s', u)
    u = re.sub(r'\b(mM|M|μM|uM)\s*/?\s*min-1\b', r'\1/min', u)
    u = re.sub(r'\bM\u207b\u00b9\s*s\u207b\u00b9\b', 'M^-1 s^-1', u)
    u = re.sub(r'\bM-1\s+min-1\b', 'M^-1 min^-1', u)
    u = re.sub(r'\bM-1\s+s-1\b', 'M^-1 s^-1', u)
    u = re.sub(r'\bmol/L/s\b', 'mol L^-1 s^-1', u)
    u = re.sub(r'\bmmol/L/s\b', 'mmol L^-1 s^-1', u)
    u = re.sub(r'\bumol/L/s\b', 'umol L^-1 s^-1', u)
    u = re.sub(r'\bmol/L/h\b', 'mol L^-1 h^-1', u)
    u = re.sub(r'\bmmol/L/h\b', 'mmol L^-1 h^-1', u)
    u = re.sub(r'\bM/L\b', 'M L^-1', u)
    u = re.sub(r'\bmM/L\b', 'mM L^-1', u)
    u = re.sub(r'\bμM/L\b', 'μM L^-1', u)
    u = re.sub(r'\buM/L\b', 'uM L^-1', u)
    u = re.sub(r'\bmol/L\b', 'M', u)
    u = re.sub(r'\bmmol/L\b', 'mM', u)
    u = re.sub(r'\bumol/L\b', 'μM', u)
    u = re.sub(r'\bnmol/L\b', 'nM', u)
    u = re.sub(r'\bM/h\b', 'M h^-1', u)
    u = re.sub(r'\bmM/h\b', 'mM h^-1', u)
    u = re.sub(r'\bμM/h\b', 'μM h^-1', u)
    u = re.sub(r'\buM/h\b', 'uM h^-1', u)
    return u


def is_concentration_unit(unit: Optional[str]) -> bool:
    if not unit:
        return False
    nu = normalize_unit(unit)
    return nu in CONCENTRATION_UNITS


def is_rate_unit(unit: Optional[str]) -> bool:
    if not unit:
        return False
    nu = normalize_unit(unit)
    return nu in RATE_UNITS


def classify_source(evidence: Dict[str, Any]) -> str:
    src = evidence.get("source", "")
    if src in SOURCE_PRIORITY:
        return src
    ref = evidence.get("evidence_refs", [])
    ref_str = " ".join(str(r) for r in ref) if ref else ""
    etxt = evidence.get("evidence_text", "") or ""
    combined = ref_str + " " + etxt
    if re.search(r'(?i)\btable\b', combined):
        return "table"
    if re.search(r'(?i)\bfig(?:ure)?\b', combined):
        if re.search(r'(?i)\bcaption\b', combined):
            return "figure_caption"
        return "figure_candidate"
    return "text"


def check_magnitude(param: str, value: float, unit: Optional[str]) -> Tuple[bool, bool, str]:
    if value is None or not isinstance(value, (int, float)):
        return False, False, ""
    ranges = {
        "Km": (_KM_MAGNITUDE_RANGE, _KM_MAGNITUDE_REVIEW),
        "Vmax": (_VMAX_MAGNITUDE_RANGE, _VMAX_MAGNITUDE_REVIEW),
        "kcat": (_KCAT_MAGNITUDE_RANGE, _KCAT_MAGNITUDE_REVIEW),
        "kcat_Km": (_KCAT_KM_MAGNITUDE_RANGE, _KCAT_KM_MAGNITUDE_REVIEW),
    }
    if param not in ranges:
        return False, False, ""
    (lo, hi), (rlo, rhi) = ranges[param]
    if value < lo or value > hi:
        return True, False, f"{param} value {value} outside acceptable range ({lo}–{hi})"
    if value < rlo or value > rhi:
        return False, True, f"{param} value {value} outside typical range ({rlo}–{rhi})"
    return False, False, ""


def is_lineweaver_burk_context(evidence_text: str) -> bool:
    if not evidence_text:
        return False
    return bool(_LINeweAVER_BURK_RE.search(evidence_text))


def calibrate_magnitude_ranges(text_chunks: List[str]) -> Dict[str, Tuple[float, float]]:
    full_text = " ".join(text_chunks)
    all_conc = []
    for m in re.finditer(r'([\d.]+)\s*(mM|μM|uM|M|nM|µM|nmol|umol|mmol)', full_text):
        try:
            val = float(m.group(1))
            unit = m.group(2)
            if unit in ("M",):
                all_conc.append(val)
            elif unit in ("mM", "mmol"):
                all_conc.append(val * 1e-3)
            elif unit in ("μM", "uM", "µM", "umol"):
                all_conc.append(val * 1e-6)
            elif unit in ("nM", "nmol"):
                all_conc.append(val * 1e-9)
        except ValueError:
            pass

    adjusted = {
        "Km_review": (1e-9, 1.0),
        "Vmax_review": (1e-12, 1e6),
    }

    if not all_conc:
        return adjusted

    typical = sorted(all_conc)[len(all_conc) // 2] if all_conc else 1e-6
    high = max(all_conc)

    if typical < 1e-6:
        adjusted["Km_review"] = (1e-9, max(0.01, typical * 10000))
        adjusted["Vmax_review"] = (1e-12, max(1e-4, typical * 100))
    elif typical < 1e-3:
        adjusted["Km_review"] = (1e-9, max(0.1, typical * 10000))
    else:
        adjusted["Km_review"] = (1e-9, max(1.0, high * 5))

    return adjusted


class NumericValidator:
    def __init__(self):
        self.warnings: List[str] = []
        self.important_values: List[Dict[str, Any]] = []
        self._paper_context: Optional[Dict[str, Tuple[float, float]]] = None

    def set_paper_context(self, context: Dict[str, Tuple[float, float]]):
        self._paper_context = context

    def _get_adjusted_review_range(self, param: str) -> Tuple[float, float]:
        if self._paper_context and param == "Km":
            return self._paper_context.get("Km_review", (1e-9, 1.0))
        if self._paper_context and param == "Vmax":
            return self._paper_context.get("Vmax_review", (1e-12, 1e6))
        if param == "Km":
            return (1e-9, 1.0)
        if param == "Vmax":
            return (1e-12, 1e6)
        return (0, float("inf"))

    def validate_kinetics_entry(
        self,
        entry: Dict[str, Any],
        selected_nanozyme: str,
        main_activity_type: Optional[str] = None,
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        self.warnings = []
        demoted: List[Dict[str, Any]] = []
        needs_review_flag = False

        param = entry.get("parameter", "")
        value = entry.get("value")
        unit = entry.get("unit")
        substrate = entry.get("substrate")
        evidence_text = entry.get("evidence_text", "") or ""
        source = classify_source(entry)

        if value is None:
            return None, demoted

        try:
            numeric_val = float(value)
        except (ValueError, TypeError):
            self.warnings.append("numeric_validation_failed")
            return None, demoted

        material = entry.get("material", "")
        if material and selected_nanozyme:
            mat_lower = material.lower().strip()
            sel_lower = selected_nanozyme.lower().strip()
            if mat_lower and sel_lower and mat_lower not in sel_lower and sel_lower not in mat_lower:
                demoted.append(self._make_important_value(
                    entry, source, "material_mismatch", True
                ))
                return None, demoted

        if param == "Km":
            if not is_concentration_unit(unit):
                demoted.append(self._make_important_value(
                    entry, source, "Km_unit_not_concentration", True
                ))
                self.warnings.append("numeric_validation_failed")
                return None, demoted

        elif param == "Vmax":
            if not is_rate_unit(unit):
                demoted.append(self._make_important_value(
                    entry, source, "Vmax_unit_not_rate", True
                ))
                self.warnings.append("numeric_validation_failed")
                return None, demoted

        elif param == "kcat":
            nu = normalize_unit(unit) if unit else None
            if nu and nu not in KCAT_UNITS:
                demoted.append(self._make_important_value(
                    entry, source, "kcat_unit_invalid", True
                ))
                self.warnings.append("numeric_validation_failed")
                return None, demoted
            reject, review, msg = check_magnitude("kcat", numeric_val, unit)
            if reject:
                demoted.append(self._make_important_value(
                    entry, source, msg, True
                ))
                return None, demoted
            if review:
                needs_review_flag = True

        elif param == "kcat_Km":
            nu = normalize_unit(unit) if unit else None
            if nu and nu not in KCAT_KM_UNITS:
                demoted.append(self._make_important_value(
                    entry, source, "kcat_Km_unit_invalid", True
                ))
                self.warnings.append("numeric_validation_failed")
                return None, demoted
            reject, review, msg = check_magnitude("kcat_Km", numeric_val, unit)
            if reject:
                demoted.append(self._make_important_value(
                    entry, source, msg, True
                ))
                return None, demoted
            if review:
                needs_review_flag = True

        if is_lineweaver_burk_context(evidence_text):
            needs_review_flag = True

        reject, review, msg = check_magnitude(param, numeric_val, unit)
        if reject:
            demoted.append(self._make_important_value(
                entry, source, msg, True
            ))
            return None, demoted
        if review:
            needs_review_flag = True

        if not review and not reject and self._paper_context:
            rlo, rhi = self._get_adjusted_review_range(param)
            if numeric_val < rlo or numeric_val > rhi:
                typical = sorted(
                    [v for v in [c * 1e-3 if u == "mM" else c * 1e-6 if u in ("μM", "uM") else c
                     for c, u in zip([numeric_val], [unit or "M"])] if v > 0]
                ) if False else [abs(numeric_val)]
                needs_review_flag = True
                logger.warning(
                    f"[NumericValidator] {param}={numeric_val} {unit} "
                    f"outside paper-specific review range ({rlo:.2e}–{rhi:.2e}). "
                    f"Paper context suggests different concentration scale."
                )

        if source == "figure_candidate":
            needs_review_flag = True

        if not unit:
            demoted.append(self._make_important_value(
                entry, source, "missing_unit", True
            ))
            self.warnings.append("numeric_validation_failed")
            return None, demoted

        formal = {
            "Km": None, "Km_unit": None,
            "Vmax": None, "Vmax_unit": None,
            "kcat": None, "kcat_unit": None,
            "kcat_Km": None, "kcat_Km_unit": None,
            "substrate": None, "source": None,
            "needs_review": needs_review_flag,
        }
        if param == "Km":
            formal["Km"] = numeric_val
            formal["Km_unit"] = normalize_unit(unit)
            formal["substrate"] = substrate
            formal["source"] = source
        elif param == "Vmax":
            formal["Vmax"] = numeric_val
            formal["Vmax_unit"] = normalize_unit(unit)
            formal["substrate"] = substrate
            formal["source"] = source
        elif param == "kcat":
            formal["kcat"] = numeric_val
            formal["kcat_unit"] = normalize_unit(unit)
            formal["substrate"] = substrate
            formal["source"] = source
        elif param == "kcat_Km":
            formal["kcat_Km"] = numeric_val
            formal["kcat_Km_unit"] = normalize_unit(unit)
            formal["substrate"] = substrate
            formal["source"] = source

        return formal, demoted

    def resolve_kinetics(
        self,
        candidates: List[Dict[str, Any]],
        selected_nanozyme: str,
        main_activity_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = {
            "Km": None, "Km_unit": None,
            "Vmax": None, "Vmax_unit": None,
            "kcat": None, "kcat_unit": None,
            "kcat_Km": None, "kcat_Km_unit": None,
            "substrate": None, "source": None,
            "needs_review": False,
        }
        all_demoted: List[Dict[str, Any]] = []

        km_candidates = [c for c in candidates if c.get("parameter") == "Km"]
        vmax_candidates = [c for c in candidates if c.get("parameter") == "Vmax"]
        kcat_candidates = [c for c in candidates if c.get("parameter") == "kcat"]
        kcat_km_candidates = [c for c in candidates if c.get("parameter") == "kcat_Km"]

        km_candidates.sort(key=lambda c: SOURCE_PRIORITY.get(classify_source(c), 0), reverse=True)
        vmax_candidates.sort(key=lambda c: SOURCE_PRIORITY.get(classify_source(c), 0), reverse=True)
        kcat_candidates.sort(key=lambda c: SOURCE_PRIORITY.get(classify_source(c), 0), reverse=True)
        kcat_km_candidates.sort(key=lambda c: SOURCE_PRIORITY.get(classify_source(c), 0), reverse=True)

        for km_entry in km_candidates:
            formal, demoted = self.validate_kinetics_entry(
                km_entry, selected_nanozyme, main_activity_type
            )
            all_demoted.extend(demoted)
            if formal and formal.get("Km") is not None:
                result["Km"] = formal["Km"]
                result["Km_unit"] = formal["Km_unit"]
                result["substrate"] = formal.get("substrate")
                result["source"] = formal.get("source")
                break

        for vmax_entry in vmax_candidates:
            formal, demoted = self.validate_kinetics_entry(
                vmax_entry, selected_nanozyme, main_activity_type
            )
            all_demoted.extend(demoted)
            if formal and formal.get("Vmax") is not None:
                result["Vmax"] = formal["Vmax"]
                result["Vmax_unit"] = formal["Vmax_unit"]
                if not result.get("substrate"):
                    result["substrate"] = formal.get("substrate")
                if not result.get("source"):
                    result["source"] = formal.get("source")
                break

        for kcat_entry in kcat_candidates:
            formal, demoted = self.validate_kinetics_entry(
                kcat_entry, selected_nanozyme, main_activity_type
            )
            all_demoted.extend(demoted)
            if formal and formal.get("kcat") is not None:
                result["kcat"] = formal["kcat"]
                result["kcat_unit"] = formal.get("kcat_unit")
                break

        for kcat_km_entry in kcat_km_candidates:
            formal, demoted = self.validate_kinetics_entry(
                kcat_km_entry, selected_nanozyme, main_activity_type
            )
            all_demoted.extend(demoted)
            if formal and formal.get("kcat_Km") is not None:
                result["kcat_Km"] = formal["kcat_Km"]
                result["kcat_Km_unit"] = formal.get("kcat_Km_unit")
                break

        self.important_values.extend(all_demoted)
        return result

    def validate_r_squared(self, value: Any) -> bool:
        if value is None:
            return True
        try:
            v = float(value)
            return 0 <= v <= 1
        except (ValueError, TypeError):
            return False

    def validate_lod(self, lod_entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        value = lod_entry.get("value") or lod_entry.get("detection_limit")
        unit = lod_entry.get("unit") or lod_entry.get("detection_limit_unit")
        target = lod_entry.get("target_analyte")
        if value is None:
            return None
        if not target:
            return self._make_important_value(
                lod_entry, classify_source(lod_entry),
                "LOD_missing_target_analyte", True
            )
        if not unit:
            return self._make_important_value(
                lod_entry, classify_source(lod_entry),
                "LOD_missing_unit", True
            )
        return None

    def validate_linear_range(self, lr_entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        low = lr_entry.get("linear_range_low") or lr_entry.get("low")
        high = lr_entry.get("linear_range_high") or lr_entry.get("high")
        unit = lr_entry.get("unit") or lr_entry.get("linear_range_unit")
        target = lr_entry.get("target_analyte")
        if low is None and high is None:
            return None
        if not target:
            return self._make_important_value(
                lr_entry, classify_source(lr_entry),
                "linear_range_missing_target_analyte", True
            )
        if not unit:
            return self._make_important_value(
                lr_entry, classify_source(lr_entry),
                "linear_range_missing_unit", True
            )
        return None

    def _make_important_value(
        self,
        entry: Dict[str, Any],
        source: str,
        reason: str,
        needs_review: bool,
    ) -> Dict[str, Any]:
        return {
            "parameter": entry.get("parameter", ""),
            "value": entry.get("value"),
            "unit": entry.get("unit"),
            "material": entry.get("material", ""),
            "substrate": entry.get("substrate"),
            "source": source,
            "reason": reason,
            "needs_review": needs_review,
            "evidence_text": entry.get("evidence_text", ""),
        }

    def get_warnings(self) -> List[str]:
        return list(dict.fromkeys(self.warnings))

    def get_important_values(self) -> List[Dict[str, Any]]:
        return self.important_values

    _NANOZYME_KM_RANGES = {
        "peroxidase-like": (0.001, 500, "mM"),
        "oxidase-like": (0.01, 200, "mM"),
        "catalase-like": (0.1, 1000, "mM"),
        "superoxide-dismutase-like": (0.01, 100, "mM"),
        "glucose-oxidase-like": (0.1, 500, "mM"),
        "haloperoxidase-like": (0.01, 100, "mM"),
        "phosphatase-like": (0.001, 200, "mM"),
        "laccase-like": (0.01, 50, "mM"),
        "nitroreductase-like": (0.001, 100, "mM"),
    }

    _NANOZYME_VMAX_RANGES = {
        "peroxidase-like": (1e-4, 1e6, "μM/s"),
        "oxidase-like": (1e-3, 1e5, "μM/s"),
        "catalase-like": (1e-2, 1e6, "μM/s"),
        "glucose-oxidase-like": (1e-3, 1e5, "μM/s"),
    }

    _ANALYTE_ENZYME_COMPATIBILITY = {
        "peroxidase-like": {"h2o2", "tmb", "abts", "opd", "dab", "glucose", "dopamine", "ascorbic acid"},
        "oxidase-like": {"glucose", "ascorbic acid", "uric acid", "cholesterol", "dopamine"},
        "catalase-like": {"h2o2"},
        "glucose-oxidase-like": {"glucose", "o2"},
        "superoxide-dismutase-like": {"superoxide", "o2-"},
        "haloperoxidase-like": {"br-", "i-", "h2o2"},
    }

    def validate_nanozyme_kinetics(self, record: Dict[str, Any]) -> List[str]:
        warnings = []
        ma = record.get("main_activity", {})
        etype = ma.get("enzyme_like_type", "")
        kin = ma.get("kinetics", {})

        if not isinstance(kin, dict) or not etype:
            return warnings

        km_range = self._NANOZYME_KM_RANGES.get(etype)
        if km_range:
            km_val = kin.get("Km")
            km_u = kin.get("Km_unit", "")
            if isinstance(km_val, (int, float)):
                km_mM = self._to_mM(km_val, km_u)
                if km_mM is not None:
                    lo, hi, _ = km_range
                    if km_mM < lo or km_mM > hi:
                        warnings.append(
                            f"Km={km_val} {km_u} ({km_mM:.4f} mM) outside typical range "
                            f"for {etype} ({lo}-{hi} mM)"
                        )

        vmax_range = self._NANOZYME_VMAX_RANGES.get(etype)
        if vmax_range:
            vmax_val = kin.get("Vmax")
            vmax_u = kin.get("Vmax_unit", "")
            if isinstance(vmax_val, (int, float)):
                vmax_uM = self._to_uM_per_s(vmax_val, vmax_u)
                if vmax_uM is not None:
                    lo, hi, _ = vmax_range
                    if vmax_uM < lo or vmax_uM > hi:
                        warnings.append(
                            f"Vmax={vmax_val} {vmax_u} ({vmax_uM:.4f} μM/s) outside typical range "
                            f"for {etype}"
                        )

        for i, kl in enumerate(ma.get("kinetics_list", [])):
            if not isinstance(kl, dict):
                continue
            if km_range:
                kl_km = kl.get("Km")
                kl_kmu = kl.get("Km_unit", "")
                if isinstance(kl_km, (int, float)):
                    kl_km_mM = self._to_mM(kl_km, kl_kmu)
                    if kl_km_mM is not None:
                        lo, hi, _ = km_range
                        if kl_km_mM < lo or kl_km_mM > hi:
                            warnings.append(
                                f"kinetics_list[{i}]: Km={kl_km} {kl_kmu} outside typical range for {etype}"
                            )

        for app in record.get("applications", []):
            if not isinstance(app, dict):
                continue
            analyte = app.get("target_analyte", "")
            if analyte and etype in self._ANALYTE_ENZYME_COMPATIBILITY:
                compat = self._ANALYTE_ENZYME_COMPATIBILITY[etype]
                if analyte.lower() not in {a.lower() for a in compat}:
                    warnings.append(
                        f"Analyte '{analyte}' may be incompatible with {etype} "
                        f"(expected: {', '.join(sorted(compat))})"
                    )

        return warnings

    def _to_mM(self, val: float, unit: str) -> Optional[float]:
        conversions = {"M": 1e3, "mM": 1.0, "μM": 1e-3, "uM": 1e-3, "nM": 1e-6, "pM": 1e-9}
        factor = conversions.get(unit)
        return val * factor if factor else None

    def _to_uM_per_s(self, val: float, unit: str) -> Optional[float]:
        conversions = {
            "M/s": 1e6, "M s^-1": 1e6, "M·s-1": 1e6,
            "mM/s": 1e3, "mM s^-1": 1e3, "mM·s-1": 1e3,
            "μM/s": 1.0, "uM/s": 1.0, "μM s^-1": 1.0,
            "nM/s": 1e-3, "nM s^-1": 1e-3,
            "μM/min": 1.0 / 60, "uM/min": 1.0 / 60,
        }
        factor = conversions.get(unit)
        return val * factor if factor else None
