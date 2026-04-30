# extraction_pipeline.py - 增强版：集成新模块、统一日志
"""
纳米酶文献提取系统 - 提取管道

增强功能：
1. 集成配置管理模块
2. 集成缓存管理
3. 集成任务队列
4. 统一日志系统
5. 更好的错误处理和进度报告
"""

import asyncio
import hashlib
import json
import sys
import logging
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List
from datetime import datetime

# 尝试导入新模块
try:
    from config_manager import ConfigManager, get_config
    from cache_manager import CacheManager, get_cache_manager
    from task_queue import TaskQueue, TaskStatus, get_task_queue
    from logging_setup import setup_logging, get_logger
    CONFIG_MANAGER_AVAILABLE = True
except ImportError as e:
    CONFIG_MANAGER_AVAILABLE = False
    get_logger = lambda x: logging.getLogger(x)

# 导入原有模块
try:
    import yaml
    from api_client import APIClient
    from llm_extractor import LLMExtractor, TableExtractor
    from vlm_extractor import VLMExtractor
    from result_integrator import ResultIntegrator, get_field_defs
    from rule_learner import RuleLearner
    MODULES_AVAILABLE = True
except ImportError as e:
    MODULES_AVAILABLE = False

try:
    from single_main_nanozyme_extractor import (
        SingleMainNanozymePipeline,
        SMNConfig,
        validate_schema,
        EXTRACTION_MODE as SMN_MODE,
        SCHEMA_VERSION as SMN_SCHEMA_VERSION,
    )
    SMN_AVAILABLE = True
except ImportError:
    SMN_AVAILABLE = False

logger = logging.getLogger(__name__)


class ExtractionPipeline:
    """
    增强版提取管道
    
    支持：
    - 配置管理
    - 结果缓存
    - 任务队列
    - 进度回调
    - 错误恢复
    """
    
    def __init__(
        self,
        config_path: str = "config.yaml",
        output_dir: Optional[str] = None,
        enable_cache: bool = True,
        enable_queue: bool = False,
        use_new_modules: bool = True
    ):
        """
        初始化提取管道
        
        Args:
            config_path: 配置文件路径
            output_dir: 输出目录
            enable_cache: 是否启用缓存
            enable_queue: 是否启用任务队列
            use_new_modules: 是否使用新模块（配置管理、缓存等）
        """
        self._setup_logging()
        
        # 加载配置
        if use_new_modules and CONFIG_MANAGER_AVAILABLE:
            self.config = ConfigManager.get_instance(config_path)
            self.config_manager = self.config
            self.output_dir = Path(output_dir) if output_dir else self.config.pipeline.results_dir
            self.enable_cache = enable_cache and self.config.pipeline.enable_cache
            self.confidence_threshold = self.config.pipeline.confidence_threshold
            self.rulebook_path = self.config.pipeline.rulebook_path
            
            # 初始化缓存管理器
            if self.enable_cache:
                self.cache_manager = get_cache_manager(
                    str(self.config.pipeline.cache_dir),
                    max_age_days=7
                )
            else:
                self.cache_manager = None
            
            # 初始化任务队列
            if enable_queue and self.config.queue.enabled:
                self.task_queue = TaskQueue(
                    queue_file=str(self.config.pipeline.task_queue_path),
                    max_retry=self.config.queue.max_retries,
                    task_timeout=self.config.queue.task_timeout,
                    cleanup_interval=self.config.queue.cleanup_interval,
                )
            else:
                self.task_queue = None
                
        else:
            # 使用原有配置加载方式
            self._load_legacy_config(config_path)
            self.enable_cache = False
            self.cache_manager = None
            self.task_queue = None
            self.config_manager = None
        
        # 创建输出目录
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化组件
        if MODULES_AVAILABLE:
            self.integrator = ResultIntegrator(self.confidence_threshold)
            self.rule_learner = RuleLearner(str(self.rulebook_path))
        else:
            self.integrator = None
            self.rule_learner = None
        
        logger.info(f"提取管道初始化完成: output_dir={self.output_dir}")
        if self.enable_cache:
            logger.info("缓存功能已启用")
        if self.task_queue:
            logger.info("任务队列已启用")
    
    def _setup_logging(self):
        """设置日志"""
        if not logging.getLogger().handlers:
            if CONFIG_MANAGER_AVAILABLE:
                setup_logging(level=logging.INFO, detailed=False)
            else:
                logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    def _load_legacy_config(self, config_path: str):
        """加载原有格式的配置（向后兼容）"""
        with open(config_path, 'r', encoding='utf-8') as f:
            self._raw_config = yaml.safe_load(f)
        
        self.output_dir = Path(self._raw_config.get('results_dir', './extraction_results'))
        self.confidence_threshold = self._raw_config.get('confidence_threshold', 0.7)
        self.rulebook_path = Path(self._raw_config.get('rulebook_path', './rulebook.json'))
    
    async def process_mid_json(
        self,
        mid_json_path: str,
        progress_callback: Optional[Callable[[str, Optional[int]], None]] = None,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        处理中间任务JSON
        
        Args:
            mid_json_path: 中间任务JSON路径
            progress_callback: 进度回调 (message, percent)
            use_cache: 是否使用缓存
            
        Returns:
            提取结果
        """
        mid_json_path = Path(mid_json_path)
        
        try:
            if progress_callback:
                progress_callback("读取 mid_task.json...", 5)
            logger.info("=" * 60)
            logger.info("开始执行大模型提取流程")
            logger.info("=" * 60)
            
            # 加载中间任务
            with open(mid_json_path, 'r', encoding='utf-8') as f:
                mid = json.load(f)

            chunks = mid['llm_task']['chunks']
            prompt_template = mid['llm_task']['prompt_template']
            vlm_tasks = mid.get('vlm_tasks', [])
            metadata = mid.get('metadata', {})
            chunk_contexts = mid['llm_task'].get('chunk_contexts', [])
            extracted_hints = mid.get('extracted_hints', {})
            sentence_metadata = mid.get('sentence_metadata', {})
            # 新增：读取 table_extraction_task（向后兼容，无该字段时为空）
            table_extraction_task = mid.get('table_extraction_task') or None

            logger.info(f"[DIAG] mid loaded: extraction_mode={metadata.get('extraction_mode', 'unknown')}, "
                         f"chunking_mode={mid.get('chunking_mode', 'unknown')}, "
                         f"chunks={len(chunks)}, vlm_tasks={len(vlm_tasks)}, "
                         f"prompt_preview={prompt_template[:200] if prompt_template else '(empty)'}")

            single_chunk_forced = self.config_manager.get("preprocessor_config.preserve_single_chunk_default", False) if self.config_manager else False
            if single_chunk_forced and len(chunks) > 1:
                logger.warning(f"[DIAG] 单块模式被激活但 chunk 数={len(chunks)}，预期为1")

            for i, chunk in enumerate(chunks):
                ctx = chunk_contexts[i] if i < len(chunk_contexts) else {}
                hint_parts: List[str] = []
                mentions = ctx.get('candidate_system_mentions', [])
                if mentions:
                    unique_mentions = list(dict.fromkeys(mentions))[:5]
                    hint_parts.append(f"likely systems: {', '.join(unique_mentions)}")
                enzyme_mentions = ctx.get('candidate_enzyme_mentions', [])
                if enzyme_mentions:
                    hint_parts.append(f"likely enzyme types: {', '.join(enzyme_mentions[:4])}")
                substrate_mentions = ctx.get('candidate_substrate_mentions', [])
                if substrate_mentions:
                    hint_parts.append(f"likely substrates: {', '.join(substrate_mentions[:4])}")
                app_mentions = ctx.get('candidate_application_mentions', [])
                if app_mentions:
                    hint_parts.append(f"likely applications: {', '.join(app_mentions[:3])}")
                if ctx.get('contains_kinetics_signal'):
                    hint_parts.append("kinetics-like values appear")
                if ctx.get('is_caption'):
                    hint_parts.append("from caption")
                if ctx.get('is_supplementary'):
                    hint_parts.append("from supplementary")
                if hint_parts:
                    chunks[i] = f"[Hint: {'; '.join(hint_parts)}]\n\n{chunk}"

            config_hash = self._build_cache_hash(prompt_template, chunks)

            # 检查缓存
            if use_cache and self.enable_cache and self.cache_manager:
                try:
                    cached = self.cache_manager.get(
                        str(mid_json_path),
                        config_hash,
                        check_file_change=True
                    )
                    if cached:
                        logger.info("使用缓存结果")
                        out_path = self._save_result(mid_json_path, cached)
                        logger.info(f"缓存结果已保存至: {out_path}")
                        if progress_callback:
                            progress_callback("使用缓存结果", 100)
                        return cached
                except Exception as e:
                    logger.warning(f"缓存检查失败: {e}")
            
            logger.info(f"加载配置文件: {len(chunks)} 个文本块, {len(vlm_tasks)} 个图像任务")
            
            async with APIClient() as client:
                # ===== 阶段 1: LLM 文本提取 =====
                if progress_callback:
                    progress_callback(f"开始 LLM 提取 ({len(chunks)} 个文本块)...", 15)
                logger.info("-" * 60)
                logger.info("阶段 1: LLM 文本提取开始")
                logger.info("-" * 60)
                logger.info(f"文本块数量: {len(chunks)}")
                
                chunk_batch_size = self._get_batch_size('chunk')
                if len(chunks) == 1:
                    effective_chunk_batch = 1
                    logger.info("检测到单块模式，使用串行提取")
                else:
                    effective_chunk_batch = min(chunk_batch_size, 2)
                    logger.info(f"批处理大小: {effective_chunk_batch} (已限制并发)")
                self._log_api_config('llm')
                
                llm = LLMExtractor(client, effective_chunk_batch)
                logger.info("开始调用 LLM API...")
                llm_results = await llm.extract_all_chunks(chunks, prompt_template)
                
                logger.info(f"LLM 提取完成, 成功处理 {len(llm_results)}/{len(chunks)} 个文本块")
                if len(llm_results) < len(chunks):
                    failed_count = len(chunks) - len(llm_results)
                    logger.warning(f"警告: {failed_count} 个文本块提取失败，用占位符填充保持索引对齐")
                    for i in range(len(chunks)):
                        if i >= len(llm_results) or llm_results[i] is None:
                            llm_results.insert(i, {"_placeholder": True, "_chunk_index": i, "nanozyme_systems": [], "catalytic_activities": [], "evidence": []})
                
                # ===== 阶段 1.5: TableExtractor 表格提取 =====
                table_results: List[Dict] = []
                if table_extraction_task and table_extraction_task.get("tables"):
                    if progress_callback:
                        tbl_count = len(table_extraction_task.get("tables", []))
                        progress_callback(f"开始表格提取 ({tbl_count} 个表格)...", 40)
                    logger.info("-" * 60)
                    logger.info("阶段 1.5: TableExtractor 表格提取开始")
                    logger.info("-" * 60)
                    try:
                        tbl_ext = TableExtractor(client, batch_size=2)
                        table_results = await tbl_ext.extract_all_tables(table_extraction_task)
                        tbl_success = sum(1 for r in table_results if not r.get("error"))
                        logger.info(f"[Table] 表格提取完成: {tbl_success}/{len(table_results)} 成功")
                    except Exception as tbl_e:
                        logger.warning(f"[Table] 表格提取异常（不影响文本/VLM 结果）: {tbl_e}")
                        table_results = []
                else:
                    logger.info("阶段 1.5: 无 table_extraction_task 或表格为空，跳过表格提取")

                # ===== 阶段 2: VLM 图像提取 =====
                vlm_results = []
                if vlm_tasks:
                    if progress_callback:
                        progress_callback(f"开始 VLM 提取 ({len(vlm_tasks)} 张图片)...", 50)
                    logger.info("-" * 60)
                    logger.info("阶段 2: VLM 图像提取开始")
                    logger.info("-" * 60)
                    logger.info(f"图像任务数量: {len(vlm_tasks)}")
                    
                    vlm_batch_size = self._get_batch_size('vlm')
                    effective_vlm_batch = min(vlm_batch_size, 1)  # 最大1并发
                    logger.info(f"批处理大小: {effective_vlm_batch} (已限制并发)")
                    self._log_api_config('vlm')
                    
                    vlm = VLMExtractor(client, effective_vlm_batch)
                    logger.info("开始调用 VLM API...")
                    vlm_results = await vlm.extract_all_images(vlm_tasks)
                    
                    error_count = sum(1 for r in vlm_results if 'error' in r)
                    logger.info(f"已处理 {len(vlm_results)}/{len(vlm_tasks)} 张图片")
                    logger.info(f"成功: {len(vlm_results) - error_count}, 错误: {error_count}")
                else:
                    logger.info("阶段 2: 无图像任务,跳过 VLM 提取")
                
                # ===== 阶段 3: 结果整合 =====
                if progress_callback:
                    progress_callback("整合结果...", 85)
                logger.info("-" * 60)
                logger.info("阶段 3: 结果整合开始")
                logger.info("-" * 60)
                
                result = self.integrator.integrate(llm_results, vlm_results, extracted_hints=extracted_hints, sentence_metadata=sentence_metadata, pipeline_context={
                    "parse_status": metadata.get("parse_status") if metadata else None,
                    "document_kind": extracted_hints.get("document_kind") if extracted_hints else None,
                    "source_file": metadata.get("source_file") if metadata else None,
                })
                result['metadata'].update(metadata)

                # ===== 表格结果合并 =====
                if table_results:
                    result = self._merge_table_results(result, table_results)
                    logger.info(
                        f"[Table Merge] table_extractions={len(result.get('table_extractions', []))}, "
                        f"kinetics_parameters={len(result.get('kinetics_parameters', []))}, "
                        f"unlinked_table_records={len(result.get('unlinked_table_records', []))}"
                    )

                # paper metadata 主从关系：preprocessor 主，LLM 辅
                # preprocessor metadata 优先，LLM 仅在 preprocessor 缺失时补位
                paper = result.get('paper', {})
                pp_meta = metadata or {}
                field_source = {}
                pp_field_map = {
                    'authors': 'author',
                    'source_file': 'source_file',
                }
                si_author_fallback = None
                if pp_meta.get('is_supplementary') and not pp_meta.get('author'):
                    si_author_fallback = self._try_get_main_author(mid_json_path)
                    if si_author_fallback:
                        logger.info(f"[paper metadata] SI author fallback from main article: {si_author_fallback[:60]}")
                for field in ('title', 'authors', 'journal', 'doi', 'year', 'pages', 'source_file'):
                    pp_key = pp_field_map.get(field, field)
                    pp_val = pp_meta.get(pp_key)
                    if pp_val is None and field == 'source_file':
                        pp_val = pp_meta.get('file_name')
                    if field == 'authors' and pp_val is None and 'author' in pp_meta:
                        pp_val = pp_meta.get('author')
                    if field == 'authors' and pp_val in (None, '') and si_author_fallback:
                        pp_val = si_author_fallback
                    if field == 'year' and isinstance(pp_val, str):
                        try:
                            pp_val = int(pp_val)
                        except (ValueError, TypeError):
                            pass
                    llm_val = paper.get(field)
                    if pp_val not in (None, '', [], {}):
                        paper[field] = pp_val
                        field_source[field] = 'preprocessor'
                        if llm_val not in (None, '', [], {}):
                            logger.info(f"[paper metadata] {field} 来源=preprocessor（覆盖 LLM 值）, 值={pp_val}")
                        else:
                            logger.info(f"[paper metadata] {field} 来源=preprocessor, 值={pp_val}")
                    elif llm_val not in (None, '', [], {}):
                        field_source[field] = 'llm'
                    else:
                        field_source[field] = 'none'
                result['paper_field_source'] = field_source

                result['metadata']['processed_at'] = datetime.now().isoformat()
                result['metadata']['schema_version'] = result.get(
                    'schema_version',
                    result['metadata'].get('schema_version', 'nanozyme.v1')
                )
                result['metadata']['systems_count'] = result['metadata'].get(
                    'systems_count', len(result.get('nanozyme_systems', []))
                )
                result['metadata']['activities_count'] = result['metadata'].get(
                    'activities_count', len(result.get('catalytic_activities', []))
                )
                result['metadata']['figures_count'] = result['metadata'].get(
                    'figures_count', len(result.get('figures', []))
                )
                result['metadata']['evidence_count'] = result['metadata'].get(
                    'evidence_count', len(result.get('evidence', []))
                )
                
                # 统计信息
                fields_count = len(result.get('fields', {}))
                low_confidence = sum(1 for f in result.get('fields', {}).values() if f.get('needs_review', False))
                logger.info(
                    "整合完成, 共提取 %s 个兼容字段, systems=%s, activities=%s",
                    fields_count,
                    result['metadata']['systems_count'],
                    result['metadata']['activities_count'],
                )
                if low_confidence > 0:
                    logger.warning(f"其中 {low_confidence} 个字段置信度较低,建议人工审核")
                
                out_path = self._save_result(mid_json_path, result)
                logger.info(f"结果已保存至: {out_path}")
                logger.info("=" * 60)
                logger.info("大模型提取流程全部完成")
                logger.info("=" * 60)
                
                # 更新缓存
                if self.enable_cache and self.cache_manager:
                    try:
                        self.cache_manager.set(str(mid_json_path), config_hash, result)
                    except Exception as e:
                        logger.warning(f"缓存保存失败: {e}")
                
                if progress_callback:
                    progress_callback("提取完成", 100)
                
                return result
                
        except RuntimeError as e:
            logger.error("=" * 60)
            logger.error(f"提取流程失败: {str(e)}")
            logger.error("=" * 60)
            import traceback
            logger.error(f"详细堆栈:\n{traceback.format_exc()}")
            raise
        except Exception as e:
            logger.error("=" * 60)
            logger.error(f"提取流程发生未知错误: {str(e)}")
            logger.error("=" * 60)
            import traceback
            logger.error(f"详细堆栈:\n{traceback.format_exc()}")
            raise

    async def process_mid_json_single_main_nanozyme(
        self,
        mid_json_path: str,
        progress_callback: Optional[Callable[[str, Optional[int]], None]] = None,
        use_cache: bool = True,
        smn_config: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        single_main_nanozyme 模式：独立轻量 pipeline，不依赖旧多系统逻辑。
        支持 LLM/VLM 失败降级，始终输出完整固定 schema。
        """
        if not SMN_AVAILABLE:
            raise RuntimeError("single_main_nanozyme_extractor 模块不可用")

        mid_json_path = Path(mid_json_path)

        try:
            if progress_callback:
                progress_callback("读取 mid_task.json...", 5)
            logger.info("=" * 60)
            logger.info("[SMN] 开始 single_main_nanozyme 提取流程")
            logger.info("=" * 60)

            with open(mid_json_path, "r", encoding="utf-8") as f:
                mid = json.load(f)

            metadata = mid.get("metadata", {})
            logger.info(
                f"[SMN] mid loaded: "
                f"chunks={len(mid.get('llm_task', {}).get('chunks', []))}, "
                f"vlm_tasks={len(mid.get('vlm_tasks', []))}"
            )

            config_hash = self._build_cache_hash(
                "single_main_nanozyme",
                mid.get("llm_task", {}).get("chunks", []),
            )

            if use_cache and self.enable_cache and self.cache_manager:
                try:
                    cached = self.cache_manager.get(
                        str(mid_json_path), config_hash, check_file_change=True
                    )
                    if cached:
                        logger.info("[SMN] 使用缓存结果")
                        self._save_result(mid_json_path, cached)
                        if progress_callback:
                            progress_callback("使用缓存结果", 100)
                        return cached
                except Exception as e:
                    logger.warning(f"[SMN] 缓存检查失败: {e}")

            if progress_callback:
                progress_callback("提取中...", 20)

            smn_cfg = SMNConfig.from_dict(smn_config) if smn_config else SMNConfig()

            client = None
            try:
                client = APIClient()
                await client.__aenter__()
            except Exception as e:
                logger.warning(f"[SMN] API client 初始化失败: {e}，将使用规则模式")

            try:
                pipeline = SingleMainNanozymePipeline(client=client, config=smn_cfg)
                record = await pipeline.extract(mid)
            finally:
                if client:
                    try:
                        await client.__aexit__(None, None, None)
                    except Exception:
                        pass

            record["extraction_mode"] = SMN_MODE
            record["metadata"] = {
                "source_file": metadata.get("source_file"),
                "extraction_mode": SMN_MODE,
                "processed_at": datetime.now().isoformat(),
                "schema_version": SMN_SCHEMA_VERSION,
            }

            record = validate_schema(record)

            out_path = self._save_result(mid_json_path, record)
            logger.info(f"[SMN] 结果已保存至: {out_path}")
            logger.info(
                f"[SMN] diagnostics: status={record['diagnostics']['status']}, "
                f"confidence={record['diagnostics']['confidence']}, "
                f"warnings={record['diagnostics']['warnings']}"
            )

            if self.enable_cache and self.cache_manager:
                try:
                    self.cache_manager.set(str(mid_json_path), config_hash, record)
                except Exception as e:
                    logger.warning(f"[SMN] 缓存保存失败: {e}")

            if progress_callback:
                progress_callback("提取完成", 100)

            return record

        except Exception as e:
            logger.error("=" * 60)
            logger.error(f"[SMN] 提取流程失败: {str(e)}")
            logger.error("=" * 60)
            import traceback
            logger.error(f"详细堆栈:\n{traceback.format_exc()}")
            raise
    
    def _log_api_config(self, api_type: str):
        """输出 API 配置日志"""
        try:
            normalized_type = {
                'text_llm': 'llm',
                'vision_vlm': 'vlm',
            }.get(api_type, api_type)

            if CONFIG_MANAGER_AVAILABLE and hasattr(self, 'config') and hasattr(self.config, normalized_type):
                api_cfg = getattr(self.config, normalized_type, None)
                if api_cfg:
                    logger.info(f"API配置: {api_cfg.model} @ {api_cfg.base_url}")
                    return
            # 兼容模式：从原始配置读取
            if hasattr(self, '_raw_config') and api_type in self._raw_config:
                cfg = self._raw_config[api_type]
                logger.info(f"API配置: {cfg.get('model', 'unknown')} @ {cfg.get('base_url', 'unknown')}")
                return
            if hasattr(self, '_raw_config'):
                providers = self._raw_config.get('providers', {})
                if normalized_type in providers:
                    cfg = providers[normalized_type]
                    logger.info(f"API配置: {cfg.get('model', 'unknown')} @ {cfg.get('base_url', 'unknown')}")
        except Exception:
            pass

    def _try_get_main_author(self, mid_json_path: Path) -> Optional[str]:
        si_stem = mid_json_path.stem
        main_stem = si_stem.split()[0].strip() if ' ' in si_stem else si_stem.replace(' SI', '').replace('_SI', '')
        parent = mid_json_path.parent
        for candidate in [f"{main_stem}.json", f"{main_stem}_mid_task.json", f"{main_stem}_extracted.json"]:
            candidate_path = parent / candidate
            if candidate_path.exists():
                try:
                    with open(candidate_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    meta = data.get('metadata', {})
                    author = meta.get('author')
                    if author and isinstance(author, str) and len(author.strip()) > 2:
                        return author.strip()
                except Exception:
                    pass
        return None

    def _merge_table_results(
        self,
        result: Dict[str, Any],
        table_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        将 TableExtractor 的结果合并到最终 result 中。

        - table_extractions：原始表格抽取记录（按表格 ID）
        - kinetics_parameters：所有 kinetics_parameters 类型记录
        - material_properties：material_surface_properties 类型记录
        - electronic_structure：electronic_structure 类型记录
        - unlinked_table_records：无法关联到 catalytic_activities 的动力学记录
        - 尝试将 kinetics 记录 merge 到 catalytic_activities（粗匹配）
        """
        import re

        result.setdefault("table_extractions", [])
        result.setdefault("kinetics_parameters", [])
        result.setdefault("material_properties", [])
        result.setdefault("electronic_structure", [])
        result.setdefault("unlinked_table_records", [])

        all_kinetics_records: List[Dict[str, Any]] = []

        for tbl_result in table_results:
            if tbl_result.get("error"):
                logger.warning(
                    f"[Table Merge] 跳过错误表格 {tbl_result.get('table_id')}: {tbl_result.get('error')}"
                )
                continue

            records = tbl_result.get("records", [])
            table_id = tbl_result.get("table_id", "")
            table_type = tbl_result.get("table_type", "general_table")

            # 原始记录汇总
            result["table_extractions"].append({
                "table_id": table_id,
                "table_type": table_type,
                "source_page": tbl_result.get("source_page"),
                "caption": tbl_result.get("caption", ""),
                "record_count": len(records),
                "warnings": tbl_result.get("warnings", []),
                "records": records,
            })

            for rec in records:
                if not isinstance(rec, dict):
                    continue
                rtype = rec.get("record_type", table_type)

                if rtype in ("kinetics_parameters", "kinetics"):
                    # 保证 source_table_id 字段
                    rec.setdefault("source_table_id", table_id)
                    result["kinetics_parameters"].append(rec)
                    all_kinetics_records.append(rec)

                elif rtype in ("material_surface_properties", "material_property"):
                    rec.setdefault("source_table_id", table_id)
                    result["material_properties"].append(rec)

                elif rtype in ("electronic_structure",):
                    rec.setdefault("source_table_id", table_id)
                    result["electronic_structure"].append(rec)

                else:
                    rec.setdefault("source_table_id", table_id)
                    result["unlinked_table_records"].append(rec)

        # ---- 尝试将 kinetics 记录 merge 到 catalytic_activities ----
        catalytic_activities = result.get("catalytic_activities", [])
        if catalytic_activities and all_kinetics_records:
            unlinked: List[Dict[str, Any]] = []
            for krec in all_kinetics_records:
                matched = self._try_link_kinetics_to_activity(krec, catalytic_activities)
                if not matched:
                    unlinked.append(krec)
                    result["unlinked_table_records"].append(krec)
            logger.info(
                f"[Table Merge] kinetics 记录关联: {len(all_kinetics_records) - len(unlinked)} 成功, "
                f"{len(unlinked)} 未关联（保留为 unlinked_table_records）"
            )
        elif all_kinetics_records:
            result["unlinked_table_records"].extend(all_kinetics_records)

        return result

    def _try_link_kinetics_to_activity(
        self,
        krec: Dict[str, Any],
        catalytic_activities: List[Dict[str, Any]],
    ) -> bool:
        """
        尝试将单条 kinetics 记录关联到 catalytic_activities 中的某条记录。
        匹配规则（粗匹配）：material + enzyme_like_activity + substrate。
        成功时将 kinetics 数值注入对应 activity；失败返回 False。
        """
        mat = (krec.get("material") or "").lower().strip()
        enz = (krec.get("enzyme_like_activity") or "").lower().strip()
        sub = (krec.get("substrate") or "").lower().strip()

        for act in catalytic_activities:
            # material 匹配（system_name 或 material_name_raw）
            act_mat = (
                (act.get("system_name") or act.get("material_name_raw") or "")
                .lower().strip()
            )
            act_enz = (act.get("enzyme_like_type") or "").lower().strip()
            act_sub = ""
            for km_entry in act.get("kinetics", []):
                if isinstance(km_entry, dict):
                    act_sub_candidate = (km_entry.get("substrate") or "").lower().strip()
                    if act_sub_candidate:
                        act_sub = act_sub_candidate
                        break
            if not act_sub:
                for s in act.get("substrates", []):
                    if isinstance(s, str) and s.strip():
                        act_sub = s.lower().strip()
                        break

            # 粗匹配：两个以上字段非空且一致
            score = 0
            if mat and act_mat and (mat in act_mat or act_mat in mat):
                score += 2
            if enz and act_enz and (enz in act_enz or act_enz in enz):
                score += 1
            if sub and act_sub and (sub in act_sub or act_sub in sub):
                score += 1

            if score >= 2:
                # 将 kinetics 数值注入到 activity
                act.setdefault("kinetics_from_table", [])
                act["kinetics_from_table"].append({
                    "Km_value": krec.get("Km_value"),
                    "Km_unit": krec.get("Km_unit"),
                    "Vmax_value": krec.get("Vmax_value"),
                    "Vmax_unit": krec.get("Vmax_unit"),
                    "kcat_value": krec.get("kcat_value"),
                    "kcat_unit": krec.get("kcat_unit"),
                    "substrate": krec.get("substrate"),
                    "source_table_id": krec.get("source_table_id"),
                    "source_page": krec.get("source_page"),
                })
                return True

        return False

    def _build_cache_hash(self, prompt_template: str, chunks: Optional[List[str]] = None) -> str:
        try:
            from nanozyme_preprocessor_midjson import VERSION as preprocessor_version
        except ImportError:
            preprocessor_version = "nanozyme.v1.2"
        chunks_hash = ""
        if chunks:
            chunks_combined = "\n---CHUNK_BOUNDARY---\n".join(chunks)
            chunks_hash = hashlib.md5(chunks_combined.encode('utf-8')).hexdigest()[:16]
        hash_input = f"{preprocessor_version}:{prompt_template}:{chunks_hash}"

        if CONFIG_MANAGER_AVAILABLE and hasattr(self, 'config'):
            return self.config.get_config_hash({
                'prompt_template': prompt_template,
                'preprocessor_version': preprocessor_version,
                'chunks_hash': chunks_hash,
            })

        return hashlib.md5(hash_input.encode('utf-8')).hexdigest()[:16]

    def _save_result(self, mid_json_path: Path, result: Dict[str, Any]) -> Path:
        out_path = self.output_dir / f"{mid_json_path.stem}_extracted.json"
        temp_path = self.output_dir / f"{mid_json_path.stem}_extracted.json.tmp"

        result.setdefault('metadata', {})
        result['metadata']['output_path'] = str(out_path)

        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            temp_path.replace(out_path)
        except PermissionError:
            alt_path = self.output_dir / f"{mid_json_path.stem}_extracted_alt.json"
            logger.warning(f"目标文件被锁定，保存至替代路径: {alt_path}")
            result['metadata']['output_path'] = str(alt_path)
            with open(alt_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            out_path = alt_path
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

        return out_path
    
    def _get_batch_size(self, type_name: str) -> int:
        """获取批处理大小"""
        if CONFIG_MANAGER_AVAILABLE and hasattr(self, 'config') and hasattr(self.config, 'pipeline'):
            try:
                if type_name == 'chunk':
                    return self.config.pipeline.chunk_batch_size
                elif type_name == 'vlm':
                    return self.config.pipeline.vlm_batch_size
            except Exception:
                pass
        # 兼容模式：从原始配置读取
        if hasattr(self, '_raw_config'):
            if type_name == 'chunk':
                return self._raw_config.get('chunk_batch_size', 5)
            elif type_name == 'vlm':
                return self._raw_config.get('vlm_batch_size', 2)
        return 5  # 默认值
    
    def process_mid_json_sync(
        self,
        mid_json_path: str,
        progress_callback: Optional[Callable[[str, Optional[int]], None]] = None,
        use_cache: bool = True,
        extraction_mode: Optional[str] = None,
    ) -> str:
        """
        同步执行提取，返回结果 JSON 文件路径

        Args:
            mid_json_path: 中间任务JSON路径
            progress_callback: 进度回调
            use_cache: 是否使用缓存
            extraction_mode: 提取模式，None 则自动检测

        Returns:
            结果JSON文件路径
        """
        if extraction_mode is None:
            try:
                with open(mid_json_path, "r", encoding="utf-8") as f:
                    mid = json.load(f)
                extraction_mode = mid.get("metadata", {}).get("extraction_mode", "canonical_multi_system")
            except Exception:
                extraction_mode = "canonical_multi_system"

        if extraction_mode == "single_main_nanozyme" and SMN_AVAILABLE:
            result = asyncio.run(self.process_mid_json_single_main_nanozyme(
                mid_json_path, progress_callback, use_cache
            ))
        else:
            result = asyncio.run(self.process_mid_json(
                mid_json_path, progress_callback, use_cache
            ))
        return result.get('metadata', {}).get(
            'output_path',
            str(self.output_dir / f"{Path(mid_json_path).stem}_extracted.json")
        )
    
    def run_feedback(self, mid_json_path: str, corrections: Dict[str, Any]) -> None:
        """
        处理人工反馈
        
        Args:
            mid_json_path: 中间任务JSON路径
            corrections: 修正数据
        """
        for field, new_val in corrections.items():
            self.rule_learner.learn_from_correction(field, None, new_val)
        logger.info(f"已记录 {len(corrections)} 条反馈")
        
        self.rule_learner.update_keyword_weights_from_feedback()
        logger.info("规则权重已根据反馈自动更新，下次预处理将加载新权重")
    
    def invalidate_cache(self, mid_json_path: str) -> None:
        """使缓存失效"""
        if self.cache_manager:
            self.cache_manager.invalidate(mid_json_path)
            logger.info(f"缓存已失效: {mid_json_path}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = {
            'output_dir': str(self.output_dir),
            'confidence_threshold': self.confidence_threshold,
        }
        
        if self.cache_manager:
            stats['cache'] = self.cache_manager.get_statistics()
        
        if self.task_queue:
            stats['queue'] = self.task_queue.get_statistics()
        
        return stats


async def main():
    """命令行入口"""
    if len(sys.argv) < 2:
        print("用法: python extraction_pipeline.py <mid_task.json> [--no-cache]")
        sys.exit(1)
    
    mid_json_path = sys.argv[1]
    use_cache = '--no-cache' not in sys.argv
    
    pipeline = ExtractionPipeline()
    
    def progress_callback(msg, percent):
        print(f"[进度 {percent}%] {msg}")
    
    result = await pipeline.process_mid_json(
        mid_json_path,
        progress_callback=progress_callback,
        use_cache=use_cache
    )
    
    # 显示需要审核的字段
    needs_review = {k: v for k, v in result['fields'].items() if v.get('needs_review')}
    if needs_review:
        print("\n⚠️ 以下字段置信度较低，建议人工确认：")
        for field, info in needs_review.items():
            print(f"  {field}: {info['value']} (置信度: {info['confidence']:.2f})")
        
        if input("\n是否输入修正值？(y/n): ").lower() == 'y':
            corrections = {}
            for field in needs_review:
                new_val = input(f"{field} 的正确值 (回车跳过): ").strip()
                if new_val:
                    field_def = next((f for f in get_field_defs() if f['name'] == field), None)
                    if field_def and field_def['type'] == 'float':
                        try:
                            new_val = float(new_val)
                        except:
                            pass
                    corrections[field] = new_val
            if corrections:
                pipeline.run_feedback(mid_json_path, corrections)
                print("反馈已记录，规则库已更新。")


if __name__ == "__main__":
    if MODULES_AVAILABLE:
        asyncio.run(main())
    else:
        print("错误: 缺少必要的依赖模块")
        sys.exit(1)
