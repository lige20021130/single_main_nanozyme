import re
import logging
from typing import Dict, List, Any, Optional

from dependencies import get_attr
from single_main_nanozyme_extractor import (
    _KM_PATTERNS, _KM_VMAX_JOINT_PATTERNS, _VMAX_PATTERNS, _VMAX_OCR_PATTERNS,
    _KCAT_PATTERNS, _KCAT_KM_PATTERNS, _LOD_PATTERNS, _LINEAR_RANGE_PATTERNS,
    _SYNTHESIS_METHODS, _SYNTHESIS_CONDITION_PATTERNS,
    _SIZE_PATTERNS, _CRYSTAL_STRUCTURE_PATTERNS, _SURFACE_AREA_PATTERNS,
    _ZETA_POTENTIAL_PATTERNS, _PORE_SIZE_PATTERNS,
    _PH_PATTERNS, _TEMPERATURE_PATTERNS,
    _ENZYME_TYPE_PATTERNS, _SUBSTRATE_KEYWORDS,
    _normalize_ocr_scientific, _parse_scientific_notation, _extract_vmax_fallback,
    _RATE_UNITS,
)

logger = logging.getLogger(__name__)

_normalize_unit_fn = get_attr("numeric_validator", "normalize_unit")
_is_concentration_unit_fn = get_attr("numeric_validator", "is_concentration_unit")
_is_rate_unit_fn = get_attr("numeric_validator", "is_rate_unit")


def _norm_unit(unit):
    if _normalize_unit_fn and unit:
        return _normalize_unit_fn(unit)
    return unit


_FULLTEXT_STABILITY_PATTERNS = [
    re.compile(r'\bstable\s+(?:for|over|during)\s*([\d.]+)\s*(days?|weeks?|months?|hours?|h)\b', re.I),
    re.compile(r'\bretained\s+(?:more\s+than\s+)?(\d+)\s*%?\s*(?:of\s+(?:its?\s+)?(?:original|initial)\s+activity)?\s*(?:after|for)\s*([\d.]+)\s*(days?|weeks?|months?|hours?|cycles?)', re.I),
    re.compile(r'\b(?:storage|long[-\s]?term)\s+stability\s*(?::|was|of)\s*(?:stable\s+)?(?:for\s+)?([\d.]+)\s*(days?|weeks?|months?|hours?)', re.I),
    re.compile(r'\bremained\s+([\d.]+)\s*%?\s*(?:of\s+(?:its?\s+)?(?:original|initial)\s+activity)?\s*(?:after|over)\s*([\d.]+)\s*(days?|weeks?|months?|cycles?)', re.I),
    re.compile(r'\b(?:good|excellent|high)\s+stability\b', re.I),
]

_FULLTEXT_REACTION_TIME_PATTERNS = [
    re.compile(r'\b(?:reaction|incubation|catalytic)\s+time\s*(?:of|was|=|:|≈|~)\s*(?:about\s+|approximately\s+)?([\d.]+)\s*(min|s|sec|h|hour|hr)', re.I),
    re.compile(r'\bincubated\s+(?:for|at)\s*(?:about\s+)?([\d.]+)\s*(min|s|sec|h|hour|hr)', re.I),
    re.compile(r'\b(?:after|within)\s*([\d.]+)\s*(min|s|sec|h|hour|hr)\s+(?:of\s+)?(?:reaction|incubation|catalysis)', re.I),
]

_FULLTEXT_MECHANISM_PATTERNS = [
    re.compile(r'\b(?:electron|radical|Fenton|Haber[-\s]?Weiss|Schottky|piezo|photo|sono|electro)cataly', re.I),
    re.compile(r'\bROS\s+(?:generation|production|mediat)', re.I),
    re.compile(r'\b(?:hydroxyl|superoxide|singlet\s+oxygen)\s+radical', re.I),
    re.compile(r'\b(?:oxygen\s+)?vacancy[-\s]*(?:mediated|induced|driven|catalyzed|promoted)', re.I),
    re.compile(r'\b(?:active\s+)?(?:site|center)s?\s+(?:for|of)\s+(?:cataly|oxid)', re.I),
    re.compile(r'\b(?:charge|electron)\s+transfer\b', re.I),
    re.compile(r'\b(?:catalytic|reaction)\s+mechanism\b', re.I),
    re.compile(r'\b(?:peroxidase|oxidase|catalase|SOD)\s*[-\s]*(?:like\s+)?(?:mechanism|pathway|process)', re.I),
]


def _is_concentration_unit(unit):
    if _is_concentration_unit_fn and unit:
        return _is_concentration_unit_fn(unit)
    if not unit:
        return False
    return bool(re.match(r'^[mμunp]?M$|^[mμunp]?mol', unit, re.I))


def _is_rate_unit(unit):
    if _is_rate_unit_fn and unit:
        return _is_rate_unit_fn(unit)
    if not unit:
        return False
    return bool(re.search(r'M\s*[sS]|M/?s|mM/?s|s[\u207b\-]1', unit, re.I))


class KineticsAgent:
    _METHOD_PRIORITY = {
        "uv-vis": 1, "uv/vis": 1, "uv vis": 1, "absorption": 1,
        "spectrophotometric": 1,
        "fluorescence": 2, "fluorometric": 2,
        "colorimetric": 2, "colorimetry": 2,
        "electrochemical": 3, "amperometric": 3,
        "sers": 4, "surface-enhanced": 4, "raman": 4,
        "other": 5,
    }

    def _detect_method(self, text):
        tl = text.lower()
        for key in self._METHOD_PRIORITY:
            if key in tl:
                return key
        return "other"

    def extract(self, record, buckets, table_values, selected_name, doc=None):
        if record["main_activity"]["kinetics"]["Km"] is None or record["main_activity"]["kinetics"]["Vmax"] is None:
            self._extract_kinetics_from_text(record, buckets.get("kinetics", []))
        if record["main_activity"]["kinetics"]["Km"] is None or record["main_activity"]["kinetics"]["Vmax"] is None:
            extended = list(buckets.get("kinetics", [])) + list(buckets.get("activity", []))
            seen = set()
            unique_extended = []
            for t in extended:
                if t not in seen:
                    seen.add(t)
                    unique_extended.append(t)
            self._extract_kinetics_from_text(record, unique_extended)
        if record["main_activity"]["kinetics"]["Km"] is None or record["main_activity"]["kinetics"]["Vmax"] is None:
            self._extract_kinetics_from_flattened_table(record, buckets.get("kinetics", []), selected_name)
        if record["main_activity"]["kinetics"]["Km"] is None and table_values:
            self._extract_kinetics_from_table(record, table_values)
        self._extract_kcat_from_text(record, buckets.get("kinetics", []))
        self._validate_kinetics_units(record)
        self._extract_specific_activity(record, buckets.get("activity", []) + buckets.get("kinetics", []))
        self._fill_kinetics_list(record, buckets.get("kinetics", []))
        return record

    _SPECIFIC_ACTIVITY_PATTERNS = [
        re.compile(r'\bspecific\s+activity\s*(?:of|was|=|:|≈|~)\s*(?:about\s+|approximately\s+)?([\d.]+)\s*([μu]?[MmNn]\s*[/·]\s*(?:min|s|hr|h))', re.I),
        re.compile(r'\bspecific\s+activity\s*(?:of|was|=|:|≈|~)\s*(?:about\s+|approximately\s+)?([\d.]+)\s*(U\s*/\s*(?:mg|g|mL))', re.I),
        re.compile(r'\b([\d.]+)\s*(U\s*/\s*(?:mg|g|mL))\s*(?:of\s+)?specific\s+activity', re.I),
        re.compile(r'\bspecific\s+activity\s*(?:reached|achieved|exhibited|showed)\s*(?:a\s+)?(?:value\s+)?(?:of\s+)?([\d.]+)\s*([μu]?[MmNn]\s*[/·]\s*(?:min|s|hr|h))', re.I),
        re.compile(r'\b([\d.]+)\s*(U\s*/\s*mg)\b', re.I),
    ]

    def _extract_specific_activity(self, record, texts):
        ivs = record.get("important_values", [])
        for iv in ivs:
            if iv.get("name", "").lower() == "specific activity":
                return
        for text in texts:
            for pat in self._SPECIFIC_ACTIVITY_PATTERNS:
                m = pat.search(text)
                if m:
                    val = m.group(1)
                    unit = m.group(2).replace(" ", "")
                    ivs.append({
                        "name": "specific activity",
                        "value": val,
                        "unit": unit,
                        "context": m.group(0)[:100],
                        "source": "rule",
                        "needs_review": False,
                    })
                    record["important_values"] = ivs
                    return

    _MULTI_KM_PATTERNS = [
        re.compile(r'\bKm\s*[\(（]\s*([\w\d\-/]+(?:\s[\w\d\-/]+){0,1})\s*[\)）]\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*(mM|μM|uM|M|nM|pM)', re.I),
        re.compile(r'\bKm\s*(?:for|of)\s+([\w\d\-/]+(?:\s[\w\d\-/]+){0,1})\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*(mM|μM|uM|M|nM|pM)', re.I),
        re.compile(r'\bKm\s*[\(（]\s*([\w\d\-/]+)\s*[\)）]\s*([\d.]+)\s*(mM|μM|uM|M|nM|pM)', re.I),
        re.compile(r'\b([\w\d\-/]+)\s*[-–]?\s*Km\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*(mM|μM|uM|M|nM|pM)', re.I),
        re.compile(r'\baffinity\s*(?:for|toward|to)\s+([\w\d\-/]+(?:\s[\w\d\-/]+){0,1})\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*(mM|μM|uM|M|nM|pM)', re.I),
    ]

    _MULTI_VMAX_PATTERNS = [
        re.compile(r'\bVmax\s*[\(（]\s*([\w\d\-/]+(?:\s[\w\d\-/]+){0,1})\s*[\)）]\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*([^\s,;)]+)', re.I),
        re.compile(r'\bVmax\s*(?:for|of)\s+([\w\d\-/]+(?:\s[\w\d\-/]+){0,1})\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*([^\s,;)]+)', re.I),
        re.compile(r'\bVmax\s*[\(（]\s*([\w\d\-/]+)\s*[\)）]\s*([\d.]+)\s*([^\s,;)]+)', re.I),
        re.compile(r'\b([\w\d\-/]+)\s*[-–]?\s*Vmax\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*([^\s,;)]+)', re.I),
    ]

    _MULTI_KCAT_PATTERNS = [
        re.compile(r'\bkcat\s*[\(（]\s*([\w\d\-/]+(?:\s[\w\d\-/]+){0,1})\s*[\)）]\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*([^\s,;)]+)', re.I),
        re.compile(r'\bkcat\s*(?:for|of)\s+([\w\d\-/]+(?:\s[\w\d\-/]+){0,1})\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*([^\s,;)]+)', re.I),
        re.compile(r'\bturnover\s+(?:frequency|number)\s*(?:for|of)\s+([\w\d\-/]+(?:\s[\w\d\-/]+){0,1})\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*([^\s,;)]+)', re.I),
    ]

    _MULTI_KCAT_KM_PATTERNS = [
        re.compile(r'\bkcat/Km\s*[\(（]\s*([\w\d\-/]+(?:\s[\w\d\-/]+){0,1})\s*[\)）]\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*([^\s,;)]+)', re.I),
        re.compile(r'\bcatalytic\s+efficiency\s*(?:for|of)\s+([\w\d\-/]+(?:\s[\w\d\-/]+){0,1})\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*([^\s,;)]+)', re.I),
    ]

    _JOINT_KM_VMAX_PATTERNS = [
        re.compile(r'\bKm\s*[\(（]\s*([\w\d\-/]+)\s*[\)）]\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*(mM|μM|uM|M|nM|pM)\s*[;,]\s*Vmax\s*[\(（]\s*([\w\d\-/]+)\s*[\)）]\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*([^\s,;)]+)', re.I),
        re.compile(r'\bKm\s*(?:for|of)\s+([\w\d\-/]+)\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*(mM|μM|uM|M|nM|pM)\s*[;,]\s*Vmax\s*(?:for|of)\s+([\w\d\-/]+)\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*([^\s,;)]+)', re.I),
    ]

    _ENZYME_TYPE_KM_PATTERNS = [
        re.compile(r'\bKm\s*[\(（]\s*(peroxidase|oxidase|catalase|SOD|GPx|GOx|laccase|phosphatase|esterase|haloperoxidase|NTR|hydrolase|nuclease|tyrosinase|catalytic)\s*[-\s]?\s*like\s*[\)）]\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*(mM|μM|uM|M)', re.I),
        re.compile(r'\bKm\s*(?:for|of)\s+(?:the\s+)?(peroxidase|oxidase|catalase|SOD|GPx|GOx|laccase|phosphatase|esterase|haloperoxidase|NTR|hydrolase|nuclease|tyrosinase|catalytic)\s*[-\s]?\s*like\s+activity\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*(mM|μM|uM|M)', re.I),
    ]

    _ENZYME_TYPE_VMAX_PATTERNS = [
        re.compile(r'\bVmax\s*[\(（]\s*(peroxidase|oxidase|catalase|SOD|GPx|GOx|laccase|phosphatase|esterase|haloperoxidase|NTR|hydrolase|nuclease|tyrosinase|catalytic)\s*[-\s]?\s*like\s*[\)）]\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*([^\s,;)]+)', re.I),
        re.compile(r'\bVmax\s*(?:for|of)\s+(?:the\s+)?(peroxidase|oxidase|catalase|SOD|GPx|GOx|laccase|phosphatase|esterase|haloperoxidase|NTR|hydrolase|nuclease|tyrosinase|catalytic)\s*[-\s]?\s*like\s+activity\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*([^\s,;)]+)', re.I),
    ]

    def _fill_kinetics_list(self, record, kinetics_texts):
        kin = record["main_activity"]["kinetics"]
        existing_list = record["main_activity"].get("kinetics_list", [])
        if existing_list:
            return

        entries = []
        main_km = kin.get("Km")
        main_vmax = kin.get("Vmax")
        main_kcat = kin.get("kcat")

        if main_km is not None or main_vmax is not None:
            entry = {}
            if main_km is not None:
                entry["Km"] = main_km
                entry["Km_unit"] = kin.get("Km_unit")
            if main_vmax is not None:
                entry["Vmax"] = main_vmax
                entry["Vmax_unit"] = kin.get("Vmax_unit")
            if main_kcat is not None:
                entry["kcat"] = main_kcat
                entry["kcat_unit"] = kin.get("kcat_unit")
            substrate = kin.get("substrate")
            if substrate:
                entry["substrate"] = substrate
            entries.append(entry)

        substrate_km = {}
        for text in kinetics_texts:
            norm_text = _normalize_ocr_scientific(text)
            for m in self._MULTI_KM_PATTERNS[0].finditer(norm_text):
                sub_name = m.group(1)
                km_val = m.group(2)
                km_unit = m.group(3)
                substrate_km.setdefault(sub_name, {"substrate": sub_name})
                substrate_km[sub_name]["Km"] = km_val
                substrate_km[sub_name]["Km_unit"] = km_unit
            for m in self._MULTI_KM_PATTERNS[1].finditer(norm_text):
                sub_name = m.group(1)
                km_val = m.group(2)
                km_unit = m.group(3)
                substrate_km.setdefault(sub_name, {"substrate": sub_name})
                substrate_km[sub_name]["Km"] = km_val
                substrate_km[sub_name]["Km_unit"] = km_unit
            for m in self._MULTI_KM_PATTERNS[2].finditer(norm_text):
                sub_name = m.group(1)
                km_val = m.group(2)
                km_unit = m.group(3)
                if sub_name not in substrate_km:
                    substrate_km[sub_name] = {"substrate": sub_name, "Km": km_val, "Km_unit": km_unit}
            for m in self._MULTI_KM_PATTERNS[3].finditer(norm_text):
                sub_name = m.group(1)
                km_val = m.group(2)
                km_unit = m.group(3)
                substrate_km.setdefault(sub_name, {"substrate": sub_name})
                substrate_km[sub_name]["Km"] = km_val
                substrate_km[sub_name]["Km_unit"] = km_unit
            for m in self._MULTI_KM_PATTERNS[4].finditer(norm_text):
                sub_name = m.group(1)
                km_val = m.group(2)
                km_unit = m.group(3)
                substrate_km.setdefault(sub_name, {"substrate": sub_name})
                substrate_km[sub_name]["Km"] = km_val
                substrate_km[sub_name]["Km_unit"] = km_unit

            for m in self._MULTI_VMAX_PATTERNS[0].finditer(norm_text):
                sub_name = m.group(1)
                vmax_val = m.group(2)
                vmax_unit = m.group(3)
                substrate_km.setdefault(sub_name, {"substrate": sub_name})
                substrate_km[sub_name]["Vmax"] = vmax_val
                substrate_km[sub_name]["Vmax_unit"] = vmax_unit
            for m in self._MULTI_VMAX_PATTERNS[1].finditer(norm_text):
                sub_name = m.group(1)
                vmax_val = m.group(2)
                vmax_unit = m.group(3)
                substrate_km.setdefault(sub_name, {"substrate": sub_name})
                substrate_km[sub_name]["Vmax"] = vmax_val
                substrate_km[sub_name]["Vmax_unit"] = vmax_unit
            for m in self._MULTI_VMAX_PATTERNS[2].finditer(norm_text):
                sub_name = m.group(1)
                vmax_val = m.group(2)
                vmax_unit = m.group(3)
                substrate_km.setdefault(sub_name, {"substrate": sub_name})
                substrate_km[sub_name].setdefault("Vmax", vmax_val)
                substrate_km[sub_name].setdefault("Vmax_unit", vmax_unit)
            for m in self._MULTI_VMAX_PATTERNS[3].finditer(norm_text):
                sub_name = m.group(1)
                vmax_val = m.group(2)
                vmax_unit = m.group(3)
                substrate_km.setdefault(sub_name, {"substrate": sub_name})
                substrate_km[sub_name]["Vmax"] = vmax_val
                substrate_km[sub_name]["Vmax_unit"] = vmax_unit

            for m in self._MULTI_KCAT_PATTERNS[0].finditer(norm_text):
                sub_name = m.group(1)
                kcat_val = m.group(2)
                kcat_unit = m.group(3)
                substrate_km.setdefault(sub_name, {"substrate": sub_name})
                substrate_km[sub_name]["kcat"] = kcat_val
                substrate_km[sub_name]["kcat_unit"] = kcat_unit
            for m in self._MULTI_KCAT_PATTERNS[1].finditer(norm_text):
                sub_name = m.group(1)
                kcat_val = m.group(2)
                kcat_unit = m.group(3)
                substrate_km.setdefault(sub_name, {"substrate": sub_name})
                substrate_km[sub_name]["kcat"] = kcat_val
                substrate_km[sub_name]["kcat_unit"] = kcat_unit
            for m in self._MULTI_KCAT_PATTERNS[2].finditer(norm_text):
                sub_name = m.group(1)
                kcat_val = m.group(2)
                kcat_unit = m.group(3)
                substrate_km.setdefault(sub_name, {"substrate": sub_name})
                substrate_km[sub_name].setdefault("kcat", kcat_val)
                substrate_km[sub_name].setdefault("kcat_unit", kcat_unit)

            for m in self._MULTI_KCAT_KM_PATTERNS[0].finditer(norm_text):
                sub_name = m.group(1)
                kcat_km_val = m.group(2)
                kcat_km_unit = m.group(3)
                substrate_km.setdefault(sub_name, {"substrate": sub_name})
                substrate_km[sub_name]["kcat_Km"] = kcat_km_val
                substrate_km[sub_name]["kcat_Km_unit"] = kcat_km_unit
            for m in self._MULTI_KCAT_KM_PATTERNS[1].finditer(norm_text):
                sub_name = m.group(1)
                kcat_km_val = m.group(2)
                kcat_km_unit = m.group(3)
                substrate_km.setdefault(sub_name, {"substrate": sub_name})
                substrate_km[sub_name].setdefault("kcat_Km", kcat_km_val)
                substrate_km[sub_name].setdefault("kcat_Km_unit", kcat_km_unit)

            for m in self._JOINT_KM_VMAX_PATTERNS[0].finditer(norm_text):
                sub1 = m.group(1)
                km_val = m.group(2)
                km_unit = m.group(3)
                sub2 = m.group(4)
                vmax_val = m.group(5)
                vmax_unit = m.group(6)
                substrate_km.setdefault(sub1, {"substrate": sub1})
                substrate_km[sub1]["Km"] = km_val
                substrate_km[sub1]["Km_unit"] = km_unit
                if sub2 == sub1 or not sub2:
                    substrate_km[sub1]["Vmax"] = vmax_val
                    substrate_km[sub1]["Vmax_unit"] = vmax_unit
                else:
                    substrate_km.setdefault(sub2, {"substrate": sub2})
                    substrate_km[sub2]["Vmax"] = vmax_val
                    substrate_km[sub2]["Vmax_unit"] = vmax_unit
            for m in self._JOINT_KM_VMAX_PATTERNS[1].finditer(norm_text):
                sub1 = m.group(1)
                km_val = m.group(2)
                km_unit = m.group(3)
                sub2 = m.group(4)
                vmax_val = m.group(5)
                vmax_unit = m.group(6)
                substrate_km.setdefault(sub1, {"substrate": sub1})
                substrate_km[sub1]["Km"] = km_val
                substrate_km[sub1]["Km_unit"] = km_unit
                if sub2 == sub1 or not sub2:
                    substrate_km[sub1]["Vmax"] = vmax_val
                    substrate_km[sub1]["Vmax_unit"] = vmax_unit
                else:
                    substrate_km.setdefault(sub2, {"substrate": sub2})
                    substrate_km[sub2]["Vmax"] = vmax_val
                    substrate_km[sub2]["Vmax_unit"] = vmax_unit

        enzyme_type_kinetics = {}
        for text in kinetics_texts:
            norm_text = _normalize_ocr_scientific(text)
            for m in self._ENZYME_TYPE_KM_PATTERNS[0].finditer(norm_text):
                etype = m.group(1).lower() + "-like"
                km_val = m.group(2)
                km_unit = m.group(3)
                enzyme_type_kinetics.setdefault(etype, {"enzyme_type": etype})
                enzyme_type_kinetics[etype]["Km"] = km_val
                enzyme_type_kinetics[etype]["Km_unit"] = km_unit
            for m in self._ENZYME_TYPE_KM_PATTERNS[1].finditer(norm_text):
                etype = m.group(1).lower() + "-like"
                km_val = m.group(2)
                km_unit = m.group(3)
                enzyme_type_kinetics.setdefault(etype, {"enzyme_type": etype})
                enzyme_type_kinetics[etype]["Km"] = km_val
                enzyme_type_kinetics[etype]["Km_unit"] = km_unit
            for m in self._ENZYME_TYPE_VMAX_PATTERNS[0].finditer(norm_text):
                etype = m.group(1).lower() + "-like"
                vmax_val = m.group(2)
                vmax_unit = m.group(3)
                enzyme_type_kinetics.setdefault(etype, {"enzyme_type": etype})
                enzyme_type_kinetics[etype]["Vmax"] = vmax_val
                enzyme_type_kinetics[etype]["Vmax_unit"] = vmax_unit
            for m in self._ENZYME_TYPE_VMAX_PATTERNS[1].finditer(norm_text):
                etype = m.group(1).lower() + "-like"
                vmax_val = m.group(2)
                vmax_unit = m.group(3)
                enzyme_type_kinetics.setdefault(etype, {"enzyme_type": etype})
                enzyme_type_kinetics[etype]["Vmax"] = vmax_val
                enzyme_type_kinetics[etype]["Vmax_unit"] = vmax_unit

        for sub_name, data in substrate_km.items():
            already = any(e.get("substrate") == sub_name for e in entries)
            if not already:
                entries.append(data)

        for etype, data in enzyme_type_kinetics.items():
            already = any(e.get("enzyme_type") == etype for e in entries)
            if not already:
                entries.append(data)

        if entries:
            record["main_activity"]["kinetics_list"] = entries

    def _validate_kinetics_units(self, record):
        kin = record["main_activity"]["kinetics"]
        km_unit = kin.get("Km_unit")
        if km_unit and _is_rate_unit(km_unit) and not _is_concentration_unit(km_unit):
            logger.warning(f"[KineticsAgent] Km_unit='{km_unit}' is a rate unit, clearing.")
            kin["Km_unit"] = None
            kin["needs_review"] = True
        vmax_unit = kin.get("Vmax_unit")
        if vmax_unit and _is_concentration_unit(vmax_unit) and not _is_rate_unit(vmax_unit):
            logger.warning(f"[KineticsAgent] Vmax_unit='{vmax_unit}' is a concentration unit, clearing.")
            kin["Vmax_unit"] = None
            kin["needs_review"] = True

    def _extract_kinetics_from_text(self, record, kinetics_texts):
        km_candidates = []
        vmax_candidates = []

        for idx, text in enumerate(kinetics_texts):
            norm_text = _normalize_ocr_scientific(text)
            method = self._detect_method(text)
            method_pri = self._METHOD_PRIORITY.get(method, 5)
            matched_vmax = False

            for pat in _KM_VMAX_JOINT_PATTERNS:
                m = pat.search(text)
                if not m:
                    m = pat.search(norm_text)
                if m:
                    g1_val = _parse_scientific_notation(m.group(1))
                    g2_unit = m.group(2)
                    g3_val = _parse_scientific_notation(m.group(3))
                    g4_unit = m.group(4)
                    g1_is_conc = _is_concentration_unit(g2_unit)
                    g3_is_rate = _is_rate_unit(g4_unit)
                    g1_is_rate = _is_rate_unit(g2_unit)
                    g3_is_conc = _is_concentration_unit(g4_unit)
                    if g1_is_conc and g3_is_rate:
                        km_val, km_unit = g1_val, g2_unit
                        vmax_val, vmax_unit = g3_val, g4_unit
                    elif g1_is_rate and g3_is_conc:
                        km_val, km_unit = g3_val, g4_unit
                        vmax_val, vmax_unit = g1_val, g2_unit
                    else:
                        km_val, km_unit = g1_val, g2_unit
                        vmax_val, vmax_unit = g3_val, g4_unit
                    if isinstance(km_val, (int, float)):
                        km_candidates.append((method_pri, km_val, km_unit, "text"))
                    if isinstance(vmax_val, (int, float)):
                        vmax_candidates.append((method_pri, vmax_val, vmax_unit, "text"))
                    break

            for pat in _KM_PATTERNS:
                m = pat.search(text)
                if not m:
                    m = pat.search(norm_text)
                if m:
                    groups = m.groups()
                    if len(groups) == 3:
                        if groups[0] in ("mM", "μM", "uM", "M", "mmol", "umol", "nmol"):
                            value, unit = groups[1], groups[0]
                        else:
                            value, unit = groups[0], groups[2]
                    elif len(groups) == 2:
                        value, unit = groups
                    else:
                        continue
                    try:
                        km_candidates.append((method_pri, float(value), unit, "text"))
                    except ValueError:
                        pass
                    break

            for pat in _VMAX_PATTERNS:
                m = pat.search(text)
                if not m:
                    m = pat.search(norm_text)
                if m:
                    groups = m.groups()
                    if len(groups) == 2:
                        g0, g1 = groups
                        g0_is_unit = g0 in _RATE_UNITS or bool(re.match(r'10[−\-–]?\d*\s*M\s*[sS]', g0)) or bool(re.match(r'[mμunp]?M[·\s]*s[⁻\-–]1', g0))
                        g1_is_unit = g1 in _RATE_UNITS or bool(re.match(r'10[−\-–]?\d*\s*M\s*[sS]', g1)) or bool(re.match(r'[mμunp]?M[·\s]*s[⁻\-–]1', g1))
                        if g1_is_unit and not g0_is_unit:
                            value, unit = g0, g1
                        elif g0_is_unit:
                            value, unit = g1, g0
                        else:
                            value, unit = g0, None
                    elif len(groups) == 3:
                        value, unit = groups[1], groups[2]
                    else:
                        continue
                    vmax_val = _parse_scientific_notation(value.strip())
                    if isinstance(vmax_val, (int, float)):
                        vmax_candidates.append((method_pri, vmax_val, unit, "text"))
                        matched_vmax = True
                    break

            if not matched_vmax:
                fallback = _extract_vmax_fallback(text)
                if fallback and isinstance(fallback.get("value"), (int, float)):
                    vmax_candidates.append((method_pri, fallback["value"], fallback.get("unit"), fallback.get("source", "text_ocr_fallback")))

        _filtered_km = []
        for c in km_candidates:
            val, unit = c[1], c[2]
            if isinstance(val, (int, float)):
                if val > 100 and not (unit and _is_concentration_unit(unit) and unit.lower().startswith(('m', 'μ', 'u', 'n', 'p'))):
                    logger.warning(f"[KineticsAgent] Km={val} {unit} seems too large (>100), likely not a valid Km. Skipping.")
                    continue
                if val <= 0:
                    continue
            _filtered_km.append(c)
        km_candidates = _filtered_km if _filtered_km else km_candidates

        _filtered_vmax = []
        for c in vmax_candidates:
            val, unit = c[1], c[2]
            if isinstance(val, (int, float)):
                if val > 1e6:
                    logger.warning(f"[KineticsAgent] Vmax={val} {unit} seems too large, likely not a valid Vmax. Skipping.")
                    continue
                if val <= 0:
                    continue
            _filtered_vmax.append(c)
        vmax_candidates = _filtered_vmax if _filtered_vmax else vmax_candidates

        kin = record["main_activity"]["kinetics"]
        if km_candidates and kin.get("Km") is None:
            km_candidates.sort(key=lambda c: c[0])
            best = km_candidates[0]
            kin["Km"] = best[1]
            raw_km_unit = best[2]
            if raw_km_unit and _is_concentration_unit(raw_km_unit):
                kin["Km_unit"] = _norm_unit(raw_km_unit) or raw_km_unit
            elif raw_km_unit and _is_rate_unit(raw_km_unit):
                logger.warning(f"[KineticsAgent] Rule Km_unit='{raw_km_unit}' is a rate unit, not concentration. Clearing.")
                kin["Km_unit"] = None
            else:
                kin["Km_unit"] = _norm_unit(raw_km_unit) if raw_km_unit else raw_km_unit
            kin["source"] = best[3]
            if len(km_candidates) > 1:
                logger.info(f"[KineticsAgent] Km multi-method: picked {best[1]} {best[2]} (pri={best[0]}) from {len(km_candidates)} candidates")

        if vmax_candidates and kin.get("Vmax") is None:
            vmax_candidates.sort(key=lambda c: c[0])
            best = vmax_candidates[0]
            kin["Vmax"] = best[1]
            raw_vmax_unit = best[2]
            if raw_vmax_unit and _is_rate_unit(raw_vmax_unit):
                kin["Vmax_unit"] = _norm_unit(raw_vmax_unit) or raw_vmax_unit
            elif raw_vmax_unit and _is_concentration_unit(raw_vmax_unit):
                logger.warning(f"[KineticsAgent] Rule Vmax_unit='{raw_vmax_unit}' is a concentration unit, not rate. Clearing.")
                kin["Vmax_unit"] = None
            else:
                kin["Vmax_unit"] = _norm_unit(raw_vmax_unit) if raw_vmax_unit else raw_vmax_unit
            kin["source"] = best[3]
            if len(vmax_candidates) > 1:
                logger.info(f"[KineticsAgent] Vmax multi-method: picked {best[1]} {best[2]} (pri={best[0]}) from {len(vmax_candidates)} candidates")

    def _extract_kinetics_from_flattened_table(self, record, kinetics_texts, selected_name):
        _FLAT_KM_HEADER = re.compile(r'Km\s*[\(（]\s*(mM|μM|uM|M|mmol|umol|nmol)\s*[\)）]', re.I)
        _FLAT_VMAX_HEADER = re.compile(r'Vmax\s*[\(（\[]\s*([^\)）\]]+)\s*[\)）\]]', re.I)
        _FLAT_SUBSTRATE_HEADER = re.compile(r'Substrate', re.I)
        _FLAT_CATALYST_HEADER = re.compile(r'Catalyst|Nanozyme|Material', re.I)
        _NUM_RE = re.compile(r'[\d.]+')

        all_texts = list(kinetics_texts)
        for text in kinetics_texts:
            table_refs = re.findall(r'Table\s+S?\d+', text, re.I)
            if table_refs:
                for ref in table_refs:
                    for other_text in kinetics_texts:
                        if other_text != text and ref.lower() in other_text.lower() and other_text not in all_texts:
                            all_texts.append(other_text)

        for text in all_texts:
            norm_text = _normalize_ocr_scientific(text)
            lines = norm_text.strip().split('\n')
            if len(lines) < 2:
                single_line = self._try_parse_inline_table(text, selected_name, record)
                if single_line:
                    return
                continue

            header = lines[0]
            km_h = _FLAT_KM_HEADER.search(header)
            vmax_h = _FLAT_VMAX_HEADER.search(header)
            if not km_h and not vmax_h:
                continue

            km_unit = km_h.group(1) if km_h else None
            vmax_unit_raw = vmax_h.group(1).strip() if vmax_h else None
            has_substrate_col = bool(_FLAT_SUBSTRATE_HEADER.search(header))
            has_catalyst_col = bool(_FLAT_CATALYST_HEADER.search(header))
            header_parts = re.split(r'\s{2,}|\t', header)
            col_count = len(header_parts)

            for line in lines[1:]:
                parts = re.split(r'\s{2,}|\t', line.strip())
                if len(parts) < 2:
                    continue
                line_lower = line.lower()
                name_lower = selected_name.lower().replace(" ", "")
                line_compact = line_lower.replace(" ", "").replace("-", "")
                is_match = (name_lower in line_compact or selected_name.lower() in line_lower or "this work" in line_lower or "our" in line_lower)
                if not is_match and has_catalyst_col:
                    continue
                if not is_match and col_count <= 3:
                    continue

                if km_h and record["main_activity"]["kinetics"]["Km"] is None:
                    km_idx = None
                    for i, hp in enumerate(header_parts):
                        if re.search(r'\bKm\b', hp, re.I):
                            km_idx = i
                            break
                    if km_idx is not None and km_idx < len(parts):
                        try:
                            km_val = float(parts[km_idx])
                            record["main_activity"]["kinetics"]["Km"] = km_val
                            nu = _norm_unit(km_unit)
                            record["main_activity"]["kinetics"]["Km_unit"] = nu if nu else km_unit
                            record["main_activity"]["kinetics"]["source"] = "text"
                        except ValueError:
                            pass

                if vmax_h and record["main_activity"]["kinetics"]["Vmax"] is None:
                    vmax_idx = None
                    for i, hp in enumerate(header_parts):
                        if re.search(r'\bVmax\b', hp, re.I):
                            vmax_idx = i
                            break
                    if vmax_idx is not None and vmax_idx < len(parts):
                        raw_vmax = parts[vmax_idx].strip()
                        vmax_parsed = _parse_scientific_notation(raw_vmax)
                        if isinstance(vmax_parsed, (int, float)):
                            record["main_activity"]["kinetics"]["Vmax"] = vmax_parsed
                            nu = _norm_unit(vmax_unit_raw)
                            record["main_activity"]["kinetics"]["Vmax_unit"] = nu if nu else vmax_unit_raw
                            record["main_activity"]["kinetics"]["source"] = "text"
                        else:
                            norm_vmax = _normalize_ocr_scientific(raw_vmax)
                            vmax_parsed2 = _parse_scientific_notation(norm_vmax)
                            if isinstance(vmax_parsed2, (int, float)):
                                record["main_activity"]["kinetics"]["Vmax"] = vmax_parsed2
                                nu = _norm_unit(vmax_unit_raw)
                                record["main_activity"]["kinetics"]["Vmax_unit"] = nu if nu else vmax_unit_raw
                                record["main_activity"]["kinetics"]["source"] = "text"

                if has_substrate_col and not record["main_activity"]["kinetics"]["substrate"]:
                    sub_idx = None
                    for i, hp in enumerate(header_parts):
                        if re.search(r'Substrate', hp, re.I):
                            sub_idx = i
                            break
                    if sub_idx is not None and sub_idx < len(parts):
                        sub_val = parts[sub_idx].strip()
                        if sub_val and len(sub_val) < 20:
                            record["main_activity"]["kinetics"]["substrate"] = sub_val

                if record["main_activity"]["kinetics"]["Km"] is not None:
                    return

        kin = record["main_activity"]["kinetics"]
        if kin.get("Km") is None or kin.get("Vmax") is None:
            for text in all_texts:
                norm_text = _normalize_ocr_scientific(text)
                if kin.get("Km") is None:
                    for pat in _KM_PATTERNS:
                        m = pat.search(norm_text)
                        if m:
                            groups = m.groups()
                            try:
                                if len(groups) >= 2:
                                    km_val = _parse_scientific_notation(str(groups[0]))
                                    km_unit = groups[-1]
                                    if isinstance(km_val, (int, float)) and km_val > 0:
                                        kin["Km"] = km_val
                                        if km_unit:
                                            nu = _norm_unit(km_unit)
                                            kin["Km_unit"] = nu if nu else km_unit
                                        kin["source"] = "flattened_table_regex"
                                        break
                            except (ValueError, TypeError, IndexError):
                                pass
                    if kin.get("Km") is not None:
                        break

            for text in all_texts:
                norm_text = _normalize_ocr_scientific(text)
                if kin.get("Vmax") is None:
                    for pat in _VMAX_PATTERNS:
                        m = pat.search(norm_text)
                        if m:
                            groups = m.groups()
                            try:
                                if len(groups) >= 2:
                                    vmax_val = _parse_scientific_notation(str(groups[0]))
                                    vmax_unit = groups[-1]
                                    if isinstance(vmax_val, (int, float)) and vmax_val > 0:
                                        kin["Vmax"] = vmax_val
                                        if vmax_unit:
                                            nu = _norm_unit(vmax_unit)
                                            kin["Vmax_unit"] = nu if nu else vmax_unit
                                        kin["source"] = "flattened_table_regex"
                                        break
                            except (ValueError, TypeError, IndexError):
                                pass
                    if kin.get("Vmax") is not None:
                        break

    def _try_parse_inline_table(self, text, selected_name, record):
        km_header_m = re.search(r'Km\s*[\(（]\s*(mM|μM|uM|M|mmol|umol|nmol)\s*[\)）]', text, re.I)
        vmax_header_m = re.search(r'Vmax\s*[\(（\[]\s*([^\)）\]]+?)\s*[\)）\]]', text, re.I)
        if not km_header_m and not vmax_header_m:
            return False
        km_unit = km_header_m.group(1) if km_header_m else None
        vmax_unit = vmax_header_m.group(1).strip() if vmax_header_m else None
        header_end = max(km_header_m.end() if km_header_m else 0, vmax_header_m.end() if vmax_header_m else 0)
        data_part = text[header_end:].strip()
        name_lower = selected_name.lower()
        name_variants = [name_lower, name_lower.replace(" ", "")]
        for prefix in ["nanosized ", "nano ", "the "]:
            if name_lower.startswith(prefix):
                name_variants.append(name_lower[len(prefix):])
        pattern_str = r'(?:' + '|'.join(re.escape(nv) for nv in name_variants if nv) + r')'
        catalyst_m = re.search(pattern_str, data_part, re.I)
        if not catalyst_m:
            if "this work" in data_part.lower():
                catalyst_m = re.search(r'[\w\s]*?this work', data_part, re.I)
        if not catalyst_m:
            return False
        after_catalyst = data_part[catalyst_m.start():]
        nums = re.findall(r'([\d.]+)', after_catalyst)
        if len(nums) >= 2:
            if vmax_header_m and km_header_m:
                try:
                    vmax_val = float(nums[0])
                    km_val = float(nums[1])
                    record["main_activity"]["kinetics"]["Km"] = km_val
                    nu = _norm_unit(km_unit)
                    record["main_activity"]["kinetics"]["Km_unit"] = nu if nu else km_unit
                    record["main_activity"]["kinetics"]["Vmax"] = vmax_val
                    nu = _norm_unit(vmax_unit)
                    record["main_activity"]["kinetics"]["Vmax_unit"] = nu if nu else vmax_unit
                    record["main_activity"]["kinetics"]["source"] = "text"
                    return True
                except ValueError:
                    pass
            elif km_header_m:
                try:
                    km_val = float(nums[0])
                    record["main_activity"]["kinetics"]["Km"] = km_val
                    nu = _norm_unit(km_unit)
                    record["main_activity"]["kinetics"]["Km_unit"] = nu if nu else km_unit
                    record["main_activity"]["kinetics"]["source"] = "text"
                    return True
                except ValueError:
                    pass
        return False

    def _extract_kinetics_from_table(self, record, table_values):
        for val in table_values:
            param = val.get("parameter", "")
            if param == "Km" and record["main_activity"]["kinetics"]["Km"] is None:
                try:
                    record["main_activity"]["kinetics"]["Km"] = float(val["value"])
                    nu = _norm_unit(val.get("unit"))
                    record["main_activity"]["kinetics"]["Km_unit"] = nu if nu else val.get("unit")
                    record["main_activity"]["kinetics"]["substrate"] = val.get("substrate")
                    record["main_activity"]["kinetics"]["source"] = "table"
                except (ValueError, TypeError):
                    pass
            elif param == "Vmax" and record["main_activity"]["kinetics"]["Vmax"] is None:
                try:
                    record["main_activity"]["kinetics"]["Vmax"] = float(val["value"])
                except (ValueError, TypeError):
                    record["main_activity"]["kinetics"]["Vmax"] = val["value"]
                nu = _norm_unit(val.get("unit"))
                record["main_activity"]["kinetics"]["Vmax_unit"] = nu if nu else val.get("unit")
                record["main_activity"]["kinetics"]["source"] = "table"
            elif param in ("kcat", "Kcat", "k_cat") and record["main_activity"]["kinetics"]["kcat"] is None:
                try:
                    parsed = _parse_scientific_notation(str(val["value"]))
                    if isinstance(parsed, (int, float)):
                        record["main_activity"]["kinetics"]["kcat"] = parsed
                        raw_u = val.get("unit", "s^-1")
                        nu = _norm_unit(raw_u)
                        record["main_activity"]["kinetics"]["kcat_unit"] = nu if nu else raw_u
                        record["main_activity"]["kinetics"]["source"] = "table"
                except (ValueError, TypeError):
                    pass
            elif param in ("kcat/Km", "kcat_Km", "Kcat/Km", "catalytic_efficiency") and record["main_activity"]["kinetics"]["kcat_Km"] is None:
                try:
                    parsed = _parse_scientific_notation(str(val["value"]))
                    if isinstance(parsed, (int, float)):
                        record["main_activity"]["kinetics"]["kcat_Km"] = parsed
                        raw_u = val.get("unit", "M^-1 s^-1")
                        nu = _norm_unit(raw_u)
                        record["main_activity"]["kinetics"]["kcat_Km_unit"] = nu if nu else raw_u
                        record["main_activity"]["kinetics"]["source"] = "table"
                except (ValueError, TypeError):
                    pass

        if record["main_activity"]["kinetics"]["Km"] is not None:
            return

        for val in table_values:
            raw_text = val.get("raw_text", "") or val.get("text", "")
            if not raw_text:
                continue
            for pat in _KM_PATTERNS:
                m = pat.search(raw_text)
                if m:
                    groups = m.groups()
                    try:
                        if len(groups) >= 2:
                            km_val = _parse_scientific_notation(str(groups[-2] if len(groups) >= 3 else groups[0]))
                            km_unit = groups[-1] if groups[-1] else None
                            if isinstance(km_val, (int, float)):
                                record["main_activity"]["kinetics"]["Km"] = km_val
                                if km_unit:
                                    nu = _norm_unit(km_unit)
                                    record["main_activity"]["kinetics"]["Km_unit"] = nu if nu else km_unit
                                record["main_activity"]["kinetics"]["source"] = "table_regex"
                                break
                    except (ValueError, TypeError, IndexError):
                        pass
            if record["main_activity"]["kinetics"]["Km"] is not None:
                break

    def _extract_kcat_from_text(self, record, kinetics_texts):
        for text in kinetics_texts:
            norm_text = _normalize_ocr_scientific(text)
            if record["main_activity"]["kinetics"]["kcat"] is None:
                for pat in _KCAT_PATTERNS:
                    m = pat.search(text)
                    if not m:
                        m = pat.search(norm_text)
                    if m:
                        groups = m.groups()
                        if len(groups) == 3:
                            substrate, value, unit = groups
                        elif len(groups) == 2:
                            value, unit = groups
                            substrate = None
                        else:
                            continue
                        parsed = _parse_scientific_notation(value.strip())
                        if isinstance(parsed, (int, float)):
                            record["main_activity"]["kinetics"]["kcat"] = parsed
                            nu = _norm_unit(unit)
                            record["main_activity"]["kinetics"]["kcat_unit"] = nu if nu else unit
                            if substrate and not record["main_activity"]["kinetics"]["substrate"]:
                                record["main_activity"]["kinetics"]["substrate"] = substrate
                            break

            if record["main_activity"]["kinetics"]["kcat"] is None:
                e_m = re.search(r'\bkcat\b[^.=]{0,20}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)', norm_text, re.I)
                if not e_m:
                    e_m = re.search(r'\bkcat\b[^.=]{0,20}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)', text, re.I)
                if e_m:
                    try:
                        base = float(e_m.group(1))
                        exp = int(e_m.group(2).replace('−', '-').replace('\u2212', '-'))
                        kcat_val = base * (10 ** exp)
                        if 1e-3 <= kcat_val <= 1e8:
                            record["main_activity"]["kinetics"]["kcat"] = kcat_val
                            nu = _norm_unit("s^-1")
                            record["main_activity"]["kinetics"]["kcat_unit"] = nu if nu else "s^-1"
                            logger.info(f"[KineticsAgent] kcat E-notation: {base}e{exp} = {kcat_val:.2e}")
                    except (ValueError, TypeError):
                        pass

            if record["main_activity"]["kinetics"]["kcat_Km"] is None:
                for pat in _KCAT_KM_PATTERNS:
                    m = pat.search(text)
                    if not m:
                        m = pat.search(norm_text)
                    if m:
                        groups = m.groups()
                        if len(groups) == 3:
                            substrate, value, unit = groups
                        elif len(groups) == 2:
                            value, unit = groups
                            substrate = None
                        else:
                            continue
                        parsed = _parse_scientific_notation(value.strip())
                        if isinstance(parsed, (int, float)):
                            record["main_activity"]["kinetics"]["kcat_Km"] = parsed
                            nu = _norm_unit(unit)
                            record["main_activity"]["kinetics"]["kcat_Km_unit"] = nu if nu else unit
                            break

            if record["main_activity"]["kinetics"]["kcat_Km"] is None:
                eff_m = re.search(r'\bcatalytic\s+efficiency\b[^.=]{0,30}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)', norm_text, re.I)
                if not eff_m:
                    eff_m = re.search(r'\bcatalytic\s+efficiency\b[^.=]{0,30}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)', text, re.I)
                if eff_m:
                    try:
                        base = float(eff_m.group(1))
                        exp = int(eff_m.group(2).replace('−', '-').replace('\u2212', '-'))
                        kcat_km_val = base * (10 ** exp)
                        if 1e0 <= kcat_km_val <= 1e12:
                            record["main_activity"]["kinetics"]["kcat_Km"] = kcat_km_val
                            nu = _norm_unit("M^-1 s^-1")
                            record["main_activity"]["kinetics"]["kcat_Km_unit"] = nu if nu else "M^-1 s^-1"
                    except (ValueError, TypeError):
                        pass

        if record["main_activity"]["kinetics"]["kcat"] is None:
            kcat_km = record["main_activity"]["kinetics"].get("kcat_Km")
            km = record["main_activity"]["kinetics"].get("Km")
            km_unit = record["main_activity"]["kinetics"].get("Km_unit", "")
            if kcat_km and km and isinstance(kcat_km, (int, float)) and isinstance(km, (int, float)) and km > 0:
                km_in_M = km
                if km_unit in ("mM",):
                    km_in_M = km * 1e-3
                elif km_unit in ("μM", "uM"):
                    km_in_M = km * 1e-6
                elif km_unit in ("nM",):
                    km_in_M = km * 1e-9
                kcat_val = kcat_km * km_in_M
                if 1e-3 <= kcat_val <= 1e8:
                    record["main_activity"]["kinetics"]["kcat"] = kcat_val
                    record["main_activity"]["kinetics"]["kcat_unit"] = "s^-1"
                    logger.info(f"[KineticsAgent] kcat derived from kcat/Km={kcat_km:.2e} * Km={km} {km_unit} = {kcat_val:.2e}")


class MorphologyAgent:
    _METAL_ELEMENTS = [
        "Fe", "Co", "Ni", "Cu", "Zn", "Mn", "Cr", "V", "Ti", "Mo", "W",
        "Ru", "Rh", "Pd", "Ag", "Pt", "Au", "Ir", "Os", "Ce", "La",
        "Pr", "Nd", "Sm", "Eu", "Gd", "Dy", "Yb", "Zr", "Hf", "Nb",
        "Ta", "Re", "Al", "Ga", "In", "Sn", "Pb", "Bi", "Pd", "Cd",
    ]

    _CHARACTERIZATION_TECHNIQUES = {
        "XRD": re.compile(r'\bXRD\b|X-ray\s+diffraction', re.I),
        "XPS": re.compile(r'\bXPS\b|X-ray\s+photoelectron', re.I),
        "SEM": re.compile(r'\bSEM\b|scanning\s+electron\s+microscop', re.I),
        "TEM": re.compile(r'\bTEM\b|transmission\s+electron\s+microscop', re.I),
        "HRTEM": re.compile(r'\bHRTEM\b|high.resolution\s+TEM', re.I),
        "EDX": re.compile(r'\bEDX\b|\bEDS\b|energy.dispersive\s+(?:X-ray|spectroscop)', re.I),
        "BET": re.compile(r'\bBET\b|Brunauer.Emmett.Teller|N2\s+adsorption', re.I),
        "Raman": re.compile(r'\bRaman\b', re.I),
        "FTIR": re.compile(r'\bFTIR\b|\bFT-IR\b|Fourier\s+transform\s+infrared', re.I),
        "XAFS": re.compile(r'\bXAFS\b|X-ray\s+absorption\s+fine\s+structure', re.I),
        "EPR": re.compile(r'\bEPR\b|electron\s+paramagnetic\s+resonance', re.I),
        "AFM": re.compile(r'\bAFM\b|atomic\s+force\s+microscop', re.I),
        "ICP": re.compile(r'\bICP\b|inductively\s+coupled\s+plasma', re.I),
        "TGA": re.compile(r'\bTGA\b|thermogravimet', re.I),
        "SAED": re.compile(r'\bSAED\b|selected.area\s+electron\s+diffraction', re.I),
        "HAADF": re.compile(r'\bHAADF\b|high.angle\s+annular\s+dark.field', re.I),
        "UV-vis": re.compile(r'\bUV.vis\b|UV.visible\s+spectroscop', re.I),
        "PL": re.compile(r'\bPL\b|photoluminescen', re.I),
        "DLS": re.compile(r'\bDLS\b|dynamic\s+light\s+scattering', re.I),
        "Zeta": re.compile(r'\bzeta\s+potential', re.I),
    }

    def extract(self, record, buckets, table_values, selected_name, doc=None):
        material_texts = buckets.get("material", []) + buckets.get("characterization", []) + buckets.get("synthesis", [])[:3]
        self._extract_size_properties(record, material_texts)
        char_texts = buckets.get("characterization", []) + buckets.get("material", [])[:3]
        self._extract_physical_properties(record, char_texts)
        all_relevant = material_texts + char_texts
        self._extract_metal_elements(record, all_relevant, selected_name)
        self._extract_characterization_techniques(record, all_relevant)
        self._extract_composition_structured(record, all_relevant, selected_name)
        self._extract_dopants_or_defects(record, all_relevant)
        return record

    def _extract_size_properties(self, record, material_texts):
        sel = record.get("selected_nanozyme", {})
        if not isinstance(sel, dict):
            return
        if sel.get("size") is None:
            for text in material_texts:
                for pat in _SIZE_PATTERNS:
                    m = pat.search(text)
                    if m:
                        groups = m.groups()
                        if len(groups) == 3:
                            low, high, unit = groups
                            sel["size"] = f"{low}-{high} {unit}"
                            sel["size_unit"] = unit
                            sel["size_distribution"] = f"{low}-{high} {unit}"
                        elif len(groups) == 2:
                            value, unit = groups
                            sel["size"] = f"{value} {unit}"
                            sel["size_unit"] = unit
                        break
                if sel.get("size"):
                    break
        if sel.get("crystal_structure") is None:
            for text in material_texts:
                for pat in _CRYSTAL_STRUCTURE_PATTERNS:
                    m = pat.search(text)
                    if m:
                        groups = m.groups()
                        all_digits = [g for g in groups if g and re.match(r'^\d{3}$', g)]
                        if all_digits:
                            sel["crystal_structure"] = ", ".join(f"({p})" for p in all_digits)
                        elif m.lastindex and m.group(1):
                            raw = m.group(1).strip()
                            if re.match(r'^[\d\s,.\u00c5]+$', raw):
                                continue
                            elif re.match(r'^[\d\s,]+$', raw):
                                planes = re.findall(r'\d{3}', raw)
                                if planes:
                                    sel["crystal_structure"] = ", ".join(f"({p})" for p in planes)
                            else:
                                sel["crystal_structure"] = raw.lower()
                        else:
                            match_text = m.group(0).lower()
                            for struct_name in ("spinel", "perovskite", "fluorite", "cubic",
                                               "tetragonal", "hexagonal", "orthorhombic",
                                               "monoclinic", "amorphous", "crystalline",
                                               "anatase", "rutile", "brookite",
                                               "rock salt", "zinc blende", "wurtzite",
                                               "graphitic", "face-centered cubic",
                                               "body-centered cubic"):
                                if struct_name in match_text:
                                    sel["crystal_structure"] = struct_name
                                    break
                            if sel.get("crystal_structure") is None:
                                planes = re.findall(r'\((\d{3})\)', m.group(0))
                                if planes:
                                    sel["crystal_structure"] = ", ".join(f"({p})" for p in planes)
                        break
                if sel.get("crystal_structure"):
                    break

    def _extract_physical_properties(self, record, char_texts):
        sel = record.get("selected_nanozyme", {})
        if not isinstance(sel, dict):
            return
        if sel.get("surface_area") is None:
            for text in char_texts:
                for pat in _SURFACE_AREA_PATTERNS:
                    m = pat.search(text)
                    if m:
                        sel["surface_area"] = f"{m.group(1)} {m.group(2)}"
                        break
                if sel.get("surface_area"):
                    break
        if sel.get("zeta_potential") is None:
            for text in char_texts:
                for pat in _ZETA_POTENTIAL_PATTERNS:
                    m = pat.search(text)
                    if m:
                        sel["zeta_potential"] = f"{m.group(1)} {m.group(2)}"
                        break
                if sel.get("zeta_potential"):
                    break
        if sel.get("pore_size") is None:
            for text in char_texts:
                for pat in _PORE_SIZE_PATTERNS:
                    m = pat.search(text)
                    if m:
                        sel["pore_size"] = f"{m.group(1)} {m.group(2)}"
                        break
                if sel.get("pore_size"):
                    break

    def _extract_metal_elements(self, record, texts, selected_name):
        sel = record.get("selected_nanozyme", {})
        if not isinstance(sel, dict):
            return
        if sel.get("metal_elements") and len(sel["metal_elements"]) > 0:
            return

        name_lower = (selected_name or "").lower()
        found_elements = set()
        for elem in self._METAL_ELEMENTS:
            if elem.lower() in name_lower:
                found_elements.add(elem)

        combined = " ".join(texts[:20])
        for elem in self._METAL_ELEMENTS:
            if re.search(r'\b' + re.escape(elem) + r'\b', combined):
                found_elements.add(elem)

        if found_elements:
            sel["metal_elements"] = sorted(list(found_elements))

    def _extract_characterization_techniques(self, record, texts):
        sel = record.get("selected_nanozyme", {})
        if not isinstance(sel, dict):
            return
        if sel.get("characterization") and len(sel["characterization"]) > 0:
            return

        found_techniques = set()
        combined = " ".join(texts[:20])
        for tech_name, pattern in self._CHARACTERIZATION_TECHNIQUES.items():
            if pattern.search(combined):
                found_techniques.add(tech_name)

        if found_techniques:
            sel["characterization"] = sorted(list(found_techniques))

    _DOPANT_PATTERNS = [
        re.compile(r'\b(?:N|B|S|P|F|Cl|Br|I|Se|Si)\s*[-‑–—doped]\b', re.I),
        re.compile(r'\b(?:N|B|S|P|F|Se|Si)\s*[-‑–]?(?:doped|substituted|incorporated|co[-\s]?doped)\b', re.I),
        re.compile(r'\b(?:co[-\s]?doped|tri[-\s]?doped)\s+(?:with\s+)?([\w\-]+(?:\s[\w\-]+){0,2})', re.I),
        re.compile(r'\bdoped\s+(?:with|by)\s+([\w\-]+(?:\s[\w\-]+){0,2})', re.I),
        re.compile(r'\b(?:N|B|S|P|F|Se|Si|Cl)\s*[-‑–]\s*(?:doped|doping|substitut)', re.I),
        re.compile(r'\boxygen\s+vacanc', re.I),
        re.compile(r'\bsulfur\s+vacanc', re.I),
        re.compile(r'\bnitrogen\s+vacanc', re.I),
        re.compile(r'\b(?:vacancy|vacancies|defect|defects)\b', re.I),
        re.compile(r'\b(?:Fe|Co|Ni|Mn|Cu|Zn|Ce|Au|Ag|Pt|Pd|Ti|V|Cr|Mo|W|Ru|Rh|Ir|La|Zr|Al|Sn|Bi|In)\s*[-‑–]\s*(?:doped|substituted|incorporated)\b', re.I),
    ]

    def _extract_dopants_or_defects(self, record, texts):
        sel = record.get("selected_nanozyme", {})
        if not isinstance(sel, dict):
            return
        if sel.get("dopants_or_defects") and len(sel["dopants_or_defects"]) > 0:
            return
        found = set()
        for text in texts:
            for pat in self._DOPANT_PATTERNS:
                m = pat.search(text)
                if m:
                    raw = m.group(0).strip()
                    if 'vacanc' in raw.lower() or 'defect' in raw.lower():
                        if 'oxygen' in raw.lower():
                            found.add("oxygen vacancy")
                        elif 'sulfur' in raw.lower():
                            found.add("sulfur vacancy")
                        elif 'nitrogen' in raw.lower():
                            found.add("nitrogen vacancy")
                        else:
                            found.add(raw.lower())
                    elif m.lastindex and m.group(1):
                        found.add(m.group(1).strip().lower())
                    else:
                        found.add(raw.lower())
        if found:
            sel["dopants_or_defects"] = sorted(list(found))

    _CORE_PATTERN = re.compile(
        r'\b([A-Z][a-z]?\d*(?:[- ][A-Z][a-z]?\d*)*)\s*@\s*([A-Z][a-z]?\d*(?:[- ][A-Z][a-z]?\d*)*)\b',
    )
    _SUPPORT_PATTERN = re.compile(
        r'\b(?:supported|deposited|loaded|anchored|immobilized)\s+(?:on|onto|over)\s+([\w\-]+(?:\s[\w\-]+){0,2})',
        re.I,
    )
    _ORGANIC_PATTERN = re.compile(
        r'\b(?:coated|wrapped|capped|functionalized|modified)\s+(?:with|by)\s+([\w\-]+(?:\s[\w\-]+){0,2})',
        re.I,
    )

    def _extract_composition_structured(self, record, texts, selected_name):
        sel = record.get("selected_nanozyme", {})
        if not isinstance(sel, dict):
            return
        comp = sel.get("composition_structured", {})
        if not isinstance(comp, dict):
            comp = {"core": None, "dopants": [], "support": None, "organic_component": None}
            sel["composition_structured"] = comp

        if comp.get("core") is None:
            for text in texts:
                m = self._CORE_PATTERN.search(text)
                if m:
                    comp["core"] = m.group(1).strip()
                    comp["support"] = m.group(2).strip()
                    break

        if comp.get("support") is None:
            for text in texts:
                m = self._SUPPORT_PATTERN.search(text)
                if m:
                    comp["support"] = m.group(1).strip()
                    break

        if comp.get("organic_component") is None:
            for text in texts:
                m = self._ORGANIC_PATTERN.search(text)
                if m:
                    raw = m.group(1).strip().lower()
                    if raw not in ("the", "a", "an", "its"):
                        comp["organic_component"] = raw
                    break

        if not comp.get("dopants"):
            dopants = sel.get("dopants_or_defects", [])
            if dopants:
                comp["dopants"] = dopants


class SynthesisAgent:
    def extract(self, record, buckets, table_values, selected_name, doc=None):
        synthesis_texts = buckets.get("synthesis", []) + buckets.get("material", [])[:5] + buckets.get("characterization", [])[:3]
        self._extract_synthesis_method(record, synthesis_texts)
        self._extract_method_detail(record, synthesis_texts)
        return record

    def _extract_synthesis_method(self, record, synthesis_texts):
        sel = record.get("selected_nanozyme", {})
        if not isinstance(sel, dict):
            return
        if sel.get("synthesis_method") is None:
            method_scores = {}
            for text in synthesis_texts:
                for method_name, pattern in _SYNTHESIS_METHODS.items():
                    if pattern.search(text):
                        weight = 0.1 if method_name == "general_synthesis" else 1.0
                        score = method_scores.get(method_name, 0) + weight
                        method_scores[method_name] = score
            if method_scores:
                non_generic = {k: v for k, v in method_scores.items() if k != "general_synthesis"}
                if non_generic:
                    best_method = max(non_generic, key=non_generic.get)
                else:
                    best_method = max(method_scores, key=method_scores.get)
                sel["synthesis_method"] = best_method.replace("_", " ")

        synth_cond = sel.get("synthesis_conditions", {})
        if not isinstance(synth_cond, dict):
            synth_cond = {}
            sel["synthesis_conditions"] = synth_cond

        if synth_cond.get("temperature") is None:
            for text in synthesis_texts:
                for pat in _SYNTHESIS_CONDITION_PATTERNS["temperature"]:
                    m = pat.search(text)
                    if m:
                        synth_cond["temperature"] = f"{m.group(1)} °C"
                        break
                if synth_cond.get("temperature"):
                    break

        if synth_cond.get("time") is None:
            for text in synthesis_texts:
                for pat in _SYNTHESIS_CONDITION_PATTERNS["time"]:
                    m = pat.search(text)
                    if m:
                        synth_cond["time"] = f"{m.group(1)} {m.group(2)}"
                        break
                if synth_cond.get("time"):
                    break

        if not synth_cond.get("precursors"):
            for text in synthesis_texts:
                for pat in _SYNTHESIS_CONDITION_PATTERNS["precursors"]:
                    m = pat.search(text)
                    if m:
                        raw = m.group(1).strip()
                        precursors = [p.strip() for p in re.split(r'[,\s]+', raw) if p.strip() and len(p.strip()) > 1]
                        if precursors:
                            synth_cond["precursors"] = precursors[:5]
                        break
                if synth_cond.get("precursors"):
                    break

    _METHOD_DETAIL_PATTERNS = [
        re.compile(r'\b(?:under|in)\s+(?:a\s+)?(N[2_]|Ar|nitrogen|argon|inert|vacuum|air)\s+(?:atmosphere|flow|environment|condition)', re.I),
        re.compile(r'\b(?:stirred|stirring)\s+(?:for|at)\s*([\d.]+\s*(?:h|hour|min|s))', re.I),
        re.compile(r'\baged\s+(?:at|for)\s*([\d.]+\s*(?:h|hour|min|days?|°C))', re.I),
        re.compile(r'\bdried\s+(?:at|under|in)\s*([\d.]+\s*(?:°C|h|hour|vacuum))', re.I),
        re.compile(r'\bcalcined\s+(?:at|for)\s*([\d.]+\s*(?:°C|h|hour))', re.I),
        re.compile(r'\bwashed\s+(?:with|by)\s+([\w\-]+(?:\s[\w\-]+){0,2})', re.I),
        re.compile(r'\bcentrifuged\s+(?:at|for)\s*([\d.]+\s*(?:rpm|g|min))', re.I),
        re.compile(r'\b(?:autoclaved|sealed)\s+(?:in|at)\s*([\w\-]+(?:\s[\w\-]+){0,2})', re.I),
        re.compile(r'\b(?:ground|milled|ball[-\s]?milled)\s+(?:for|at)\s*([\d.]+\s*(?:h|hour|min))', re.I),
        re.compile(r'\bfreeze[-\s]?dried\b', re.I),
        re.compile(r'\blyophilized\b', re.I),
    ]

    def _extract_method_detail(self, record, synthesis_texts):
        sel = record.get("selected_nanozyme", {})
        if not isinstance(sel, dict):
            return
        synth_cond = sel.get("synthesis_conditions", {})
        if not isinstance(synth_cond, dict):
            synth_cond = {}
            sel["synthesis_conditions"] = synth_cond
        if synth_cond.get("method_detail"):
            return
        details = []
        for text in synthesis_texts:
            for pat in self._METHOD_DETAIL_PATTERNS:
                m = pat.search(text)
                if m:
                    raw = m.group(0).strip()
                    if m.lastindex and m.group(1):
                        raw = f"{raw.split(m.group(1))[0].strip()} {m.group(1).strip()}"
                    details.append(raw)
                    if len(details) >= 3:
                        break
            if len(details) >= 3:
                break
        if details:
            synth_cond["method_detail"] = "; ".join(details)


class ApplicationAgent:
    _APP_TYPE_KEYWORDS = {
        "detection": ["detection", "sensing", "sensor", "biosensor", "assay", "monitoring", "determin"],
        "therapeutic": ["therapeutic", "antitumor", "antibacterial", "wound heal", "cytoprotect", "neuroprotect", "anti-inflammator", "antiinflammator", "disinfect", "steriliz"],
        "environmental": ["pollutant", "heavy metal", "pesticide", "organophosph", "endocrine", "degrad", "environmental", "drinking water", "waste water", "river", "lake", "tap water", "sea water"],
        "diagnostic": ["diagnos", "theranost", "biomarker", "point-of-care", "poc"],
    }

    _ANALYTE_PATTERNS = [
        re.compile(r'\b(?:detection\s+(?:of|for)|sensing\s+(?:of|for)|determin(?:ation|ing)\s+(?:of|for))\s+([\w\-]+(?:\s[\w\-]+){0,3})', re.I),
        re.compile(r'\b(?:glucose|cholesterol|uric\s+acid|lactate|ascorbic\s+acid|dopamine|cysteine|glutathione|bilirubin)\b', re.I),
        re.compile(r'\b(?:Hg[\s2]*\+{1,2}|Pb[\s2]*\+{1,2}|Cd[\s2]*\+{1,2}|Cu[\s2]*\+{1,2}|Fe[\s3]*\+{1,2}|Cr\s*[Vv][Ii]+|As\s*[Vv][Ii]+)\b', re.I),
        re.compile(r'\b(?:xanthine|hypoxanthine|acetylcholine|choline|urea|hydrogen\s+peroxide|H2O2|phenol|bisphenol|catechol|hydroquinone)\b', re.I),
        re.compile(r'\b(?:mercury|lead|cadmium|arsenic|chromium)\b', re.I),
        re.compile(r'\b(?:sensing|detecting|monitoring)\s+(?:of\s+)?([\w\-]+(?:\s[\w\-]+){0,2})', re.I),
        re.compile(r'\b(?:thrombin|lysozyme|trypsin|urease|horseradish|HRP|BSA|albumin)\b', re.I),
        re.compile(r'\b(?:nitrofurantoin|chloramphenicol|tetracycline|kanamycin|gentamicin|ampicillin)\b', re.I),
        re.compile(r'\b(?:malathion|paraoxon|chlorpyrifos|diazinon|atrazine|simazine)\b', re.I),
    ]

    _SAMPLE_TYPE_MAP = {
        "serum": "serum", "plasma": "plasma", "urine": "urine", "blood": "blood",
        "saliva": "saliva", "tear": "tear", "water": "water", "food": "food",
        "milk": "food", "juice": "food", "wine": "food", "beer": "food",
        "cell": "cell_culture", "tissue": "tissue", "river": "environmental_water",
        "lake": "environmental_water", "tap water": "environmental_water",
        "sea water": "environmental_water", "waste water": "environmental_water",
        "drinking water": "environmental_water",
    }

    def extract(self, record, buckets, table_values, selected_name, doc=None):
        app_texts = (buckets.get("application", [])
                     + buckets.get("kinetics", [])[:5]
                     + buckets.get("activity", [])[:3])
        self._extract_applications_from_text(record, app_texts)
        self._extract_selectivity(record, app_texts)
        self._extract_response_time(record, app_texts)
        self._extract_reusability(record, app_texts)
        return record

    def _is_kinetics_context(self, text):
        kinetics_kw = ("km", "vmax", "kcat", "michaelis", "kinetic", "michaelis-menten")
        text_lower = text.lower()
        return any(kw in text_lower for kw in kinetics_kw)

    def _extract_applications_from_text(self, record, app_texts):
        if record["applications"]:
            return
        seen_apps = set()
        for text in app_texts:
            app = {}
            for pat in _LOD_PATTERNS:
                lod_m = pat.search(text)
                if lod_m:
                    app["detection_limit"] = f"{lod_m.group(1)} {lod_m.group(2)}"
                    break
            for pat in _LINEAR_RANGE_PATTERNS:
                lr_m = pat.search(text)
                if lr_m:
                    app["linear_range"] = f"{lr_m.group(1)} {lr_m.group(2)}"
                    break
            text_lower = text.lower()
            for app_type, keywords in self._APP_TYPE_KEYWORDS.items():
                if any(kw in text_lower for kw in keywords):
                    app["application_type"] = app_type
                    break
            for pat in self._ANALYTE_PATTERNS:
                m = pat.search(text)
                if m:
                    analyte = m.group(1).strip() if m.lastindex else m.group(0).strip()
                    analyte = re.sub(r'\s+', ' ', analyte).strip()
                    if len(analyte) > 2 and analyte.lower() not in ("the", "this", "that"):
                        if analyte.lower() == "h2o2" and self._is_kinetics_context(text):
                            continue
                        app["target_analyte"] = analyte
                    break
            for sample_kw, sample_type in self._SAMPLE_TYPE_MAP.items():
                if sample_kw in text_lower:
                    app["sample_type"] = sample_type
                    break
            if any(kw in text_lower for kw in ["colorimetric", "colorimetry"]):
                app["method"] = "colorimetric"
            elif any(kw in text_lower for kw in ["fluorescent", "fluorescence"]):
                app["method"] = "fluorescent"
            elif any(kw in text_lower for kw in ["electrochem"]):
                app["method"] = "electrochemical"
            elif any(kw in text_lower for kw in ["smartphone", "phone"]):
                app["method"] = "smartphone-based"
            has_substance = any(v is not None for k, v in app.items() if k in ("detection_limit", "linear_range", "target_analyte", "sample_type"))
            has_type = app.get("application_type") is not None
            if not has_substance and not has_type:
                continue
            dedup_key = (app.get("application_type"), app.get("target_analyte"), app.get("detection_limit"), app.get("linear_range"))
            if dedup_key in seen_apps:
                continue
            seen_apps.add(dedup_key)
            for key in ("application_type", "target_analyte", "method", "linear_range", "detection_limit", "sample_type", "notes"):
                app.setdefault(key, None)
            record["applications"].append(app)

    _SELECTIVITY_PATTERNS = [
        re.compile(r'\bselectivit', re.I),
        re.compile(r'\binterfer', re.I),
        re.compile(r'\banti.interfer', re.I),
        re.compile(r'\bspecificit', re.I),
        re.compile(r'\bno\s+(?:significant\s+)?interfer', re.I),
        re.compile(r'\b(?:high|excellent|good|remarkable)\s+selectivit', re.I),
    ]

    _SELECTIVITY_DETAIL_PATTERNS = [
        re.compile(r'\bselectiv(?:e|ity)\s+(?:toward|for|to|over|against)\s+([\w\-]+(?:\s[\w\-]+){0,3})', re.I),
        re.compile(r'\bno\s+(?:significant\s+|obvious\s+)?interfer(?:ence)?\s+(?:from|by)\s+([\w\-]+(?:\s[\w\-]+){0,3})', re.I),
        re.compile(r'\binterfer(?:ence)?\s+(?:from|by)\s+([\w\-]+(?:\s[\w\-]+){0,3})\s+was\s+(?:negligible|minimal|not\s+observed)', re.I),
    ]

    def _extract_selectivity(self, record, app_texts):
        apps = record.get("applications", [])
        if not apps:
            return
        app = apps[0]
        if app.get("notes") and "selectivity" in str(app["notes"]).lower():
            return
        for text in app_texts:
            for pat in self._SELECTIVITY_PATTERNS:
                if pat.search(text):
                    detail = None
                    for dpat in self._SELECTIVITY_DETAIL_PATTERNS:
                        dm = dpat.search(text)
                        if dm:
                            detail = dm.group(1).strip()
                            break
                    note = "selective"
                    if detail:
                        note = f"selective toward {detail}"
                    if app.get("notes"):
                        app["notes"] = f"{app['notes']}; {note}"
                    else:
                        app["notes"] = note
                    return

    _RESPONSE_TIME_PATTERNS = [
        re.compile(r'\bresponse\s+time\s*(?:of|was|=|:|≈|~)\s*(?:about\s+|approximately\s+)?([\d.]+)\s*(s|sec|min)', re.I),
        re.compile(r'\bdetection\s+time\s*(?:of|was|=|:|≈|~)\s*(?:about\s+|approximately\s+)?([\d.]+)\s*(s|sec|min)', re.I),
        re.compile(r'\b(?:within|in)\s*([\d.]+)\s*(s|sec|min)\s+(?:of\s+)?(?:response|detection)', re.I),
        re.compile(r'\b(?:rapid|fast|quick)\s+(?:response|detection)\s+(?:within|in)\s*([\d.]+)\s*(s|sec|min)', re.I),
        re.compile(r'\bresult\s+(?:was\s+)?obtained\s+(?:within|in)\s*([\d.]+)\s*(s|sec|min)', re.I),
    ]

    def _extract_response_time(self, record, app_texts):
        apps = record.get("applications", [])
        if not apps:
            return
        app = apps[0]
        if app.get("notes") and "response time" in str(app["notes"]).lower():
            return
        for text in app_texts:
            for pat in self._RESPONSE_TIME_PATTERNS:
                m = pat.search(text)
                if m:
                    val = m.group(1)
                    unit = m.group(2)
                    note = f"response time: {val} {unit}"
                    if app.get("notes"):
                        app["notes"] = f"{app['notes']}; {note}"
                    else:
                        app["notes"] = note
                    return

    _REUSABILITY_PATTERNS = [
        re.compile(r'\bretained\s+(?:more\s+than\s+)?(\d+)\s*%?\s*(?:of\s+(?:its?\s+)?(?:original|initial)\s+activity)?\s*(?:after|for)\s*([\d.]+)\s*cycles?', re.I),
        re.compile(r'\breusab', re.I),
        re.compile(r'\brecyclab', re.I),
        re.compile(r'\b(?:good|excellent|high)\s+reusab', re.I),
        re.compile(r'\b(?:reused|recycled)\s+(?:for\s+)?([\d.]+)\s*cycles?', re.I),
        re.compile(r'\bremained\s+([\d.]+)\s*%?\s*(?:of\s+(?:its?\s+)?(?:original|initial)\s+activity)?\s*(?:after|over)\s*([\d.]+)\s*cycles?', re.I),
    ]

    def _extract_reusability(self, record, app_texts):
        apps = record.get("applications", [])
        if not apps:
            return
        app = apps[0]
        if app.get("notes") and "reusab" in str(app["notes"]).lower():
            return
        for text in app_texts:
            for pat in self._REUSABILITY_PATTERNS:
                m = pat.search(text)
                if m:
                    groups = m.groups()
                    if len(groups) >= 2 and groups[0] and groups[1]:
                        note = f"reusable: {groups[0]}% after {groups[1]} cycles"
                    else:
                        note = "reusable"
                    if app.get("notes"):
                        app["notes"] = f"{app['notes']}; {note}"
                    else:
                        app["notes"] = note
                    return


class RuleExtractorAdapter:
    def __init__(self):
        self.kinetics_agent = KineticsAgent()
        self.morphology_agent = MorphologyAgent()
        self.synthesis_agent = SynthesisAgent()
        self.application_agent = ApplicationAgent()

    def extract_from_evidence(self, record, buckets, table_values, selected_name, doc=None):
        if record["main_activity"]["enzyme_like_type"] is None:
            search_texts = buckets.get("activity", []) + buckets.get("mechanism", [])
            if doc:
                title = doc.metadata.get("title", "")
                if title:
                    search_texts.insert(0, title)
                for chunk in doc.chunks[:3]:
                    if "abstract" in chunk.lower()[:200]:
                        search_texts.insert(0, chunk[:2000])
                        break
            for text in search_texts:
                for pattern, etype in _ENZYME_TYPE_PATTERNS:
                    if pattern.search(text):
                        record["main_activity"]["enzyme_like_type"] = etype
                        break
                if record["main_activity"]["enzyme_like_type"]:
                    break
            if record["main_activity"]["enzyme_like_type"] is None and doc:
                for chunk in doc.chunks:
                    for pattern, etype in _ENZYME_TYPE_PATTERNS:
                        if pattern.search(chunk):
                            record["main_activity"]["enzyme_like_type"] = etype
                            break
                    if record["main_activity"]["enzyme_like_type"]:
                        break

        if not record["main_activity"]["substrates"]:
            found = set()
            for text in buckets.get("activity", []):
                for sub in _SUBSTRATE_KEYWORDS:
                    if sub in text:
                        found.add(sub)
            if found:
                record["main_activity"]["substrates"] = sorted(found)

        self.kinetics_agent.extract(record, buckets, table_values, selected_name, doc)
        self.morphology_agent.extract(record, buckets, table_values, selected_name, doc)
        self.synthesis_agent.extract(record, buckets, table_values, selected_name, doc)
        self.application_agent.extract(record, buckets, table_values, selected_name, doc)

        self._extract_pH_profile(record, buckets)
        self._extract_temperature_profile(record, buckets)

        if doc:
            self._fulltext_fallback_extract(record, doc, selected_name)

        return record

    def _extract_pH_profile(self, record, buckets):
        ph_profile = record["main_activity"].get("pH_profile", {})
        if not isinstance(ph_profile, dict):
            ph_profile = {}
            record["main_activity"]["pH_profile"] = ph_profile

        search_texts = (
            buckets.get("activity", [])
            + buckets.get("kinetics", [])
            + buckets.get("application", [])[:5]
            + buckets.get("mechanism", [])[:5]
            + record.get("raw_supporting_text", {}).get("kinetics", [])[:5]
            + record.get("raw_supporting_text", {}).get("activity", [])[:5]
        )

        if ph_profile.get("optimal_pH") is None:
            for text in search_texts:
                for pat in _PH_PATTERNS["optimal_pH"]:
                    m = pat.search(text)
                    if m:
                        try:
                            ph_profile["optimal_pH"] = float(m.group(1))
                            record["main_activity"]["conditions"]["pH"] = m.group(1)
                        except (ValueError, IndexError):
                            pass
                        break
                if ph_profile.get("optimal_pH") is not None:
                    break

        if ph_profile.get("optimal_pH") is None:
            _OPTIMAL_PH_EXTRA_PATTERNS = [
                re.compile(r'\bpH\s*([\d.]+)\s*(?:was|is|showed|exhibited|displayed)\s+(?:the\s+)?(?:highest|maximum|optimal|best)', re.I),
                re.compile(r'(?:highest|maximum|optimal|best)\s+(?:activity|catalytic)\s+(?:was\s+)?(?:observed|achieved|found|obtained)\s+at\s+pH\s*([\d.]+)', re.I),
                re.compile(r'(?:optimal|optimum)\s+pH\s*(?:value\s*)?(?:of|was|:)\s*([\d.]+)', re.I),
                re.compile(r'pHo\s*(?:pt)?\s*=\s*([\d.]+)', re.I),
            ]
            for text in search_texts:
                for pat in _OPTIMAL_PH_EXTRA_PATTERNS:
                    m = pat.search(text)
                    if m:
                        try:
                            val = float(m.group(1))
                            if 0 < val <= 14:
                                ph_profile["optimal_pH"] = val
                                record["main_activity"]["conditions"]["pH"] = m.group(1)
                                break
                        except (ValueError, IndexError):
                            pass
                if ph_profile.get("optimal_pH") is not None:
                    break

        if ph_profile.get("optimal_pH") is None:
            for text in search_texts:
                if re.search(r'\b(?:kinetic|reaction|catalytic|assay|steady-state)\b', text, re.I):
                    m = re.search(r'\b(?:buffer|solution)\s*\([^)]*pH\s*([\d.]+)', text, re.I)
                    if m:
                        try:
                            val = float(m.group(1))
                            if 0 <= val <= 14:
                                record["main_activity"]["conditions"]["pH"] = m.group(1)
                                break
                        except (ValueError, IndexError):
                            pass

        if ph_profile.get("optimal_pH") is None:
            _PH_LOOSE_PATTERNS = [
                re.compile(r'\bpH\s*([\d.]+)\s*\)', re.I),
                re.compile(r'\bpH\s+([\d.]+)', re.I),
            ]
            for text in search_texts:
                if re.search(r'\b(?:optimal|optimum|best|highest|maximum|peak)\b', text, re.I) and re.search(r'\bpH\b', text, re.I):
                    for pat in _PH_LOOSE_PATTERNS:
                        m = pat.search(text)
                        if m:
                            try:
                                val = float(m.group(1))
                                if 0 < val <= 14:
                                    ph_profile["optimal_pH"] = val
                                    record["main_activity"]["conditions"]["pH"] = m.group(1)
                                    break
                            except (ValueError, IndexError):
                                pass
                    if ph_profile.get("optimal_pH") is not None:
                        break

        if ph_profile.get("pH_range") is None:
            for text in search_texts:
                for pat in _PH_PATTERNS["pH_range"]:
                    m = pat.search(text)
                    if m:
                        ph_profile["pH_range"] = f"{m.group(1)}-{m.group(2)}"
                        break
                if ph_profile.get("pH_range") is not None:
                    break

        if ph_profile.get("pH_stability_range") is None:
            for text in search_texts:
                for pat in _PH_PATTERNS["pH_stability"]:
                    m = pat.search(text)
                    if m:
                        ph_profile["pH_stability_range"] = f"{m.group(1)}-{m.group(2)}"
                        break
                if ph_profile.get("pH_stability_range") is not None:
                    break

        if ph_profile.get("optimal_pH") is None:
            cond_ph = record.get("main_activity", {}).get("conditions", {}).get("pH")
            if cond_ph:
                try:
                    val = float(cond_ph)
                    if 0 < val <= 14:
                        ph_profile["optimal_pH"] = val
                        if not record["main_activity"]["conditions"].get("pH"):
                            record["main_activity"]["conditions"]["pH"] = str(val)
                except (ValueError, TypeError):
                    pass

    def _extract_temperature_profile(self, record, buckets):
        temp_profile = record["main_activity"].get("temperature_profile", {})
        if not isinstance(temp_profile, dict):
            temp_profile = {}
            record["main_activity"]["temperature_profile"] = temp_profile

        search_texts = (
            buckets.get("activity", [])
            + buckets.get("kinetics", [])
            + buckets.get("application", [])[:5]
            + buckets.get("mechanism", [])[:5]
            + record.get("raw_supporting_text", {}).get("kinetics", [])[:5]
            + record.get("raw_supporting_text", {}).get("activity", [])[:5]
        )

        norm_texts = [_normalize_ocr_scientific(t) for t in search_texts]

        if temp_profile.get("optimal_temperature") is None:
            for text, norm in zip(search_texts, norm_texts):
                for pat in _TEMPERATURE_PATTERNS["optimal_temperature"]:
                    m = pat.search(text)
                    if not m:
                        m = pat.search(norm)
                    if m:
                        temp_profile["optimal_temperature"] = f"{m.group(1)} °C"
                        record["main_activity"]["conditions"]["temperature"] = f"{m.group(1)} °C"
                        break
                if temp_profile.get("optimal_temperature") is not None:
                    break

        if temp_profile.get("optimal_temperature") is None:
            _OPTIMAL_TEMP_EXTRA_PATTERNS = [
                re.compile(r'(?:optimal|optimum)\s+(?:temperature|temp)\s*(?:value\s*)?(?:of|was|:)\s*([\d.]+)\s*°?\s*C', re.I),
                re.compile(r'(?:highest|maximum|best)\s+(?:activity|catalytic)\s+(?:was\s+)?(?:observed|achieved|found|obtained)\s+at\s*([\d.]+)\s*°?\s*C', re.I),
                re.compile(r'([\d.]+)\s*°\s*C\s*(?:was|is)\s+(?:the\s+)?(?:optimal|optimum|best)', re.I),
            ]
            for text, norm in zip(search_texts, norm_texts):
                for pat in _OPTIMAL_TEMP_EXTRA_PATTERNS:
                    m = pat.search(text)
                    if not m:
                        m = pat.search(norm)
                    if m:
                        try:
                            val = float(m.group(1))
                            if 15 <= val <= 80:
                                temp_profile["optimal_temperature"] = f"{m.group(1)} °C"
                                record["main_activity"]["conditions"]["temperature"] = f"{m.group(1)} °C"
                                break
                        except (ValueError, IndexError):
                            pass
                if temp_profile.get("optimal_temperature") is not None:
                    break

        if temp_profile.get("optimal_temperature") is None:
            for text, norm in zip(search_texts, norm_texts):
                if re.search(r'\b(?:kinetic|reaction|catalytic|assay|steady-state)\b', text, re.I):
                    m = re.search(r'\b(?:at|under)\s*([\d.]+)\s*°?\s*C\b', norm, re.I)
                    if not m:
                        m = re.search(r'\b([\d.]+)\s*°\s*C\b', norm, re.I)
                    if m:
                        try:
                            val = float(m.group(1))
                            if 15 <= val <= 80:
                                record["main_activity"]["conditions"]["temperature"] = f"{m.group(1)} °C"
                                break
                        except (ValueError, IndexError):
                            pass

        if temp_profile.get("optimal_temperature") is None:
            _TEMP_LOOSE_PATTERNS = [
                re.compile(r'([\d.]+)\s*°\s*C', re.I),
                re.compile(r'([\d.]+)\s*°C', re.I),
            ]
            for text, norm in zip(search_texts, norm_texts):
                if re.search(r'\b(?:optimal|optimum|best|highest|maximum|peak|dependent|effect)\b', text, re.I) and re.search(r'\b(?:temperature|temp|°C)\b', text, re.I):
                    for pat in _TEMP_LOOSE_PATTERNS:
                        m = pat.search(text)
                        if not m:
                            m = pat.search(norm)
                        if m:
                            try:
                                val = float(m.group(1))
                                if 15 <= val <= 80:
                                    temp_profile["optimal_temperature"] = f"{m.group(1)} °C"
                                    record["main_activity"]["conditions"]["temperature"] = f"{m.group(1)} °C"
                                    break
                            except (ValueError, IndexError):
                                pass
                    if temp_profile.get("optimal_temperature") is not None:
                        break

        if temp_profile.get("temperature_range") is None:
            for text, norm in zip(search_texts, norm_texts):
                for pat in _TEMPERATURE_PATTERNS["temperature_range"]:
                    m = pat.search(text)
                    if not m:
                        m = pat.search(norm)
                    if m:
                        temp_profile["temperature_range"] = f"{m.group(1)}-{m.group(2)} °C"
                        break
                if temp_profile.get("temperature_range") is not None:
                    break

        if temp_profile.get("temperature_range") is None:
            _TEMP_RANGE_FALLBACK = [
                re.compile(r'\btemperature\s+(?:ranging\s+)?(?:from\s+)?([\d.]+)\s*[-–—~to]+\s*([\d.]+)\s*°?C', re.I),
            ]
            for text, norm in zip(search_texts, norm_texts):
                for pat in _TEMP_RANGE_FALLBACK:
                    m = pat.search(text)
                    if not m:
                        m = pat.search(norm)
                    if m:
                        try:
                            low, high = float(m.group(1)), float(m.group(2))
                            if 10 <= low <= 100 and 10 <= high <= 100:
                                temp_profile["temperature_range"] = f"{m.group(1)}-{m.group(2)} °C"
                                break
                        except (ValueError, IndexError):
                            pass
                if temp_profile.get("temperature_range") is not None:
                    break

        if temp_profile.get("thermal_stability") is None:
            for text, norm in zip(search_texts, norm_texts):
                for pat in _TEMPERATURE_PATTERNS["thermal_stability"]:
                    m = pat.search(text)
                    if not m:
                        m = pat.search(norm)
                    if m:
                        temp_profile["thermal_stability"] = f"stable up to {m.group(1)} °C"
                        break
                if temp_profile.get("thermal_stability") is not None:
                    break

        if temp_profile.get("optimal_temperature") is None:
            cond_temp = record.get("main_activity", {}).get("conditions", {}).get("temperature")
            if cond_temp:
                m = re.search(r'([\d.]+)', str(cond_temp))
                if m:
                    try:
                        val = float(m.group(1))
                        if 15 <= val <= 80:
                            temp_profile["optimal_temperature"] = f"{m.group(1)} °C"
                    except (ValueError, TypeError):
                        pass

    _MORPHOLOGY_TERMS = [
        "nanoparticle", "nanoparticles", "nanosphere", "nanospheres",
        "nanosheet", "nanosheets", "nanorod", "nanorods",
        "nanowire", "nanowires", "nanotube", "nanotubes",
        "nanofiber", "nanofibers", "nanocube", "nanocubes",
        "nanoprism", "nanoprisms", "nanostar", "nanostars",
        "nanoflower", "nanoflowers", "nanocluster", "nanoclusters",
        "nanodot", "nanodots", "nanoring", "nanorings",
        "octahedr", "cuboctahedr", "dodecahedr", "icosahedr",
        "sphere", "spherical", "cubic", "cubical",
        "rod-shaped", "sheet-like", "wire-like", "flower-like",
        "core-shell", "yolk-shell", "hollow sphere", "hollow structure",
        "mesoporous", "porous", "lamellar", "layered",
        "dendritic", "branched", "urchin-like", "bundle",
        "platelet", "flake", "belt", "ribbon",
        "needle-like", "spindle", "ellipsoid", "ellipsoidal",
        "irregular", "aggregat",
    ]

    def _fulltext_fallback_extract(self, record, doc, selected_name):
        all_text = "\n".join(doc.chunks) if doc.chunks else ""
        if not all_text:
            return

        norm_text = _normalize_ocr_scientific(all_text)
        search_pairs = [(all_text, norm_text)]

        sel = record.get("selected_nanozyme", {})
        act = record.get("main_activity", {})
        ph_prof = act.get("pH_profile", {})
        temp_prof = act.get("temperature_profile", {})

        selected_variants = self._build_selected_variants(selected_name)

        ph_prof = self._context_aware_fallback(
            ph_prof, "optimal_pH", _PH_PATTERNS["optimal_pH"],
            all_text, norm_text, selected_variants, float_converter=lambda v: float(v) if 0 <= float(v) <= 14 else None,
            field_name="optimal_pH"
        )

        if ph_prof.get("optimal_pH") is not None and not act.get("conditions", {}).get("pH"):
            act.setdefault("conditions", {})["pH"] = str(ph_prof["optimal_pH"])

        if temp_prof.get("optimal_temperature") is None:
            for orig, norm in search_pairs:
                for pat in _TEMPERATURE_PATTERNS["optimal_temperature"]:
                    m = pat.search(orig)
                    if not m:
                        m = pat.search(norm)
                    if m:
                        temp_prof["optimal_temperature"] = f"{m.group(1)} °C"
                        logger.info(f"[SMN] Fulltext fallback: optimal_temperature={m.group(1)}°C")
                        break
                if temp_prof.get("optimal_temperature") is not None:
                    break
                if temp_prof.get("optimal_temperature") is not None:
                    break



        if sel.get("synthesis_method") is None:
            method_scores = {}
            for method_name, pattern in _SYNTHESIS_METHODS.items():
                if pattern.search(all_text):
                    method_scores[method_name] = method_scores.get(method_name, 0) + 1
            if method_scores:
                best = max(method_scores, key=method_scores.get)
                if best != "general_synthesis" or len(method_scores) == 1:
                    sel["synthesis_method"] = best.replace("_", " ")
                    logger.info(f"[SMN] Fulltext fallback: synthesis_method={best}")

        if sel.get("size") is None:
            for pat in _SIZE_PATTERNS:
                m = pat.search(all_text)
                if m:
                    groups = m.groups()
                    if len(groups) == 3:
                        sel["size"] = f"{groups[0]}-{groups[1]} {groups[2]}"
                        sel["size_unit"] = groups[2]
                    elif len(groups) == 2:
                        sel["size"] = f"{groups[0]} {groups[1]}"
                        sel["size_unit"] = groups[1]
                    logger.info(f"[SMN] Fulltext fallback: size={sel.get('size')}")
                    break

        if sel.get("morphology") is None:
            found_terms = []
            tl = all_text.lower()
            seen_roots = set()
            for term in self._MORPHOLOGY_TERMS:
                root = term.rstrip("s")
                if root in seen_roots:
                    continue
                if term in tl:
                    found_terms.append(term)
                    seen_roots.add(root)
            if found_terms:
                sel["morphology"] = ", ".join(found_terms[:3])
                logger.info(f"[SMN] Fulltext fallback: morphology={sel['morphology']}")

        if sel.get("crystal_structure") is None:
            for pat in _CRYSTAL_STRUCTURE_PATTERNS:
                m = pat.search(all_text)
                if m:
                    groups = m.groups()
                    all_digits = [g for g in groups if g and re.match(r'^\d{3}$', g)]
                    if all_digits:
                        sel["crystal_structure"] = ", ".join(f"({p})" for p in all_digits)
                    elif m.lastindex and m.group(1):
                        raw = m.group(1).strip()
                        if re.match(r'^[\d\s,.\u00c5]+$', raw):
                            pass
                        elif re.match(r'^[\d\s,]+$', raw):
                            planes = re.findall(r'\d{3}', raw)
                            if planes:
                                sel["crystal_structure"] = ", ".join(f"({p})" for p in planes)
                        else:
                            sel["crystal_structure"] = raw.lower()
                    else:
                        match_text = m.group(0).lower()
                        for struct_name in ("spinel", "perovskite", "fluorite", "cubic",
                                           "tetragonal", "hexagonal", "orthorhombic",
                                           "monoclinic", "amorphous", "crystalline",
                                           "anatase", "rutile", "brookite",
                                           "rock salt", "zinc blende", "wurtzite",
                                           "graphitic", "face-centered cubic",
                                           "body-centered cubic"):
                            if struct_name in match_text:
                                sel["crystal_structure"] = struct_name
                                break
                        if sel.get("crystal_structure") is None:
                            planes = re.findall(r'\((\d{3})\)', m.group(0))
                            if planes:
                                sel["crystal_structure"] = ", ".join(f"({p})" for p in planes)
                    logger.info(f"[SMN] Fulltext fallback: crystal_structure={sel.get('crystal_structure')}")
                    break

        act["pH_profile"] = ph_prof
        act["temperature_profile"] = temp_prof

        apps = record.get("applications", [])
        if apps:
            for app in apps:
                if app.get("detection_limit") is None and app.get("application_type") in ("sensing", "detection"):
                    for pat in _LOD_PATTERNS:
                        m = pat.search(all_text)
                        if m:
                            val = m.group(1)
                            unit = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
                            app["detection_limit"] = val
                            app["detection_limit_unit"] = unit
                            logger.info(f"[SMN] Fulltext fallback: LOD={val} {unit}")
                            break
                    if app.get("detection_limit"):
                        break

                if app.get("linear_range") is None and app.get("application_type") in ("sensing", "detection"):
                    for pat in _LINEAR_RANGE_PATTERNS:
                        m = pat.search(all_text)
                        if m:
                            val = m.group(1)
                            unit = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
                            app["linear_range"] = val.replace(" ", "")
                            app["linear_range_unit"] = unit
                            logger.info(f"[SMN] Fulltext fallback: linear_range={val} {unit}")
                            break
                    if app.get("linear_range"):
                        break

        kin = act.get("kinetics", {})
        if not isinstance(kin, dict):
            kin = {}
            act["kinetics"] = kin

        if act.get("enzyme_like_type") is None:
            for pat, etype in _ENZYME_TYPE_PATTERNS:
                if pat.search(all_text):
                    act["enzyme_like_type"] = etype
                    logger.info(f"[SMN] Fulltext fallback: enzyme_like_type={etype}")
                    break

        if kin.get("Km") is None:
            for pat in _KM_PATTERNS:
                found = False
                sentences = all_text.split(".")
                norm_sentences = norm_text.split(".")
                for sent, norm_sent in zip(sentences, norm_sentences):
                    m = pat.search(sent)
                    if not m:
                        m = pat.search(norm_sent)
                    if not m:
                        continue
                    context = sent[max(0, m.start()-100):m.end()+100].lower()
                    has_selected = any(v in context for v in selected_variants if len(v) >= 2)
                    has_this_work = bool(self._THIS_WORK_CONTEXT.search(context))
                    has_contrast = any(kw in context for kw in self._CONTRAST_KEYWORDS)
                    has_negation = bool(self._NEGATION_PHRASES.search(context))
                    if has_negation or (not (has_selected or has_this_work)) or has_contrast:
                        continue
                    val = m.group(1)
                    unit = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
                    parsed = _parse_scientific_notation(val.strip())
                    if isinstance(parsed, (int, float)):
                        kin["Km"] = parsed
                        kin["Km_unit"] = _norm_unit(unit) if unit else unit
                        kin["source"] = "fulltext_fallback_context"
                        logger.info(f"[SMN] Context-aware fallback: Km={parsed} {unit}")
                        found = True
                        break
                if found:
                    break

        if kin.get("Vmax") is None:
            for pat in _VMAX_PATTERNS:
                found = False
                sentences = all_text.split(".")
                norm_sentences = norm_text.split(".")
                for sent, norm_sent in zip(sentences, norm_sentences):
                    m = pat.search(sent)
                    if not m:
                        m = pat.search(norm_sent)
                    if not m:
                        continue
                    context = sent[max(0, m.start()-100):m.end()+100].lower()
                    has_selected = any(v in context for v in selected_variants if len(v) >= 2)
                    has_this_work = bool(self._THIS_WORK_CONTEXT.search(context))
                    has_contrast = any(kw in context for kw in self._CONTRAST_KEYWORDS)
                    has_negation = bool(self._NEGATION_PHRASES.search(context))
                    if has_negation or (not (has_selected or has_this_work)) or has_contrast:
                        continue
                    val = m.group(1)
                    unit = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
                    parsed = _parse_scientific_notation(val.strip())
                    if isinstance(parsed, (int, float)):
                        kin["Vmax"] = parsed
                        kin["Vmax_unit"] = _norm_unit(unit) if unit else unit
                        kin["source"] = "fulltext_fallback_context"
                        logger.info(f"[SMN] Context-aware fallback: Vmax={parsed} {unit}")
                        found = True
                        break
                if found:
                    break

        if act.get("mechanism") is None:
            for pat in _FULLTEXT_MECHANISM_PATTERNS:
                m = pat.search(all_text)
                if m:
                    act["mechanism"] = m.group(0).strip()[:200]
                    logger.info(f"[SMN] Fulltext fallback: mechanism found")
                    break

        if sel.get("stability") is None:
            for pat in _FULLTEXT_STABILITY_PATTERNS:
                m = pat.search(all_text)
                if m:
                    groups = m.groups()
                    if len(groups) >= 2 and groups[0] and groups[1]:
                        sel["stability"] = f"stable for {groups[0]} {groups[1]}"
                    else:
                        sel["stability"] = m.group(0).strip().lower()
                    logger.info(f"[SMN] Fulltext fallback: stability={sel['stability']}")
                    break

        if act.get("conditions", {}).get("reaction_time") is None:
            for pat in _FULLTEXT_REACTION_TIME_PATTERNS:
                m = pat.search(all_text)
                if m:
                    act["conditions"]["reaction_time"] = f"{m.group(1)} {m.group(2)}"
                    logger.info(f"[SMN] Fulltext fallback: reaction_time={m.group(1)} {m.group(2)}")
                    break

        if sel.get("surface_area") is None:
            for pat in _SURFACE_AREA_PATTERNS:
                m = pat.search(all_text)
                if m:
                    sel["surface_area"] = f"{m.group(1)} {m.group(2)}"
                    logger.info(f"[SMN] Fulltext fallback: surface_area={sel['surface_area']}")
                    break

        if sel.get("pore_size") is None:
            for pat in _PORE_SIZE_PATTERNS:
                m = pat.search(all_text)
                if m:
                    sel["pore_size"] = f"{m.group(1)} {m.group(2)}"
                    logger.info(f"[SMN] Fulltext fallback: pore_size={sel['pore_size']}")
                    break

        if sel.get("zeta_potential") is None:
            for pat in _ZETA_POTENTIAL_PATTERNS:
                m = pat.search(all_text)
                if m:
                    sel["zeta_potential"] = f"{m.group(1)} {m.group(2)}"
                    logger.info(f"[SMN] Fulltext fallback: zeta_potential={sel['zeta_potential']}")
                    break

        if kin.get("Km") is None and kin.get("Vmax") is None:
            si_table_ref = re.search(
                r'(?:Table\s+S\d+|Supplementary\s+Table\s+\d+)\s+(?:displays?|shows?|presents?|lists?|summarizes?)\s+.*?(?:Km|Vmax|kinetic)',
                all_text, re.I
            )
            if si_table_ref:
                diag = record.get("diagnostics", {})
                if isinstance(diag, dict):
                    warns = diag.get("warnings", [])
                    if not isinstance(warns, list):
                        warns = []
                    warns.append("kinetics_in_SI_table_unreachable: Km/Vmax values likely in Supporting Information table")
                    diag["warnings"] = warns

    def _build_selected_variants(self, selected_name: str) -> list:
        if not selected_name:
            return []
        variants = [selected_name.lower().strip()]
        if "@" in variants[0]:
            variants.extend(p.strip() for p in variants[0].split("@") if p.strip())
        if "/" in variants[0]:
            variants.extend(p.strip() for p in variants[0].split("/") if p.strip())
        for suffix in (" nanoparticles", " nanosheets", " nanorods",
                       " nanotubes", " nanospheres", " nanozyme",
                       " nanozymes", " catalyst", " nps"):
            if variants[0].endswith(suffix):
                variants.append(variants[0][:-len(suffix)])
        return [v for v in variants if len(v) >= 2]

    _THIS_WORK_CONTEXT = re.compile(
        r'\b(?:this\s+work|this\s+study|current\s+work|current\s+study|present\s+work|present\s+study|'
        r'our\s+(?:nanozyme|catalyst|material|system|sample|result|finding|approach|method|design)|'
        r'the\s+(?:as[-\s]?prepared|as[-\s]?synthesized|above-mentioned|present|proposed|newly\s+developed)\s+'
        r'(?:nanozyme|catalyst|material|system|sample|sensor|platform)|'
        r'herein|as-prepared|as-synthesized|'
        r'proposed\s+(?:nanozyme|catalyst|material|sensor|system|platform)|'
        r'newly\s+(?:synthesized|prepared|developed|designed|fabricated))\b',
        re.I,
    )

    _CONTRAST_KEYWORDS = (
        "in contrast", "compared with", "compared to", "whereas",
        "on the other hand", "higher than", "lower than",
        "previous", "reported", "literature",
        "earlier", "prior", "known", "conventional",
        "commercial", "natural enzyme", "native enzyme",
        "other reported", "previously reported", "recently reported",
        "in previous studies", "in earlier work",
    )

    _NEGATION_PHRASES = re.compile(
        r'\b(?:did\s+not|does\s+not|was\s+not|were\s+not|is\s+not|are\s+not|'
        r'no\s+(?:significant|obvious|remarkable|detectable|measurable|apparent)\s+'
        r'(?:change|difference|effect|increase|decrease|improvement|activity)|'
        r'cannot|could\s+not|failed\s+to|unable\s+to|'
        r'lack\s+of|absence\s+of|without\s+(?:any|significant|obvious))\b',
        re.I,
    )

    def _context_aware_fallback(self, target_dict, field_name, patterns,
                                 all_text, norm_text, selected_variants,
                                 float_converter=None, value_extractor=None):
        if target_dict.get(field_name) is not None:
            return target_dict

        sentences = all_text.split(".")
        norm_sentences = norm_text.split(".")

        for pat in patterns:
            for sent, norm_sent in zip(sentences, norm_sentences):
                m = pat.search(sent)
                if not m:
                    m = pat.search(norm_sent)
                if not m:
                    continue

                context = sent[max(0, m.start()-100):m.end()+100].lower()
                has_selected = any(v in context for v in selected_variants if len(v) >= 2)
                has_this_work = bool(self._THIS_WORK_CONTEXT.search(context))
                has_contrast = any(kw in context for kw in self._CONTRAST_KEYWORDS)
                has_negation = bool(self._NEGATION_PHRASES.search(context))

                if has_negation:
                    continue
                elif has_selected and not has_contrast:
                    pass
                elif has_this_work and not has_contrast:
                    pass
                elif has_contrast:
                    continue
                else:
                    continue

                if float_converter:
                    try:
                        val = float_converter(m.group(1))
                        if val is not None:
                            target_dict[field_name] = val
                            logger.info(f"[SMN] Context-aware fallback: {field_name}={val}")
                            return target_dict
                    except (ValueError, IndexError):
                        pass
                elif value_extractor:
                    result = value_extractor(m)
                    if result is not None:
                        target_dict[field_name] = result
                        logger.info(f"[SMN] Context-aware fallback: {field_name}={result}")
                        return target_dict
                break
            if target_dict.get(field_name) is not None:
                break

        return target_dict
