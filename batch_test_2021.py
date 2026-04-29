import sys
import json
import re
import logging
import asyncio
import argparse
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PDF_DIR = Path(r"C:\Users\lcl\Desktop\wenxian-2021.6.1\-2021.6.1-")
OUTPUT_DIR = Path(r"d:\ocrwiki版本\single_main_nanozyme\test_output_2021")

PARSED_DIR = OUTPUT_DIR / "parsed"
PREPROC_DIR = OUTPUT_DIR / "preprocessed"
EXTRACT_DIR = OUTPUT_DIR / "extracted"

args = argparse.Namespace(llm=False, vlm=False, force=False, limit=10)


def get_test_pdfs(limit=10):
    all_pdfs = sorted(PDF_DIR.glob("*.pdf"))
    main_pdfs = [f for f in all_pdfs if "SI" not in f.stem and "范例" not in f.stem and "DFT" not in f.stem]
    return main_pdfs[:limit]


def safe_stem(pdf_path: Path) -> str:
    stem = pdf_path.stem
    import hashlib
    if len(stem) > 40:
        h = hashlib.md5(stem.encode()).hexdigest()[:8]
        year_match = re.match(r'(\d{4})', stem)
        prefix = year_match.group(1) if year_match else stem[:10]
        stem = f"{prefix}_{h}"
    stem = re.sub(r'[^\w\-]', '_', stem)
    return stem


def step1_parse(pdf_path: Path) -> Path:
    stem = safe_stem(pdf_path)
    out_subdir = PARSED_DIR / stem
    out_subdir.mkdir(parents=True, exist_ok=True)
    out_json = out_subdir / f"{stem}.json"

    if out_json.exists() and not args.force:
        logger.info(f"[SKIP] Already parsed: {stem}")
        return out_json

    logger.info(f"[PARSE] {stem}")
    try:
        import opendataloader_pdf
        opendataloader_pdf.convert(
            input_path=str(pdf_path),
            output_dir=str(out_subdir),
            format="json",
            use_struct_tree=True,
            reading_order="xycut",
            hybrid="docling-fast",
            hybrid_mode="auto",
            hybrid_url="http://localhost:5002",
            hybrid_timeout="120000",
            hybrid_fallback=True,
        )
    except UnicodeDecodeError:
        logger.warning(f"[PARSE] UnicodeDecodeError for {stem}, checking output...")
    except Exception as e:
        logger.error(f"[PARSE] Error for {stem}: {e}")
        return None

    if out_json.exists():
        logger.info(f"[PARSE] Success: {stem}")
        return out_json

    for jf in out_subdir.glob("*.json"):
        if jf.exists():
            logger.info(f"[PARSE] Found alternative output: {jf.name}")
            return jf

    logger.error(f"[PARSE] No output for {stem}")
    return None


def step2_preprocess(parsed_path: Path, pdf_path: Path) -> Path:
    stem = safe_stem(pdf_path)
    out_path = PREPROC_DIR / f"{stem}_mid_task.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists() and not args.force:
        logger.info(f"[SKIP] Already preprocessed: {stem}")
        return out_path

    logger.info(f"[PREPROC] {stem}")
    try:
        import shutil, tempfile
        tmp_dir = Path(tempfile.mkdtemp(prefix="smn_"))
        tmp_json = tmp_dir / f"{stem}.json"
        shutil.copy2(str(parsed_path), str(tmp_json))

        from nanozyme_preprocessor_midjson import NanozymePreprocessor
        preprocessor = NanozymePreprocessor(
            json_path=str(tmp_json),
            output_root=str(tmp_dir),
            images_root=str(parsed_path.parent),
            extraction_mode="single_main_nanozyme",
        )
        preprocessor.process()
        mid_task = preprocessor.to_mid_json()

        img_output_dir = PREPROC_DIR / f"{stem}_images"
        for task in mid_task.get("vlm_tasks", []):
            old_path = task.get("image_path", "")
            if old_path and Path(old_path).exists():
                img_output_dir.mkdir(parents=True, exist_ok=True)
                new_name = Path(old_path).name
                new_path = img_output_dir / new_name
                shutil.copy2(old_path, str(new_path))
                task["image_path"] = str(new_path.resolve())

        shutil.rmtree(tmp_dir, ignore_errors=True)

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(mid_task, f, ensure_ascii=False, indent=2)

        logger.info(f"[PREPROC] Success: {stem}")
        return out_path
    except Exception as e:
        logger.error(f"[PREPROC] Error for {stem}: {e}")
        return None


async def step3_extract(mid_path: Path, pdf_path: Path, client=None) -> Path:
    from single_main_nanozyme_extractor import SingleMainNanozymePipeline, SMNConfig, validate_schema
    stem = safe_stem(pdf_path)
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)

    out_path = EXTRACT_DIR / f"{stem}_extracted.json"
    if out_path.exists() and not args.force:
        logger.info(f"[SKIP] Already extracted: {stem}")
        return out_path

    logger.info(f"[EXTRACT] {stem}")
    try:
        with open(mid_path, "r", encoding="utf-8") as f:
            mid = json.load(f)

        config = SMNConfig(enable_llm=args.llm, enable_vlm=args.vlm)
        pipeline = SingleMainNanozymePipeline(client=client, config=config)
        record = await pipeline.extract(mid)
        record = validate_schema(record)

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        logger.info(f"[EXTRACT] Success: {stem}")
        return out_path
    except Exception as e:
        logger.error(f"[EXTRACT] Error for {stem}: {e}")
        import traceback
        traceback.print_exc()
        return None


def evaluate_result(result_path: Path) -> dict:
    if not result_path or not result_path.exists():
        return {"status": "NO_RESULT_FILE"}

    with open(result_path, "r", encoding="utf-8") as f:
        r = json.load(f)

    sel = r.get("selected_nanozyme", {})
    act = r.get("main_activity", {})
    kin = act.get("kinetics", {})
    apps = r.get("applications", [])
    app_note = r.get("applications_note", "")
    diag = r.get("diagnostics", {})

    return {
        "file": result_path.stem.replace("_extracted", ""),
        "status": "OK",
        "selected_name": sel.get("name"),
        "selection_score": sel.get("selection_score"),
        "enzyme_type": act.get("enzyme_like_type"),
        "Km": kin.get("Km"),
        "Km_unit": kin.get("Km_unit"),
        "Vmax": kin.get("Vmax"),
        "substrate": kin.get("substrate"),
        "applications_count": len(apps),
        "applications_note": app_note,
        "has_LOD": any(a.get("detection_limit") for a in apps),
        "has_analyte": any(a.get("target_analyte") for a in apps),
        "warnings": diag.get("warnings", []),
    }


async def process_one(pdf_path: Path, client=None):
    parsed = step1_parse(pdf_path)
    if not parsed:
        return {"file": pdf_path.name, "status": "PARSE_FAILED"}

    mid = step2_preprocess(parsed, pdf_path)
    if not mid:
        return {"file": pdf_path.name, "status": "PREPROC_FAILED"}

    result_path = await step3_extract(mid, pdf_path, client=client)
    if not result_path:
        return {"file": pdf_path.name, "status": "EXTRACT_FAILED"}

    return evaluate_result(result_path)


async def main():
    global args
    parser = argparse.ArgumentParser(description="Batch test for 2021 nanozyme literature")
    parser.add_argument("--llm", action="store_true", help="Enable LLM")
    parser.add_argument("--vlm", action="store_true", help="Enable VLM")
    parser.add_argument("--force", action="store_true", help="Force re-process")
    parser.add_argument("--limit", type=int, default=10, help="Number of PDFs to test")
    args = parser.parse_args()

    test_pdfs = get_test_pdfs(args.limit)
    logger.info(f"Found {len(test_pdfs)} PDFs to test (limit={args.limit})")

    server_proc = None
    try:
        import urllib.request
        r = urllib.request.urlopen("http://localhost:5002/health", timeout=3)
        logger.info("PDF server already running on port 5002")
    except Exception:
        logger.info("Starting PDF server on port 5002...")
        import subprocess
        server_proc = subprocess.Popen(
            ["opendataloader-pdf-hybrid", "--port=5002"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        import time
        for _ in range(30):
            time.sleep(1)
            try:
                r = urllib.request.urlopen("http://localhost:5002/health", timeout=3)
                logger.info("PDF server started successfully")
                break
            except Exception:
                continue
        else:
            logger.warning("PDF server failed to start within 30s")

    client = None
    if args.llm or args.vlm:
        try:
            from api_client import APIClient
            client = APIClient()
            await client.__aenter__()
            logger.info("APIClient initialized for LLM/VLM")
        except Exception as e:
            logger.warning(f"APIClient init failed: {e}, falling back to rule-only")
            client = None

    results = []
    try:
        for i, pdf in enumerate(test_pdfs):
            logger.info(f"\n{'='*60}\n[{i+1}/{len(test_pdfs)}] Processing: {pdf.name[:60]}\n{'='*60}")
            result = await process_one(pdf, client=client)
            results.append(result)
    finally:
        if client:
            await client.__aexit__(None, None, None)
        if server_proc:
            server_proc.terminate()
            logger.info("PDF server terminated")

    summary_path = OUTPUT_DIR / "test_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({"timestamp": datetime.now().isoformat(), "results": results}, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    ok = [r for r in results if r.get("status") == "OK"]
    print(f"Total: {len(results)}, OK: {len(ok)}, Failed: {len(results) - len(ok)}")
    for r in ok:
        name = (r.get("file") or "?")[:40]
        sel = r.get("selected_name") or "None"
        etype = r.get("enzyme_type") or "None"
        km = r.get("Km")
        apps = r.get("applications_count", 0)
        print(f"  {name:42s} | {sel:20s} | {etype:20s} | Km={km} | apps={apps}")


if __name__ == "__main__":
    asyncio.run(main())
