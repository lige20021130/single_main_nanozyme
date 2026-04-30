import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)


def setup_cli_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def find_mid_tasks(directory: Path) -> List[Path]:
    mid_tasks = []
    for p in directory.rglob("*_mid_task.json"):
        mid_tasks.append(p)
    for p in directory.rglob("mid_task.json"):
        mid_tasks.append(p)
    return sorted(set(mid_tasks))


def preprocess_pdf(pdf_path: Path, output_dir: Path, extraction_mode: str) -> Optional[Path]:
    try:
        from nanozyme_preprocessor_midjson import NanozymePreprocessor
    except ImportError:
        logger.error("NanozymePreprocessor 不可用，无法预处理 PDF")
        return None

    json_path = output_dir / f"{pdf_path.stem}.json"
    images_root = output_dir / f"{pdf_path.stem}_images"

    pre = NanozymePreprocessor(
        json_path=str(json_path),
        images_root=str(images_root) if images_root.exists() else None,
        output_root=str(output_dir),
        extraction_mode=extraction_mode,
    )
    pre.process()
    mid = pre.to_mid_json(str(output_dir / f"{pdf_path.stem}_mid_task.json"))

    mid_path = output_dir / f"{pdf_path.stem}_mid_task.json"
    if mid_path.exists():
        return mid_path
    return None


async def run_single(mid_task_path: Path, output_dir: Path, smn_config: dict, use_cache: bool = True):
    from extraction_pipeline import ExtractionPipeline

    pipeline = ExtractionPipeline(
        output_dir=str(output_dir),
        enable_cache=use_cache,
    )

    result = await pipeline.process_mid_json_single_main_nanozyme(
        str(mid_task_path),
        use_cache=use_cache,
        smn_config=smn_config,
    )
    return result


def main():
    parser = argparse.ArgumentParser(
        description="纳米酶文献提取 - single_main_nanozyme 模式",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 从已有 mid_task.json 提取
  python run_extraction.py --mode single_main_nanozyme --mid-task paper_mid_task.json --output results

  # 从 PDF 直接提取（需要预处理器）
  python run_extraction.py --mode single_main_nanozyme --input paper.pdf --output results

  # 批量提取
  python run_extraction.py --mode single_main_nanozyme --input-dir ./pdfs --output results

  # 仅规则模式（不调用 LLM/VLM）
  python run_extraction.py --mode single_main_nanozyme --mid-task paper_mid_task.json --output results --no-llm --no-vlm

  # 禁用缓存
  python run_extraction.py --mode single_main_nanozyme --mid-task paper_mid_task.json --output results --no-cache
        """,
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input", type=str, help="输入 PDF 文件路径")
    input_group.add_argument("--mid-task", type=str, help="输入已存在的 mid_task.json 路径")
    input_group.add_argument("--input-dir", type=str, help="批量输入目录（PDF 或 mid_task.json）")

    parser.add_argument("--output", type=str, default="./extraction_results", help="输出目录")
    parser.add_argument("--mode", type=str, default="single_main_nanozyme",
                        choices=["single_main_nanozyme", "canonical_multi_system"],
                        help="提取模式")
    parser.add_argument("--no-llm", action="store_true", help="禁用 LLM，仅用规则提取")
    parser.add_argument("--no-vlm", action="store_true", help="禁用 VLM 图像提取")
    parser.add_argument("--no-cache", action="store_true", help="禁用缓存")
    parser.add_argument("--verbose", action="store_true", help="详细日志")
    parser.add_argument("--top-k", type=int, default=5, help="候选材料 top K")
    parser.add_argument("--max-evidence", type=int, default=20, help="每个证据桶最大句子数")

    args = parser.parse_args()
    setup_cli_logging(args.verbose)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    smn_config = {
        "single_main_nanozyme": {
            "enable_llm": not args.no_llm,
            "enable_vlm": not args.no_vlm,
            "material_candidate_top_k": args.top_k,
            "max_evidence_sentences_per_bucket": args.max_evidence,
        }
    }

    if args.mode != "single_main_nanozyme":
        logger.error("此脚本仅支持 single_main_nanozyme 模式")
        sys.exit(1)

    mid_tasks: List[Path] = []

    if args.mid_task:
        mid_path = Path(args.mid_task)
        if not mid_path.exists():
            logger.error(f"文件不存在: {mid_path}")
            sys.exit(1)
        mid_tasks.append(mid_path)

    elif args.input:
        pdf_path = Path(args.input)
        if not pdf_path.exists():
            logger.error(f"文件不存在: {pdf_path}")
            sys.exit(1)

        if pdf_path.suffix.lower() == ".json":
            mid_tasks.append(pdf_path)
        elif pdf_path.suffix.lower() == ".pdf":
            logger.info(f"预处理 PDF: {pdf_path}")
            mid_path = preprocess_pdf(pdf_path, output_dir, "single_main_nanozyme")
            if mid_path:
                mid_tasks.append(mid_path)
            else:
                logger.error(f"PDF 预处理失败: {pdf_path}")
                sys.exit(1)
        else:
            logger.error(f"不支持的文件格式: {pdf_path.suffix}")
            sys.exit(1)

    elif args.input_dir:
        input_dir = Path(args.input_dir)
        if not input_dir.exists():
            logger.error(f"目录不存在: {input_dir}")
            sys.exit(1)

        found_mids = find_mid_tasks(input_dir)
        if found_mids:
            mid_tasks.extend(found_mids)
            logger.info(f"找到 {len(found_mids)} 个 mid_task.json")
        else:
            pdfs = sorted(input_dir.glob("*.pdf"))
            if not pdfs:
                logger.error(f"目录中未找到 PDF 或 mid_task.json: {input_dir}")
                sys.exit(1)
            logger.info(f"找到 {len(pdfs)} 个 PDF，开始预处理...")
            for pdf_path in pdfs:
                logger.info(f"预处理: {pdf_path.name}")
                mid_path = preprocess_pdf(pdf_path, output_dir, "single_main_nanozyme")
                if mid_path:
                    mid_tasks.append(mid_path)
                else:
                    logger.warning(f"预处理失败，跳过: {pdf_path.name}")

    if not mid_tasks:
        logger.error("没有可处理的文件")
        sys.exit(1)

    logger.info(f"共 {len(mid_tasks)} 个文件待处理")

    success_count = 0
    fail_count = 0

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        for i, mid_path in enumerate(mid_tasks, 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"处理 [{i}/{len(mid_tasks)}]: {mid_path.name}")
            logger.info(f"{'='*60}")

            try:
                result = loop.run_until_complete(run_single(
                    mid_path, output_dir, smn_config,
                    use_cache=not args.no_cache,
                ))
                diag = result.get("diagnostics", {})
                logger.info(
                    f"完成: status={diag.get('status')}, "
                    f"confidence={diag.get('confidence')}, "
                    f"nanozyme={result.get('selected_nanozyme', {}).get('name')}, "
                    f"activity={result.get('main_activity', {}).get('enzyme_like_type')}"
                )
                success_count += 1
            except Exception as e:
                logger.error(f"处理失败: {mid_path.name}: {e}")
                fail_count += 1

            if i < len(mid_tasks):
                import time as _time
                _time.sleep(1)
    finally:
        loop.close()

    logger.info(f"\n{'='*60}")
    logger.info(f"全部完成: 成功 {success_count}, 失败 {fail_count}, 共 {len(mid_tasks)}")
    logger.info(f"输出目录: {output_dir}")
    logger.info(f"{'='*60}")

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
