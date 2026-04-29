import re
import logging
from typing import Dict, List, Optional, Any

from single_main_nanozyme_extractor import _normalize_ocr_scientific, _parse_scientific_notation

logger = logging.getLogger(__name__)

_CAPTION_MATCH_THRESHOLD = 0.4

_KINETICS_CAPTION_PATTERNS = [
    r'(?i)\bkinetic', r'(?i)\bKm\b', r'(?i)\bVmax\b',
    r'(?i)\bMichaelis', r'(?i)\bLineweaver',
    r'(?i)\bcatalytic\s+efficiency',
]

_APPLICATION_CAPTION_PATTERNS = [
    r'(?i)\bdetection\b', r'(?i)\bsensing\b', r'(?i)\bLOD\b',
    r'(?i)\blinear\s+range\b', r'(?i)\bcalibrat',
    r'(?i)\bselectivity\b', r'(?i)\binterfer',
]

_MORPHOLOGY_CAPTION_PATTERNS = [
    r'(?i)\bSEM\b', r'(?i)\bTEM\b', r'(?i)\bAFM\b',
    r'(?i)\bmorpholog', r'(?i)\bsurface\b', r'(?i)\bXRD\b',
    r'(?i)\bXPS\b', r'(?i)\bFT.?IR\b',
]


def assess_caption_match(
    caption: str,
    vlm_result: Dict[str, Any],
) -> float:
    if not caption:
        return 0.0

    fig_type = (vlm_result.get("figure_type") or "").lower()
    caption_lower = caption.lower()

    caption_suggests_kinetics = any(re.search(p, caption_lower) for p in _KINETICS_CAPTION_PATTERNS)
    caption_suggests_application = any(re.search(p, caption_lower) for p in _APPLICATION_CAPTION_PATTERNS)
    caption_suggests_morphology = any(re.search(p, caption_lower) for p in _MORPHOLOGY_CAPTION_PATTERNS)

    vlm_suggests_kinetics = "kinetic" in fig_type or "michaelis" in fig_type
    vlm_suggests_application = "application" in fig_type or "sensing" in fig_type or "calibrat" in fig_type
    vlm_suggests_morphology = "morphology" in fig_type or "sem" in fig_type or "tem" in fig_type or "characteriz" in fig_type

    score = 0.0
    total = 0
    if caption_suggests_kinetics or vlm_suggests_kinetics:
        total += 1
        if caption_suggests_kinetics and vlm_suggests_kinetics:
            score += 1.0
        elif caption_suggests_kinetics or vlm_suggests_kinetics:
            score += 0.3

    if caption_suggests_application or vlm_suggests_application:
        total += 1
        if caption_suggests_application and vlm_suggests_application:
            score += 1.0
        elif caption_suggests_application or vlm_suggests_application:
            score += 0.3

    if caption_suggests_morphology or vlm_suggests_morphology:
        total += 1
        if caption_suggests_morphology and vlm_suggests_morphology:
            score += 1.0
        elif caption_suggests_morphology or vlm_suggests_morphology:
            score += 0.3

    if total == 0:
        return 0.5

    return score / total


def extract_figure_candidates(
    vlm_result: Dict[str, Any],
    caption: str = "",
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []

    extracted = vlm_result.get("extracted_values", {})
    if not isinstance(extracted, dict):
        return candidates

    km_list = extracted.get("Km", [])
    if isinstance(km_list, list):
        for km_entry in km_list:
            if isinstance(km_entry, dict) and km_entry.get("value") is not None:
                candidates.append({
                    "parameter": "Km",
                    "value": km_entry["value"],
                    "unit": km_entry.get("unit"),
                    "material": km_entry.get("material"),
                    "source": "figure_candidate",
                    "needs_review": True,
                    "evidence_text": caption or "",
                })

    vmax_list = extracted.get("Vmax", [])
    if isinstance(vmax_list, list):
        for vmax_entry in vmax_list:
            if isinstance(vmax_entry, dict) and vmax_entry.get("value") is not None:
                candidates.append({
                    "parameter": "Vmax",
                    "value": vmax_entry["value"],
                    "unit": vmax_entry.get("unit"),
                    "material": vmax_entry.get("material"),
                    "source": "figure_candidate",
                    "needs_review": True,
                    "evidence_text": caption or "",
                })

    sensing = extracted.get("sensing_performance", {})
    if isinstance(sensing, dict):
        if sensing.get("LOD") is not None:
            candidates.append({
                "parameter": "LOD",
                "value": sensing["LOD"],
                "source": "figure_candidate",
                "needs_review": True,
                "evidence_text": caption or "",
            })
        if sensing.get("linear_range"):
            candidates.append({
                "parameter": "linear_range",
                "value": sensing["linear_range"],
                "source": "figure_candidate",
                "needs_review": True,
                "evidence_text": caption or "",
            })

    return candidates


def extract_caption_explicit_values(caption: str) -> List[Dict[str, Any]]:
    if not caption:
        return []

    candidates: List[Dict[str, Any]] = []
    norm_caption = _normalize_ocr_scientific(caption)

    km_pat = re.compile(
        r'(?i)K[_\s]?m\s*[=:≈~\u2248]\s*([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)\s*(mM|μM|uM|nM|pM|M)'
    )
    for m in km_pat.finditer(norm_caption):
        candidates.append({
            "parameter": "Km",
            "value": float(m.group(1)),
            "unit": m.group(2),
            "source": "figure_caption",
            "needs_review": False,
            "evidence_text": m.group(0),
        })

    vmax_pat = re.compile(
        r'(?i)V[_\s]?max\s*[=:≈~\u2248]\s*([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)\s*'
        r'((?:mM|μM|uM|nM|pM|M)\s*(?:/?\s*(?:s|min|h))\s*[\u207b\^-]?\s*\d*)'
    )
    for m in vmax_pat.finditer(norm_caption):
        try:
            candidates.append({
                "parameter": "Vmax",
                "value": float(m.group(1)),
                "unit": m.group(2).strip(),
                "source": "figure_caption",
                "needs_review": False,
                "evidence_text": m.group(0),
            })
        except ValueError:
            pass

    vmax_sci_pat = re.compile(
        r'(?i)V[_\s]?max\s*[=:≈~\u2248]\s*([\d.]+)\s*[×x\u00d7]\s*10[\u207b\-–\u2212\u2013](\d+)\s*'
        r'((?:mM|μM|uM|nM|pM|M)\s*[\u00b7/\s]?\s*[sS]\s*[\u207b\^-]?\s*\d*)'
    )
    for m in vmax_sci_pat.finditer(norm_caption):
        try:
            base = float(m.group(1))
            exp = int(m.group(2))
            vmax_val = base * (10 ** -exp)
            candidates.append({
                "parameter": "Vmax",
                "value": vmax_val,
                "unit": m.group(3).strip(),
                "source": "figure_caption",
                "needs_review": True,
                "evidence_text": m.group(0),
            })
        except (ValueError, TypeError):
            pass

    return candidates


class FigureHandler:
    def __init__(self):
        self.warnings: List[str] = []
        self.important_values: List[Dict[str, Any]] = []

    def process_vlm_results(
        self,
        vlm_results: List[Dict[str, Any]],
        selected_nanozyme: str = "",
    ) -> Dict[str, Any]:
        all_candidates: List[Dict[str, Any]] = []
        all_caption_values: List[Dict[str, Any]] = []
        supporting_text: List[str] = []
        low_confidence_count = 0

        for vlm_res in vlm_results:
            if not isinstance(vlm_res, dict) or "error" in vlm_res:
                continue

            source_task = vlm_res.get("_source", {})
            caption = source_task.get("caption", "") or ""

            match_score = assess_caption_match(caption, vlm_res)
            if match_score < _CAPTION_MATCH_THRESHOLD:
                self.warnings.append("caption_match_low_confidence")
                low_confidence_count += 1

            fig_candidates = extract_figure_candidates(vlm_res, caption)
            for c in fig_candidates:
                mat = (c.get("material") or "").lower().strip()
                sel_lower = selected_nanozyme.lower().strip() if selected_nanozyme else ""
                if mat and sel_lower and mat not in sel_lower and sel_lower not in mat:
                    c["reason"] = "material_mismatch_in_figure"
                all_candidates.append(c)

            caption_values = extract_caption_explicit_values(caption)
            all_caption_values.extend(caption_values)

            observations = vlm_res.get("observations", [])
            if isinstance(observations, list):
                for obs in observations:
                    if isinstance(obs, str) and obs.strip():
                        supporting_text.append(obs.strip())

            linked_mat = vlm_res.get("linked_material_mentions", [])
            if isinstance(linked_mat, list):
                for lm in linked_mat:
                    if isinstance(lm, str) and lm.strip():
                        supporting_text.append(f"linked material: {lm.strip()}")

        for c in all_candidates:
            self.important_values.append({
                "parameter": c.get("parameter", ""),
                "value": c.get("value"),
                "unit": c.get("unit"),
                "material": c.get("material", ""),
                "source": "figure_candidate",
                "reason": c.get("reason", "from_vlm_figure"),
                "needs_review": True,
                "evidence_text": c.get("evidence_text", ""),
            })

        return {
            "figure_candidates": all_candidates,
            "caption_explicit_values": all_caption_values,
            "supporting_text": supporting_text,
            "low_confidence_count": low_confidence_count,
        }

    def get_warnings(self) -> List[str]:
        return list(dict.fromkeys(self.warnings))

    def get_important_values(self) -> List[Dict[str, Any]]:
        return self.important_values
