import json
import sys
import logging
from pathlib import Path
from typing import Dict, List, Any
from collections import Counter, defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)


def load_results(results_dir: str) -> List[Dict[str, Any]]:
    results = []
    p = Path(results_dir)
    for jf in p.glob("*.json"):
        try:
            with open(jf, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["_source_file"] = jf.name
            results.append(data)
        except Exception as e:
            logger.warning(f"Failed to load {jf}: {e}")
    return results


def compute_statistics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not results:
        return {"total": 0}

    total = len(results)
    status_counts = Counter()
    enzyme_type_counts = Counter()
    app_type_counts = Counter()
    field_fill_rates = defaultdict(lambda: {"filled": 0, "total": 0})
    km_values = []
    vmax_values = []
    size_values = []
    detection_limits = []
    warnings_counts = Counter()
    has_kinetics = 0
    has_applications = 0
    has_mechanism = 0

    for r in results:
        diag = r.get("diagnostics", {})
        status_counts[diag.get("status", "unknown")] += 1
        for w in diag.get("warnings", []):
            w_key = w.split(":")[0] if ":" in w else w
            warnings_counts[w_key] += 1

        act = r.get("main_activity", {})
        etype = act.get("enzyme_like_type")
        if etype:
            enzyme_type_counts[etype] += 1

        kin = act.get("kinetics", {})
        if kin.get("Km") is not None or kin.get("Vmax") is not None:
            has_kinetics += 1
        if kin.get("Km") is not None:
            try:
                km_values.append(float(kin["Km"]))
            except (ValueError, TypeError):
                pass
        if kin.get("Vmax") is not None:
            try:
                vmax_values.append(float(kin["Vmax"]))
            except (ValueError, TypeError):
                pass

        if act.get("mechanism"):
            has_mechanism += 1

        apps = r.get("applications", [])
        if apps:
            has_applications += 1
        for app in apps:
            at = app.get("application_type")
            if at:
                app_type_counts[at] += 1
            dl = app.get("detection_limit")
            if dl is not None:
                try:
                    detection_limits.append(float(dl))
                except (ValueError, TypeError):
                    pass

        sel = r.get("selected_nanozyme", {})
        if sel.get("size") is not None:
            try:
                size_values.append(float(sel["size"]))
            except (ValueError, TypeError):
                pass

        _TRACK_FIELDS = [
            ("selected_nanozyme.name", sel.get("name")),
            ("selected_nanozyme.composition", sel.get("composition")),
            ("selected_nanozyme.morphology", sel.get("morphology")),
            ("selected_nanozyme.size", sel.get("size")),
            ("main_activity.enzyme_like_type", etype),
            ("main_activity.substrates", act.get("substrates")),
            ("main_activity.assay_method", act.get("assay_method")),
            ("main_activity.signal", act.get("signal")),
            ("main_activity.conditions.pH", act.get("conditions", {}).get("pH")),
            ("main_activity.conditions.temperature", act.get("conditions", {}).get("temperature")),
            ("main_activity.conditions.buffer", act.get("conditions", {}).get("buffer")),
            ("main_activity.pH_profile.optimal_pH", act.get("pH_profile", {}).get("optimal_pH")),
            ("main_activity.temperature_profile.optimal_temperature",
             act.get("temperature_profile", {}).get("optimal_temperature")),
            ("main_activity.kinetics.Km", kin.get("Km")),
            ("main_activity.kinetics.Vmax", kin.get("Vmax")),
            ("main_activity.kinetics.kcat", kin.get("kcat")),
            ("main_activity.mechanism", act.get("mechanism")),
        ]
        for fname, fval in _TRACK_FIELDS:
            field_fill_rates[fname]["total"] += 1
            if fval is not None and fval != [] and fval != "":
                field_fill_rates[fname]["filled"] += 1

    def _stats(values):
        if not values:
            return {"count": 0}
        import statistics
        return {
            "count": len(values),
            "mean": round(statistics.mean(values), 4),
            "median": round(statistics.median(values), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "stdev": round(statistics.stdev(values), 4) if len(values) > 1 else 0,
        }

    fill_rates = {}
    for fname, counts in sorted(field_fill_rates.items()):
        rate = counts["filled"] / counts["total"] if counts["total"] > 0 else 0
        fill_rates[fname] = round(rate, 4)

    return {
        "total": total,
        "status_distribution": dict(status_counts),
        "enzyme_type_distribution": dict(enzyme_type_counts),
        "application_type_distribution": dict(app_type_counts),
        "field_fill_rates": fill_rates,
        "kinetics_fill_rate": round(has_kinetics / total, 4) if total > 0 else 0,
        "applications_fill_rate": round(has_applications / total, 4) if total > 0 else 0,
        "mechanism_fill_rate": round(has_mechanism / total, 4) if total > 0 else 0,
        "km_stats": _stats(km_values),
        "vmax_stats": _stats(vmax_values),
        "size_stats": _stats(size_values),
        "detection_limit_stats": _stats(detection_limits),
        "top_warnings": dict(warnings_counts.most_common(10)),
    }


def generate_report(stats: Dict[str, Any], output_path: str = None) -> str:
    lines = []
    lines.append("# Nanozyme Extraction Batch Statistics Report")
    lines.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"\n## Overview")
    lines.append(f"- Total papers: {stats.get('total', 0)}")

    for status, count in stats.get("status_distribution", {}).items():
        lines.append(f"  - {status}: {count}")

    lines.append(f"\n## Fill Rates")
    lines.append(f"- Has kinetics: {stats.get('kinetics_fill_rate', 0):.1%}")
    lines.append(f"- Has applications: {stats.get('applications_fill_rate', 0):.1%}")
    lines.append(f"- Has mechanism: {stats.get('mechanism_fill_rate', 0):.1%}")

    lines.append(f"\n### Per-Field Fill Rates")
    lines.append("| Field | Fill Rate |")
    lines.append("|-------|-----------|")
    for fname, rate in stats.get("field_fill_rates", {}).items():
        lines.append(f"| {fname} | {rate:.1%} |")

    lines.append(f"\n## Enzyme Type Distribution")
    for etype, count in stats.get("enzyme_type_distribution", {}).items():
        lines.append(f"- {etype}: {count}")

    lines.append(f"\n## Application Type Distribution")
    for atype, count in stats.get("application_type_distribution", {}).items():
        lines.append(f"- {atype}: {count}")

    for stat_name, label in [("km_stats", "Km"), ("vmax_stats", "Vmax"),
                              ("size_stats", "Size"), ("detection_limit_stats", "Detection Limit")]:
        s = stats.get(stat_name, {})
        if s.get("count", 0) > 0:
            lines.append(f"\n## {label} Statistics")
            lines.append(f"- Count: {s['count']}")
            lines.append(f"- Mean: {s.get('mean', 'N/A')}")
            lines.append(f"- Median: {s.get('median', 'N/A')}")
            lines.append(f"- Range: {s.get('min', 'N/A')} - {s.get('max', 'N/A')}")

    top_warnings = stats.get("top_warnings", {})
    if top_warnings:
        lines.append(f"\n## Top Warnings")
        for w, count in top_warnings.items():
            lines.append(f"- {w}: {count}")

    report = "\n".join(lines)
    if output_path:
        Path(output_path).write_text(report, encoding="utf-8")
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("Usage: python batch_report.py <results_dir> [output.md] [output.json]")
        sys.exit(1)
    rdir = sys.argv[1]
    omd = sys.argv[2] if len(sys.argv) > 2 else None
    ojson = sys.argv[3] if len(sys.argv) > 3 else None
    results = load_results(rdir)
    stats = compute_statistics(results)
    if ojson:
        Path(ojson).write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    report = generate_report(stats, omd)
    print(report)
