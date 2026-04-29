import sys
import json
import logging
import asyncio
import subprocess
import argparse
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("full_test")

PDF_DIR = Path(r"C:\Users\lcl\Desktop\wenxian-AM\wenxian-AM")
OUTPUT_DIR = Path(r"d:\ocrwiki版本\single_main_nanozyme\test_output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PDF_FILES = sorted(PDF_DIR.glob("*.pdf"))
MAIN_PDFS = [f for f in PDF_FILES if "SI" not in f.stem]

args = argparse.Namespace(llm=False, vlm=False, force=False)


def step1_parse_pdf(pdf_path: Path) -> Path:
    stem = pdf_path.stem
    pdf_output = OUTPUT_DIR / "parsed" / stem
    pdf_output.mkdir(parents=True, exist_ok=True)

    json_path = pdf_output / f"{stem}.json"
    if json_path.exists():
        logger.info(f"[SKIP] Already parsed: {stem}")
        return json_path

    logger.info(f"[PARSE] {pdf_path.name}")
    try:
        import opendataloader_pdf
        opendataloader_pdf.convert(
            input_path=[str(pdf_path)],
            format="json",
            use_struct_tree=True,
            reading_order="xycut",
            image_output="external",
            image_format="png",
            output_dir=str(pdf_output),
        )
    except UnicodeDecodeError:
        logger.warning(f"[PARSE] UnicodeDecodeError (known bug), checking if output was created...")
    except Exception as e:
        logger.warning(f"[PARSE] Error (checking output anyway): {e}")

    if json_path.exists():
        logger.info(f"[PARSE] Success: {json_path}")
        return json_path
    else:
        logger.error(f"[PARSE] No JSON output for {stem}")
        return None


def step2_preprocess(json_path: Path) -> Path:
    from nanozyme_preprocessor_midjson import NanozymePreprocessor
    stem = json_path.stem
    pre_output = OUTPUT_DIR / "preprocessed"
    pre_output.mkdir(parents=True, exist_ok=True)

    mid_path = pre_output / f"{stem}_mid_task.json"
    if mid_path.exists():
        logger.info(f"[SKIP] Already preprocessed: {stem}")
        return mid_path

    images_dir = json_path.parent / f"{stem}_images"
    logger.info(f"[PREPROCESS] {stem}")
    try:
        pre = NanozymePreprocessor(
            json_path=str(json_path),
            images_root=str(images_dir) if images_dir.exists() else None,
            output_root=str(pre_output),
            rulebook_path="rulebook.json",
            runtime_overrides={
                "adaptive_chunking": {"enabled": False},
                "image_filter": {"require_caption_for_small": True},
            },
            pdf_stem=stem,
            extraction_mode="single_main_nanozyme",
        )
        pre.process()
        pre.to_mid_json(str(mid_path))
        if mid_path.exists():
            logger.info(f"[PREPROCESS] Success: {mid_path}")
            return mid_path
        else:
            logger.error(f"[PREPROCESS] No mid_task output for {stem}")
            return None
    except Exception as e:
        logger.error(f"[PREPROCESS] Failed: {e}")
        import traceback
        traceback.print_exc()
        return None


async def step3_extract(mid_path: Path, enable_llm: bool = False, enable_vlm: bool = False) -> Path:
    from single_main_nanozyme_extractor import SingleMainNanozymePipeline, SMNConfig, validate_schema
    stem = mid_path.stem.replace("_mid_task", "")
    ext_output = OUTPUT_DIR / "extracted"
    ext_output.mkdir(parents=True, exist_ok=True)

    out_path = ext_output / f"{stem}_extracted.json"
    if out_path.exists():
        logger.info(f"[SKIP] Already extracted: {stem}")
        return out_path

    logger.info(f"[EXTRACT] {stem} (llm={enable_llm}, vlm={enable_vlm})")
    try:
        with open(mid_path, "r", encoding="utf-8") as f:
            mid = json.load(f)

        client = None
        if enable_llm or enable_vlm:
            try:
                from api_client import APIClient
                client_ctx = APIClient()
                client = await client_ctx.__aenter__()
                logger.info("[EXTRACT] APIClient initialized for LLM/VLM")
            except Exception as e:
                logger.warning(f"[EXTRACT] APIClient init failed: {e}, falling back to rule-only")
                client = None

        config = SMNConfig(enable_llm=enable_llm, enable_vlm=enable_vlm)
        pipeline = SingleMainNanozymePipeline(client=client, config=config)
        record = await pipeline.extract(mid)
        record = validate_schema(record)

        record["extraction_mode"] = "single_main_nanozyme"
        record["metadata"] = {
            "source_file": str(mid_path),
            "extraction_mode": "single_main_nanozyme",
            "processed_at": datetime.now().isoformat(),
            "schema_version": "single_main_nanozyme.v1",
        }

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False, default=str)

        logger.info(f"[EXTRACT] Success: {out_path}")
        return out_path
    except Exception as e:
        logger.error(f"[EXTRACT] Failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def evaluate_result(result_path: Path) -> dict:
    if result_path is None or not Path(result_path).exists():
        return {"file": "N/A", "status": "FAILED", "error": "no output file"}

    with open(result_path, "r", encoding="utf-8") as f:
        record = json.load(f)

    paper = record.get("paper", {})
    nano = record.get("selected_nanozyme", {})
    activity = record.get("main_activity", {})
    kinetics = activity.get("kinetics", {})
    apps = record.get("applications", [])
    diag = record.get("diagnostics", {})

    return {
        "file": Path(result_path).name,
        "title": (paper.get("title") or "")[:80],
        "selected_name": nano.get("name"),
        "selection_reason": nano.get("selection_reason"),
        "enzyme_type": activity.get("enzyme_like_type"),
        "substrates": activity.get("substrates"),
        "Km": kinetics.get("Km"),
        "Km_unit": kinetics.get("Km_unit"),
        "Vmax": kinetics.get("Vmax"),
        "kinetics_source": kinetics.get("source"),
        "applications_count": len(apps),
        "diagnostics_status": diag.get("status"),
        "diagnostics_confidence": diag.get("confidence"),
        "warnings": diag.get("warnings"),
    }


async def process_one(pdf_path: Path):
    stem = pdf_path.stem
    print(f"\n{'='*70}")
    print(f"Processing: {pdf_path.name}")
    print(f"{'='*70}")

    json_path = step1_parse_pdf(pdf_path)
    if not json_path:
        return {"file": pdf_path.name, "status": "PARSE_FAILED"}

    mid_path = step2_preprocess(json_path)
    if not mid_path:
        return {"file": pdf_path.name, "status": "PREPROCESS_FAILED"}

    result_path = await step3_extract(mid_path, enable_llm=args.llm, enable_vlm=args.vlm)
    if not result_path:
        return {"file": pdf_path.name, "status": "EXTRACT_FAILED"}

    return evaluate_result(result_path)


async def main():
    parser = argparse.ArgumentParser(description="Full pipeline test for single_main_nanozyme")
    parser.add_argument("--llm", action="store_true", help="Enable LLM extraction")
    parser.add_argument("--vlm", action="store_true", help="Enable VLM extraction")
    parser.add_argument("--force", action="store_true", help="Force re-extraction (delete existing results)")
    global args
    args = parser.parse_args()

    if args.force:
        ext_dir = OUTPUT_DIR / "extracted"
        for f in ext_dir.glob("*.json"):
            f.unlink()
            logger.info(f"[FORCE] Deleted: {f.name}")

    results = []
    for pdf in MAIN_PDFS:
        result = await process_one(pdf)
        results.append(result)

    print(f"\n\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    for r in results:
        print(f"\n--- {r.get('file', 'N/A')} ---")
        for k, v in r.items():
            if k != "file":
                print(f"  {k}: {v}")

    summary_path = OUTPUT_DIR / "test_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nSummary saved to: {summary_path}")


if __name__ == "__main__":
    asyncio.run(main())
