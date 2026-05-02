import json
import sys
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import Counter

logger = logging.getLogger(__name__)


def load_results(results_dir: str) -> List[Dict[str, Any]]:
    results = []
    p = Path(results_dir)
    for jf in p.glob("*.json"):
        try:
            with open(jf, "r", encoding="utf-8") as f:
                data = json.load(f)
            results.append(data)
        except Exception as e:
            logger.warning(f"Failed to load {jf}: {e}")
    return results


def plot_enzyme_type_distribution(results: List[Dict], output_dir: str):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib not available, skipping plot")
        return

    counts = Counter()
    for r in results:
        etype = r.get("main_activity", {}).get("enzyme_like_type")
        if etype:
            counts[etype] += 1

    if not counts:
        logger.info("No enzyme type data to plot")
        return

    labels = list(counts.keys())
    values = list(counts.values())

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(labels, values, color="steelblue")
    ax.set_xlabel("Count")
    ax.set_title("Enzyme-like Activity Type Distribution")
    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                str(val), va="center", fontsize=10)
    plt.tight_layout()
    out_path = Path(output_dir) / "enzyme_type_distribution.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    logger.info(f"Saved {out_path}")


def plot_application_type_distribution(results: List[Dict], output_dir: str):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib not available, skipping plot")
        return

    counts = Counter()
    for r in results:
        for app in r.get("applications", []):
            at = app.get("application_type")
            if at:
                counts[at] += 1

    if not counts:
        logger.info("No application type data to plot")
        return

    labels = list(counts.keys())
    values = list(counts.values())

    fig, ax = plt.subplots(figsize=(8, 8))
    wedges, texts, autotexts = ax.pie(values, labels=labels, autopct="%1.1f%%",
                                       startangle=90)
    ax.set_title("Application Type Distribution")
    plt.tight_layout()
    out_path = Path(output_dir) / "application_type_distribution.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    logger.info(f"Saved {out_path}")


def plot_field_fill_rates(results: List[Dict], output_dir: str):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib not available, skipping plot")
        return

    from collections import defaultdict
    field_counts = defaultdict(lambda: {"filled": 0, "total": 0})

    _FIELDS = [
        ("name", lambda r: r.get("selected_nanozyme", {}).get("name")),
        ("composition", lambda r: r.get("selected_nanozyme", {}).get("composition")),
        ("morphology", lambda r: r.get("selected_nanozyme", {}).get("morphology")),
        ("size", lambda r: r.get("selected_nanozyme", {}).get("size")),
        ("enzyme_type", lambda r: r.get("main_activity", {}).get("enzyme_like_type")),
        ("assay_method", lambda r: r.get("main_activity", {}).get("assay_method")),
        ("signal", lambda r: r.get("main_activity", {}).get("signal")),
        ("buffer", lambda r: r.get("main_activity", {}).get("conditions", {}).get("buffer")),
        ("pH", lambda r: r.get("main_activity", {}).get("conditions", {}).get("pH")),
        ("temperature", lambda r: r.get("main_activity", {}).get("conditions", {}).get("temperature")),
        ("optimal_pH", lambda r: r.get("main_activity", {}).get("pH_profile", {}).get("optimal_pH")),
        ("optimal_temp", lambda r: r.get("main_activity", {}).get("temperature_profile", {}).get("optimal_temperature")),
        ("Km", lambda r: r.get("main_activity", {}).get("kinetics", {}).get("Km")),
        ("Vmax", lambda r: r.get("main_activity", {}).get("kinetics", {}).get("Vmax")),
        ("kcat", lambda r: r.get("main_activity", {}).get("kinetics", {}).get("kcat")),
        ("mechanism", lambda r: r.get("main_activity", {}).get("mechanism")),
    ]

    for r in results:
        for fname, accessor in _FIELDS:
            val = accessor(r)
            field_counts[fname]["total"] += 1
            if val is not None and val != "" and val != []:
                field_counts[fname]["filled"] += 1

    labels = []
    rates = []
    for fname in [f[0] for f in _FIELDS]:
        c = field_counts[fname]
        rate = c["filled"] / c["total"] if c["total"] > 0 else 0
        labels.append(fname)
        rates.append(rate)

    fig, ax = plt.subplots(figsize=(12, 6))
    colors = ["#2ecc71" if r >= 0.7 else "#f39c12" if r >= 0.4 else "#e74c3c" for r in rates]
    bars = ax.bar(range(len(labels)), rates, color=colors)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylabel("Fill Rate")
    ax.set_title("Field Fill Rate Across Extracted Records")
    ax.set_ylim(0, 1.1)
    for bar, rate in zip(bars, rates):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                f"{rate:.0%}", ha="center", va="bottom", fontsize=8)
    plt.tight_layout()
    out_path = Path(output_dir) / "field_fill_rates.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    logger.info(f"Saved {out_path}")


def plot_km_vmax_scatter(results: List[Dict], output_dir: str):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib not available, skipping plot")
        return

    km_vals = []
    vmax_vals = []
    labels = []
    for r in results:
        kin = r.get("main_activity", {}).get("kinetics", {})
        km = kin.get("Km")
        vmax = kin.get("Vmax")
        if km is not None and vmax is not None:
            try:
                km_vals.append(float(km))
                vmax_vals.append(float(vmax))
                labels.append(r.get("selected_nanozyme", {}).get("name", "")[:20])
            except (ValueError, TypeError):
                pass

    if not km_vals:
        logger.info("No Km/Vmax data to plot")
        return

    fig, ax = plt.subplots(figsize=(10, 7))
    ax.scatter(km_vals, vmax_vals, alpha=0.7, s=60, edgecolors="black", linewidth=0.5)
    for i, label in enumerate(labels):
        if i < 20:
            ax.annotate(label, (km_vals[i], vmax_vals[i]),
                        textcoords="offset points", xytext=(5, 5), fontsize=7)
    ax.set_xlabel("Km")
    ax.set_ylabel("Vmax")
    ax.set_title("Km vs Vmax Scatter Plot")
    plt.tight_layout()
    out_path = Path(output_dir) / "km_vmax_scatter.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    logger.info(f"Saved {out_path}")


def generate_all_plots(results_dir: str, output_dir: str):
    results = load_results(results_dir)
    if not results:
        logger.warning(f"No results found in {results_dir}")
        return
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    plot_enzyme_type_distribution(results, output_dir)
    plot_application_type_distribution(results, output_dir)
    plot_field_fill_rates(results, output_dir)
    plot_km_vmax_scatter(results, output_dir)
    logger.info(f"All plots saved to {output_dir}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("Usage: python generate_plots.py <results_dir> [output_dir]")
        sys.exit(1)
    rdir = sys.argv[1]
    odir = sys.argv[2] if len(sys.argv) > 2 else str(Path(rdir) / "plots")
    generate_all_plots(rdir, odir)
