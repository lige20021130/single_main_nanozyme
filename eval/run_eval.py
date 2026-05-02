import json
import sys
import logging
import argparse
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


def run_extraction(pdf_dir: str, output_dir: str, config_path: str = None) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    try:
        from single_main_nanozyme_extractor import SingleMainNanozymePipeline, SMNConfig
    except ImportError:
        logger.error("Cannot import SingleMainNanozymePipeline. Make sure the project root is in PYTHONPATH.")
        sys.exit(1)

    pdf_files = list(Path(pdf_dir).glob("*.pdf"))
    if not pdf_files:
        logger.warning(f"No PDF files found in {pdf_dir}")
        return output_path

    logger.info(f"Found {len(pdf_files)} PDF files to process")
    config = SMNConfig()
    if config_path:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg_data = json.load(f)
            for k, v in cfg_data.items():
                if hasattr(config, k):
                    setattr(config, k, v)
        except Exception as e:
            logger.warning(f"Failed to load config: {e}")

    pipeline = SingleMainNanozymePipeline(config)
    success_count = 0
    fail_count = 0

    for i, pdf_path in enumerate(pdf_files, 1):
        logger.info(f"[{i}/{len(pdf_files)}] Processing {pdf_path.name}")
        try:
            result = pipeline.extract(str(pdf_path))
            out_file = output_path / f"{pdf_path.stem}.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            success_count += 1
        except Exception as e:
            logger.error(f"Failed to process {pdf_path.name}: {e}")
            fail_count += 1

    logger.info(f"Extraction complete: {success_count} success, {fail_count} failed")
    return output_path


def run_evaluation(extracted_dir: str, gold_dir: str, report_dir: str = None) -> dict:
    from evaluate import evaluate_batch
    report_path = Path(report_dir) if report_dir else Path(extracted_dir) / "eval_report"
    report_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_json = str(report_path / f"eval_results_{timestamp}.json")
    output_md = str(report_path / f"eval_report_{timestamp}.md")
    stats = evaluate_batch(extracted_dir, gold_dir, output_json, output_md)
    logger.info(f"Evaluation report saved to {report_path}")
    return stats


def main():
    parser = argparse.ArgumentParser(description="Batch extraction + evaluation pipeline")
    parser.add_argument("pdf_dir", help="Directory containing PDF files")
    parser.add_argument("gold_dir", help="Directory containing gold standard JSON files")
    parser.add_argument("--output-dir", default=None, help="Output directory for extraction results")
    parser.add_argument("--report-dir", default=None, help="Output directory for evaluation reports")
    parser.add_argument("--config", default=None, help="Path to config JSON")
    parser.add_argument("--skip-extraction", action="store_true", help="Skip extraction, only evaluate")
    parser.add_argument("--skip-evaluation", action="store_true", help="Skip evaluation, only extract")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    pdf_dir = Path(args.pdf_dir)
    gold_dir = Path(args.gold_dir)
    output_dir = args.output_dir or str(pdf_dir.parent / "extraction_output")
    report_dir = args.report_dir or str(Path(output_dir) / "eval_report")

    if not args.skip_extraction:
        logger.info("=== Step 1: Batch Extraction ===")
        run_extraction(args.pdf_dir, output_dir, args.config)
    else:
        logger.info("=== Skipping extraction ===")

    if not args.skip_evaluation:
        logger.info("=== Step 2: Evaluation ===")
        stats = run_evaluation(output_dir, args.gold_dir, report_dir)
        print("\n=== Evaluation Summary ===")
        print(f"Total papers: {stats.get('total_papers', 0)}")
        print(f"Global accuracy: {stats.get('global_accuracy', 0):.2%}")
        print(f"Average MAE: {stats.get('avg_mae', 0):.6f}")
        print(f"Magnitude accuracy: {stats.get('avg_magnitude_accuracy', 0):.2%}")
    else:
        logger.info("=== Skipping evaluation ===")

    logger.info("Pipeline complete!")


if __name__ == "__main__":
    main()
