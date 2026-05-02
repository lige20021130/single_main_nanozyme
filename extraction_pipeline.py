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
            extraction_mode: 保留参数兼容，始终使用 single_main_nanozyme

        Returns:
            结果JSON文件路径
        """
        if not SMN_AVAILABLE:
            raise RuntimeError("single_main_nanozyme_extractor 模块不可用")

        result = asyncio.run(self.process_mid_json_single_main_nanozyme(
            mid_json_path, progress_callback, use_cache
        ))
        return result.get('metadata', {}).get(
            'output_path',
            str(self.output_dir / f"{Path(mid_json_path).stem}_extracted.json")
        )
    
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
    
    result = await pipeline.process_mid_json_single_main_nanozyme(
        mid_json_path,
        progress_callback=progress_callback,
        use_cache=use_cache
    )
    
    sel = result.get("selected_nanozyme", {})
    if sel:
        print(f"\n提取完成: {sel.get('name', 'unknown')}")
        act = result.get("main_activity", {})
        kin = act.get("kinetics", {})
        if kin.get("Km"):
            print(f"  Km = {kin['Km']}")
        if kin.get("Vmax"):
            print(f"  Vmax = {kin['Vmax']}")
    else:
        print("\n未提取到主纳米酶信息")


if __name__ == "__main__":
    if SMN_AVAILABLE:
        asyncio.run(main())
    else:
        print("错误: 缺少 single_main_nanozyme_extractor 模块")
        sys.exit(1)
