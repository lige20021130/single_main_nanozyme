import json
import re
import sys
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)

_NUMERIC_FIELDS = {
    "Km", "Vmax", "kcat", "kcat_Km",
    "optimal_pH", "optimal_temperature", "size",
}

_NUMERIC_TOLERANCE = 0.1

_UNIT_CONVERSIONS = {
    ("mM", "M"): 1e-3,
    ("μM", "M"): 1e-6,
    ("uM", "M"): 1e-6,
    ("nM", "M"): 1e-9,
    ("pM", "M"): 1e-12,
    ("mmol/L", "mM"): 1.0,
    ("umol/L", "μM"): 1.0,
    ("nmol/L", "nM"): 1.0,
}

_BASE_UNITS = {
    "Km": "mM",
    "Vmax": "M/s",
    "kcat": "s^-1",
    "kcat_Km": "M^-1 s^-1",
    "size": "nm",
    "detection_limit": "μM",
}


def _to_float(val) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        val = val.strip()
        try:
            return float(val)
        except ValueError:
            pass
        m = re.match(r'([\d.]+)\s*[×x\u00d7]\s*10[\u207b\u2212\u2013\-]?\s*(\d+)', val)
        if m:
            base = float(m.group(1))
            exp = int(m.group(2))
            has_neg = bool(re.search(r'10[\u207b\u2212\u2013\-]', val))
            return base * (10 ** (-exp if has_neg else exp))
        m = re.match(r'([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)', val)
        if m:
            base = float(m.group(1))
            exp = int(m.group(2).replace('−', '-').replace('\u2212', '-'))
            return base * (10 ** exp)
    return None


def _convert_unit(value: float, from_unit: str, to_unit: str) -> Optional[float]:
    if from_unit == to_unit:
        return value
    fu = from_unit.strip().replace(' ', '').replace('⁻¹', '^-1').replace('·', '/')
    tu = to_unit.strip().replace(' ', '').replace('⁻¹', '^-1').replace('·', '/')
    if fu == tu:
        return value
    key = (fu, tu)
    if key in _UNIT_CONVERSIONS:
        return value * _UNIT_CONVERSIONS[key]
    rev_key = (tu, fu)
    if rev_key in _UNIT_CONVERSIONS:
        factor = _UNIT_CONVERSIONS[rev_key]
        if factor != 0:
            return value / factor
    return None


def _compare_string(extracted: Any, gold: Any) -> Dict[str, Any]:
    if gold is None:
        return {"match": "skip", "reason": "gold_is_null"}
    if extracted is None:
        return {"match": "miss", "reason": "extracted_is_null"}
    e_str = str(extracted).strip().lower()
    g_str = str(gold).strip().lower()
    if e_str == g_str:
        return {"match": "exact"}
    if e_str in g_str or g_str in e_str:
        return {"match": "partial"}
    return {"match": "wrong", "extracted": str(extracted), "gold": str(gold)}


def _compare_numeric(extracted: Any, gold: Any, e_unit: str = None, g_unit: str = None) -> Dict[str, Any]:
    if gold is None:
        return {"match": "skip", "reason": "gold_is_null"}
    if extracted is None:
        return {"match": "miss", "reason": "extracted_is_null"}
    e_val = _to_float(extracted)
    g_val = _to_float(gold)
    if e_val is None or g_val is None:
        return _compare_string(extracted, gold)
    if e_unit and g_unit and e_unit != g_unit:
        converted = _convert_unit(e_val, e_unit, g_unit)
        if converted is not None:
            e_val = converted
        else:
            return {"match": "unit_mismatch", "extracted": e_val, "gold": g_val,
                    "e_unit": e_unit, "g_unit": g_unit}
    if g_val == 0 and e_val == 0:
        return {"match": "exact", "error": 0.0}
    denom = max(abs(g_val), 1e-15)
    rel_error = abs(e_val - g_val) / denom
    if rel_error < _NUMERIC_TOLERANCE:
        return {"match": "exact", "error": round(rel_error, 6)}
    if rel_error < 0.5:
        return {"match": "approximate", "error": round(rel_error, 6),
                "extracted": e_val, "gold": g_val}
    return {"match": "wrong", "error": round(rel_error, 6),
            "extracted": e_val, "gold": g_val}


def _get_nested(d: Dict, path: str) -> Any:
    keys = path.split(".")
    current = d
    for k in keys:
        if isinstance(current, dict):
            current = current.get(k)
        else:
            return None
        if current is None:
            return None
    return current


_EVAL_FIELDS = [
    ("selected_nanozyme.name", "string"),
    ("selected_nanozyme.composition", "string"),
    ("selected_nanozyme.morphology", "string"),
    ("selected_nanozyme.size", "numeric"),
    ("selected_nanozyme.size_unit", "string"),
    ("selected_nanozyme.synthesis_method", "string"),
    ("selected_nanozyme.crystal_structure", "string"),
    ("main_activity.enzyme_like_type", "string"),
    ("main_activity.substrates", "list"),
    ("main_activity.assay_method", "string"),
    ("main_activity.signal", "string"),
    ("main_activity.conditions.buffer", "string"),
    ("main_activity.conditions.pH", "numeric"),
    ("main_activity.conditions.temperature", "numeric"),
    ("main_activity.pH_profile.optimal_pH", "numeric"),
    ("main_activity.pH_profile.pH_range", "string"),
    ("main_activity.temperature_profile.optimal_temperature", "numeric"),
    ("main_activity.kinetics.Km", "numeric"),
    ("main_activity.kinetics.Km_unit", "string"),
    ("main_activity.kinetics.Vmax", "numeric"),
    ("main_activity.kinetics.Vmax_unit", "string"),
    ("main_activity.kinetics.kcat", "numeric"),
    ("main_activity.kinetics.kcat_unit", "string"),
    ("main_activity.kinetics.substrate", "string"),
    ("main_activity.mechanism", "string"),
]

_KINETICS_NUMERIC_PAIRS = [
    ("main_activity.kinetics.Km", "main_activity.kinetics.Km_unit"),
    ("main_activity.kinetics.Vmax", "main_activity.kinetics.Vmax_unit"),
    ("main_activity.kinetics.kcat", "main_activity.kinetics.kcat_unit"),
    ("main_activity.kinetics.kcat_Km", "main_activity.kinetics.kcat_Km_unit"),
]


def _compare_list(extracted: Any, gold: Any) -> Dict[str, Any]:
    if gold is None:
        return {"match": "skip", "reason": "gold_is_null"}
    if extracted is None:
        return {"match": "miss", "reason": "extracted_is_null"}
    if not isinstance(extracted, list):
        extracted = [extracted] if extracted else []
    if not isinstance(gold, list):
        gold = [gold] if gold else []
    e_set = {str(x).strip().lower() for x in extracted if x is not None}
    g_set = {str(x).strip().lower() for x in gold if x is not None}
    if not g_set:
        return {"match": "skip", "reason": "gold_is_empty"}
    if not e_set:
        return {"match": "miss", "reason": "extracted_is_empty"}
    intersection = e_set & g_set
    if intersection == g_set and intersection == e_set:
        return {"match": "exact"}
    if intersection:
        precision = len(intersection) / len(e_set) if e_set else 0
        recall = len(intersection) / len(g_set) if g_set else 0
        return {"match": "partial", "precision": round(precision, 3),
                "recall": round(recall, 3)}
    return {"match": "wrong", "extracted": list(e_set), "gold": list(g_set)}


def _compare_applications(extracted_apps: List[Dict], gold_apps: List[Dict]) -> Dict[str, Any]:
    if not gold_apps:
        return {"match": "skip", "reason": "gold_is_empty"}
    if not extracted_apps:
        return {"match": "miss", "reason": "extracted_is_empty"}
    results = []
    for g_app in gold_apps:
        g_analyte = (g_app.get("target_analyte") or "").lower().strip()
        g_type = (g_app.get("application_type") or "").lower().strip()
        best_match = None
        best_score = 0
        for e_app in extracted_apps:
            score = 0
            e_analyte = (e_app.get("target_analyte") or "").lower().strip()
            e_type = (e_app.get("application_type") or "").lower().strip()
            if g_analyte and e_analyte:
                if g_analyte == e_analyte:
                    score += 3
                elif g_analyte in e_analyte or e_analyte in g_analyte:
                    score += 2
            if g_type and e_type:
                if g_type == e_type:
                    score += 2
                elif g_type in e_type or e_type in g_type:
                    score += 1
            if score > best_score:
                best_score = score
                best_match = e_app
        app_result = {"gold_analyte": g_app.get("target_analyte"),
                      "gold_type": g_app.get("application_type"),
                      "matched": best_score >= 2}
        if best_match:
            app_result["extracted_analyte"] = best_match.get("target_analyte")
            app_result["extracted_type"] = best_match.get("application_type")
            g_lod = g_app.get("detection_limit")
            e_lod = best_match.get("detection_limit")
            if g_lod is not None and e_lod is not None:
                lod_cmp = _compare_numeric(e_lod, g_lod)
                app_result["lod_match"] = lod_cmp["match"]
        results.append(app_result)
    matched_count = sum(1 for r in results if r["matched"])
    total = len(results)
    recall = matched_count / total if total > 0 else 0
    precision = matched_count / len(extracted_apps) if extracted_apps else 0
    return {"match": "partial" if recall < 1.0 else "exact",
            "recall": round(recall, 3), "precision": round(precision, 3),
            "details": results}


class Evaluator:
    def __init__(self, tolerance: float = 0.1):
        self.tolerance = tolerance
        self.results: List[Dict[str, Any]] = []
        self.global_stats: Dict[str, Any] = {}

    def compare_records(self, extracted: Dict, gold: Dict, paper_id: str = "") -> Dict[str, Any]:
        field_results = {}
        errors = []

        for field_path, field_type in _EVAL_FIELDS:
            e_val = _get_nested(extracted, field_path)
            g_val = _get_nested(gold, field_path)
            if field_type == "numeric":
                e_unit = None
                g_unit = None
                for val_path, unit_path in _KINETICS_NUMERIC_PAIRS:
                    if field_path == val_path:
                        e_unit = _get_nested(extracted, unit_path)
                        g_unit = _get_nested(gold, unit_path)
                        break
                cmp = _compare_numeric(e_val, g_val, e_unit, g_unit)
            elif field_type == "list":
                cmp = _compare_list(e_val, g_val)
            else:
                cmp = _compare_string(e_val, g_val)
            field_results[field_path] = cmp
            if cmp["match"] in ("wrong", "unit_mismatch"):
                errors.append({"field": field_path, **cmp})

        e_apps = extracted.get("applications", [])
        g_apps = gold.get("applications", [])
        app_result = _compare_applications(e_apps, g_apps)
        field_results["applications"] = app_result

        tp = sum(1 for r in field_results.values() if r["match"] in ("exact", "approximate"))
        fp_fn = sum(1 for r in field_results.values() if r["match"] in ("wrong", "miss", "unit_mismatch"))
        total_evaluable = sum(1 for r in field_results.values() if r["match"] != "skip")
        accuracy = tp / total_evaluable if total_evaluable > 0 else 0

        numeric_errors = []
        for field_path, field_type in _EVAL_FIELDS:
            if field_type == "numeric":
                r = field_results.get(field_path, {})
                if r.get("error") is not None:
                    g_val = _get_nested(gold, field_path)
                    numeric_errors.append({"field": field_path, "error": r["error"],
                                           "gold_value": g_val})
        mae = 0.0
        magnitude_accuracy = 0.0
        if numeric_errors:
            mae = sum(e["error"] for e in numeric_errors) / len(numeric_errors)
            magnitude_accuracy = sum(1 for e in numeric_errors if e["error"] < 1.0) / len(numeric_errors)

        result = {
            "paper_id": paper_id,
            "field_results": field_results,
            "accuracy": round(accuracy, 4),
            "errors": errors,
            "mae": round(mae, 6),
            "magnitude_accuracy": round(magnitude_accuracy, 4),
            "total_fields": len(field_results),
            "evaluable_fields": total_evaluable,
        }
        self.results.append(result)
        return result

    def compute_global_stats(self) -> Dict[str, Any]:
        if not self.results:
            return {}
        field_stats = defaultdict(lambda: {"tp": 0, "fp_fn": 0, "skip": 0, "total": 0})
        for result in self.results:
            for field_path, cmp in result.get("field_results", {}).items():
                field_stats[field_path]["total"] += 1
                if cmp["match"] in ("exact", "approximate"):
                    field_stats[field_path]["tp"] += 1
                elif cmp["match"] == "skip":
                    field_stats[field_path]["skip"] += 1
                else:
                    field_stats[field_path]["fp_fn"] += 1

        per_field = {}
        for field, stats in field_stats.items():
            evaluable = stats["total"] - stats["skip"]
            if evaluable > 0:
                precision = stats["tp"] / evaluable
                recall = stats["tp"] / evaluable
                f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            else:
                precision = recall = f1 = 0
            per_field[field] = {
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
                "evaluable": evaluable,
            }

        field_groups = {
            "paper": [f for f in per_field if f.startswith("paper.")],
            "selected_nanozyme": [f for f in per_field if f.startswith("selected_nanozyme.")],
            "main_activity.conditions": [f for f in per_field if f.startswith("main_activity.conditions.")],
            "main_activity.pH_profile": [f for f in per_field if f.startswith("main_activity.pH_profile.")],
            "main_activity.temperature_profile": [f for f in per_field if f.startswith("main_activity.temperature_profile.")],
            "main_activity.kinetics": [f for f in per_field if f.startswith("main_activity.kinetics.")],
            "main_activity.other": [f for f in per_field if f.startswith("main_activity.") and
                                    not any(f.startswith(p) for p in
                                            ["main_activity.conditions", "main_activity.pH_profile",
                                             "main_activity.temperature_profile", "main_activity.kinetics"])],
            "applications": ["applications"],
        }

        group_stats = {}
        for group_name, fields in field_groups.items():
            group_f1s = [per_field[f]["f1"] for f in fields if f in per_field]
            group_recalls = [per_field[f]["recall"] for f in fields if f in per_field]
            group_precisions = [per_field[f]["precision"] for f in fields if f in per_field]
            if group_f1s:
                group_stats[group_name] = {
                    "avg_f1": round(sum(group_f1s) / len(group_f1s), 4),
                    "avg_precision": round(sum(group_precisions) / len(group_precisions), 4),
                    "avg_recall": round(sum(group_recalls) / len(group_recalls), 4),
                    "field_count": len(group_f1s),
                }

        all_maes = [r["mae"] for r in self.results if r["mae"] > 0]
        all_mag_accs = [r["magnitude_accuracy"] for r in self.results]
        global_accuracy = sum(r["accuracy"] for r in self.results) / len(self.results)

        self.global_stats = {
            "total_papers": len(self.results),
            "global_accuracy": round(global_accuracy, 4),
            "avg_mae": round(sum(all_maes) / len(all_maes), 6) if all_maes else 0,
            "avg_magnitude_accuracy": round(sum(all_mag_accs) / len(all_mag_accs), 4) if all_mag_accs else 0,
            "per_field": per_field,
            "per_group": group_stats,
        }
        return self.global_stats

    def generate_report(self, output_path: str = None) -> str:
        stats = self.compute_global_stats()
        lines = []
        lines.append("# Nanozyme Extraction Evaluation Report")
        lines.append("")
        lines.append(f"## Global Metrics")
        lines.append(f"- Total papers: {stats['total_papers']}")
        lines.append(f"- Global accuracy: {stats['global_accuracy']:.2%}")
        lines.append(f"- Average MAE: {stats['avg_mae']:.6f}")
        lines.append(f"- Average magnitude accuracy: {stats['avg_magnitude_accuracy']:.2%}")
        lines.append("")
        lines.append("## Per-Group Metrics")
        lines.append("| Group | Avg F1 | Avg Precision | Avg Recall | Fields |")
        lines.append("|-------|--------|---------------|------------|--------|")
        for group, gs in stats.get("per_group", {}).items():
            lines.append(f"| {group} | {gs['avg_f1']:.4f} | {gs['avg_precision']:.4f} | {gs['avg_recall']:.4f} | {gs['field_count']} |")
        lines.append("")
        lines.append("## Per-Field Metrics")
        lines.append("| Field | Precision | Recall | F1 | Evaluable |")
        lines.append("|-------|-----------|--------|----|----------|")
        for field, fs in stats.get("per_field", {}).items():
            lines.append(f"| {field} | {fs['precision']:.4f} | {fs['recall']:.4f} | {fs['f1']:.4f} | {fs['evaluable']} |")
        lines.append("")
        lines.append("## Per-Paper Results")
        lines.append("| Paper | Accuracy | MAE | Mag.Acc | Errors |")
        lines.append("|-------|----------|-----|---------|--------|")
        for r in self.results:
            err_count = len(r.get("errors", []))
            lines.append(f"| {r['paper_id']} | {r['accuracy']:.2%} | {r['mae']:.6f} | {r['magnitude_accuracy']:.2%} | {err_count} |")
        report = "\n".join(lines)
        if output_path:
            Path(output_path).write_text(report, encoding="utf-8")
        return report

    def save_results_json(self, output_path: str):
        output = {
            "global_stats": self.global_stats,
            "per_paper_results": self.results,
        }
        Path(output_path).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


def evaluate_single(extracted_path: str, gold_path: str) -> Dict[str, Any]:
    with open(extracted_path, "r", encoding="utf-8") as f:
        extracted = json.load(f)
    with open(gold_path, "r", encoding="utf-8") as f:
        gold = json.load(f)
    evaluator = Evaluator()
    paper_id = Path(gold_path).stem
    return evaluator.compare_records(extracted, gold, paper_id)


def evaluate_batch(extracted_dir: str, gold_dir: str,
                   output_json: str = None, output_md: str = None) -> Dict[str, Any]:
    extracted_path = Path(extracted_dir)
    gold_path = Path(gold_dir)
    evaluator = Evaluator()
    gold_files = list(gold_path.glob("*.json"))
    gold_files = [f for f in gold_files if f.name != "gold_standard_template.json"]
    for gf in gold_files:
        paper_id = gf.stem
        ef = extracted_path / f"{paper_id}.json"
        if not ef.exists():
            ef = extracted_path / gf.name
        if not ef.exists():
            logger.warning(f"No extracted result for {paper_id}")
            continue
        try:
            with open(ef, "r", encoding="utf-8") as f:
                extracted = json.load(f)
            with open(gf, "r", encoding="utf-8") as f:
                gold = json.load(f)
            evaluator.compare_records(extracted, gold, paper_id)
        except Exception as e:
            logger.error(f"Error evaluating {paper_id}: {e}")
    if output_json:
        evaluator.save_results_json(output_json)
    report = evaluator.generate_report(output_md)
    return evaluator.compute_global_stats()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 3:
        print("Usage: python evaluate.py <extracted_dir> <gold_dir> [output.json] [output.md]")
        sys.exit(1)
    edir = sys.argv[1]
    gdir = sys.argv[2]
    ojson = sys.argv[3] if len(sys.argv) > 3 else None
    omd = sys.argv[4] if len(sys.argv) > 4 else None
    stats = evaluate_batch(edir, gdir, ojson, omd)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
