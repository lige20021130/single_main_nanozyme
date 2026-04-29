import re
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

APPLICATION_TYPES = {
    "biosensing", "colorimetric_sensing", "fluorescence_sensing",
    "electrochemical_sensing", "SERS_sensing", "therapeutic",
    "antibacterial", "antioxidant", "environmental_detection",
    "food_safety", "diagnostic", "other",
}

APPLICATION_TYPE_PATTERNS = {
    "colorimetric_sensing": [
        r'(?i)colorimetric\s+(?:detection|sensing|assay|sensor)',
        r'(?i)colorimetric\s+determination',
    ],
    "fluorescence_sensing": [
        r'(?i)fluorescen\w*\s+(?:detection|sensing|assay|sensor|probe)',
        r'(?i)fluorometric\s+(?:detection|assay)',
    ],
    "electrochemical_sensing": [
        r'(?i)electrochem\w*\s+(?:detection|sensing|sensor|assay)',
        r'(?i)amperometric\s+(?:detection|sensor)',
        r'(?i)voltammetric\s+(?:detection|sensor)',
    ],
    "SERS_sensing": [
        r'(?i)SERS\s+(?:detection|sensing|sensor|assay|substrate)',
        r'(?i)surface.enhanced\s+raman',
    ],
    "biosensing": [
        r'(?i)biosens(?:or|ing)',
        r'(?i)sensing\s+platform',
    ],
    "therapeutic": [
        r'(?i)therap\w+',
        r'(?i)tumou?r\s+therapy',
        r'(?i)cancer\s+therapy',
        r'(?i)wound\s+heal',
        r'(?i)anti.?tumor',
    ],
    "antibacterial": [
        r'(?i)antibacteri\w+',
        r'(?i)bacteri\w*\s+kill',
        r'(?i)disinfect',
        r'(?i)anti.?microbial',
    ],
    "antioxidant": [
        r'(?i)antioxidant',
        r'(?i)ROS\s+scaveng',
        r'(?i)cytoprotect',
        r'(?i)anti.?inflammatory',
        r'(?i)radical\s+scaveng',
    ],
    "environmental_detection": [
        r'(?i)environment\w*\s+(?:detection|monitor)',
        r'(?i)pollutant\s+(?:detection|degrad)',
        r'(?i)water\s+(?:treatment|monitor|detection)',
        r'(?i)degrad\w+\s+pollutant',
    ],
    "food_safety": [
        r'(?i)food\s+safety',
        r'(?i)food\s+(?:detection|quality|monitor)',
    ],
    "diagnostic": [
        r'(?i)diagnos\w+',
        r'(?i)clinical\s+(?:detection|assay|test)',
        r'(?i)point.of.care',
    ],
}

METHOD_PATTERNS = {
    "colorimetric": r'(?i)colorimetric|colorimetry|absorbance|UV.vis',
    "fluorescence": r'(?i)fluorescen\w*|fluorometric|fluorimetric',
    "SERS": r'(?i)SERS|surface.enhanced\s+raman',
    "electrochemical": r'(?i)electrochem\w*|amperometric|voltammetric|impedance',
}

SAMPLE_TYPE_PATTERNS = {
    "serum": r'(?i)\bserum\b',
    "water": r'(?i)\bwater\s+(?:sample|sample)?\b',
    "food": r'(?i)\bfood\s+(?:sample|extract)?\b',
    "cell": r'(?i)\bcell\b|\bcellular\b|\bin\s+vitro\b|\bin\s+vivo\b',
    "urine": r'(?i)\burine\b',
    "plasma": r'(?i)\bplasma\b',
    "blood": r'(?i)\bblood\b',
    "saliva": r'(?i)\bsaliva\b',
    "environmental": r'(?i)\benvironmental\s+sample\b|\briver\b|\blake\b|\btap\s+water\b',
}

_KNOWN_SUBSTRATES = {
    "tmb", "abts", "opd", "h2o2", "h2o2", "dcfh-da", "dcfh",
    "l-ascorbic acid", "ascorbic acid", "dopamine hydrochloride",
    "amplex red", "taed", "guaiacol", "pyrogallol", "catechol",
    "o-phenylenediamine", "3,3',5,5'-tetramethylbenzidine",
    "2,2'-azino-bis", "nadh", "nadph",
}

_KNOWN_ANALYTES = {
    "glucose", "h2o2", "hydrogen peroxide", "cysteine", "cys",
    "cu2+", "cu+", "fe2+", "fe3+", "hg2+", "pb2+", "cd2+",
    "ascorbic acid", "aa", "dopamine", "ua", "uric acid",
    "sulfite", "phenol", "bisphenol", "bpa",
    "cancer cells", "tumor cells", "hepg2", "mcf-7", "4t1",
    "glutathione", "gsh", "l-cysteine",
    "cholesterol", "lactate", "xanthine", "hypoxanthine",
    "malathion", "paraoxon", "carbaryl", "atrazine",
    "escherichia coli", "e. coli", "s. aureus",
    "cr(vi)", "cr6+", "mn2+", "zn2+", "ag+", "al3+",
}


def classify_application_type(desc: str, app_type_raw: str = "") -> str:
    combined = (desc + " " + app_type_raw).lower()
    for app_type, patterns in APPLICATION_TYPE_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, combined):
                return app_type
    return "other"


def extract_method(desc: str) -> Optional[str]:
    for method, pat in METHOD_PATTERNS.items():
        if re.search(pat, desc):
            return method
    return None


def extract_sample_type(desc: str) -> Optional[str]:
    for stype, pat in SAMPLE_TYPE_PATTERNS.items():
        if re.search(pat, desc):
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
