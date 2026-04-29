import re
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

TABLE_TYPE_KEYWORDS = {
    "kinetics_table": [
        r'(?i)\bkm\b', r'(?i)\bvmax\b', r'(?i)\bkcat\b',
        r'(?i)\bmichaelis', r'(?i)\bkinetic\s+param',
        r'(?i)\baffinity\s+constant',
    ],
    "sensing_performance_table": [
        r'(?i)\bLOD\b', r'(?i)\bdetection\s+limit\b',
        r'(?i)\blinear\s+range\b', r'(?i)\bsensitivity\b',
        r'(?i)\bsensing\s+performance\b',
        r'(?i)\btarget\s+analyte\b',
    ],
    "comparison_table": [
        r'(?i)\bcomparison\b', r'(?i)\bcompare\b',
        r'(?i)\bpreviously\s+reported\b',
        r'(?i)\bref\b.*\bref\b',
        r'(?i)\bliterature\b',
    ],
    "recovery_table": [
        r'(?i)\brecovery\b', r'(?i)\bspiked?\b',
        r'(?i)\bfound\b.*\badded\b', r'(?i)\bRSD\b',
        r'(?i)\bprecision\b',
    ],
    "characterization_table": [
        r'(?i)\bBET\b', r'(?i)\bsurface\s+area\b',
        r'(?i)\bparticle\s+size\b', r'(?i)\bzeta\s+potential\b',
        r'(?i)\bXPS\b', r'(?i)\bXRD\b',
        r'(?i)\bICP\b', r'(?i)\bcomposition\b',
        r'(?i)\bcrystallite\b', r'(?i)\blattice\b',
    ],
}

_THIS_WORK_PATTERNS = [
    r'(?i)\bthis\s+work\b',
    r'(?i)\bcurrent\s+work\b',
    r'(?i)\bpresent\s+work\b',
    r'(?i)\bour\s+(?:work|study|material|catalyst|nanozyme|system)\b',
    r'(?i)\bproposed\s+(?:method|sensor|catalyst|nanozyme)\b',
    r'(?i)\bthis\s+(?:study|paper|article|report)\b',
]


def classify_table(
    caption: str = "",
    headers: str = "",
    content_text: str = "",
    existing_type: str = "",
) -> str:
    combined = (caption + " " + headers + " " + content_text).strip()
    if existing_type and existing_type in TABLE_TYPE_KEYWORDS:
        return existing_type

    scores: Dict[str, int] = {}
    for tbl_type, patterns in TABLE_TYPE_KEYWORDS.items():
        score = 0
        for pat in patterns:
            if re.search(pat, combined):
                score += 1
        if score > 0:
            scores[tbl_type] = score

    if not scores:
        return "general_table"

    priority_order = [
        "kinetics_table", "sensing_performance_table",
        "comparison_table", "recovery_table", "characterization_table",
    ]
    best_score = max(scores.values())
    for tbl_type in priority_order:
        if scores.get(tbl_type, 0) == best_score:
            return tbl_type

    return max(scores, key=scores.get)


def is_this_work_row(row_text: str) -> bool:
    if not row_text:
        return False
    for pat in _THIS_WORK_PATTERNS:
        if re.search(pat, row_text):
            return True
    return False


def filter_comparison_table_records(
    records: List[Dict[str, Any]],
    selected_nanozyme: str = "",
) -> List[Dict[str, Any]]:
    if not records:
        return []

    filtered: List[Dict[str, Any]] = []
    sel_lower = selected_nanozyme.lower().strip() if selected_nanozyme else ""

    for rec in records:
        row_text = " ".join(str(v) for v in rec.values() if v is not None)
        if is_this_work_row(row_text):
            filtered.append(rec)
            continue
        mat = (rec.get("material") or "").lower().strip()
        if sel_lower and mat and (sel_lower in mat or mat in sel_lower):
            filtered.append(rec)
            continue

    return filtered


def filter_recovery_table_records(
    records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not records:
        return []

    allowed_fields = {
        "target_analyte", "sample_type", "recovery",
        "added", "found", "RSD", "recovery_percent",
        "sample", "spiked_concentration", "detected_concentration",
    }

    filtered: List[Dict[str, Any]] = []
    for rec in records:
        clean: Dict[str, Any] = {}
        for k, v in rec.items():
            k_lower = k.lower().strip()
            if k_lower in allowed_fields or any(af in k_lower for af in allowed_fields):
                clean[k] = v
        if clean:
            filtered.append(clean)

    return filtered


class TableClassifier:
    def __init__(self):
        self.warnings: List[str] = []
        self._classified: List[Dict[str, Any]] = []

    def classify_and_filter(
        self,
        table_summaries: List[Dict[str, Any]],
        selected_nanozyme: str = "",
    ) -> List[Dict[str, Any]]:
        self._classified = []
        sel_lower = selected_nanozyme.lower().strip() if selected_nanozyme else ""

        for tbl in table_summaries:
            caption = tbl.get("caption", "") or ""
            headers = tbl.get("headers", "") or ""
            content = tbl.get("content_text", "") or tbl.get("markdown", "") or ""
            existing_type = tbl.get("table_type", "")

            tbl_type = classify_table(caption, headers, content, existing_type)

            records = tbl.get("records", [])
            if not isinstance(records, list):
                records = []

            if tbl_type == "comparison_table":
                records = filter_comparison_table_records(records, selected_nanozyme)
                other_mats = []
                for rec in tbl.get("records", []):
                    if isinstance(rec, dict):
                        mat = (rec.get("material") or "").strip()
                        row_text = " ".join(str(v) for v in rec.values() if v is not None)
                        if mat and not is_this_work_row(row_text):
                            if sel_lower and mat.lower().strip() not in sel_lower and sel_lower not in mat.lower().strip():
                                other_mats.append(mat)
                if other_mats:
                    logger.info(
                        f"[TableClassifier] comparison_table 中的非本工作材料已过滤: {other_mats}"
                    )

            elif tbl_type == "recovery_table":
                records = filter_recovery_table_records(records)

            elif tbl_type == "general_table":
                records = []

            classified_tbl = {
                "table_id": tbl.get("table_id", ""),
                "table_type": tbl_type,
                "caption": caption,
                "records": records,
                "source_page": tbl.get("source_page") or tbl.get("page"),
            }
            self._classified.append(classified_tbl)

        return self._classified

    def get_kinetics_tables(self) -> List[Dict[str, Any]]:
        return [t for t in self._classified if t["table_type"] == "kinetics_table"]

    def get_sensing_tables(self) -> List[Dict[str, Any]]:
        return [t for t in self._classified if t["table_type"] == "sensing_performance_table"]

    def get_comparison_tables(self) -> List[Dict[str, Any]]:
        return [t for t in self._classified if t["table_type"] == "comparison_table"]

    def get_recovery_tables(self) -> List[Dict[str, Any]]:
        return [t for t in self._classified if t["table_type"] == "recovery_table"]

    def get_characterization_tables(self) -> List[Dict[str, Any]]:
        return [t for t in self._classified if t["table_type"] == "characterization_table"]

    def get_warnings(self) -> List[str]:
        return list(dict.fromkeys(self.warnings))
