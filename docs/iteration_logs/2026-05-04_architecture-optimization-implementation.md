# 架构优化实施：6 项优化全部完成

## 更新时间
2026-05-04 19:00

## 更新类型
- 架构调整 / 功能开发 / 测试

## 背景
基于架构审查报告，按 TDD 方式实施 6 项优化，提升系统性能、稳定性和可扩展性。

## 改动内容

### Task A: 合并重复的酶类型映射为单一源
- 新增 `nanozyme_models.py`：统一 `EnzymeType` 枚举 + `normalize_canonical()` 函数
- 更新 `consistency_agent.py`、`activity_selector.py`、`consistency_guard_agentic.py`：移除内联映射，统一调用 `nanozyme_models.normalize_canonical()`
- 新增 `tests/test_enzyme_type_normalization.py`：81 个参数化测试覆盖所有别名

### Task B: 移除 single_record_assembler.py 废弃代码
- 删除 `single_record_assembler.py`（旧多系统逻辑，已不再使用）

### Task C: 统一日志配置
- 增强 `logging_setup.py`：添加 `RotatingFileHandler`（10MB/5 备份）、`GUILogHandler` 共享类
- 简化 `extraction_pipeline.py`：移除条件日志判断，直接使用 `logging_setup`
- 更新 `pdf_basic_gui.py`：移除内联 `GUILogHandler`，改用共享版本
- 新增 `tests/test_logging_setup.py`：4 个测试

### Task D: 添加全局 pipeline 超时
- `extraction_pipeline.py`：新增 `per_document_timeout`（默认 600s）和 `pipeline_timeout`（默认 3600s）参数
- 提取调用包裹 `asyncio.wait_for`，超时抛出 `TimeoutError`
- 新增 `tests/test_pipeline_timeout.py`：4 个测试

### Task E: 统一依赖管理模块
- 新增 `dependencies.py`：`is_available()`、`get_module()`、`get_attr()`、`require()` API
- 更新 `extraction_pipeline.py`：用 `dependencies` 替代 try/except ImportError
- 更新 `pdf_basic_gui.py`：用 `dependencies` 替代 try/except ImportError
- 新增 `tests/test_dependencies.py`：11 个测试

### Task F: 建立 tests/ 目录 + pytest 基础结构
- 创建 `tests/` 目录，含 `conftest.py`、`__init__.py`

## 未改动内容
- `eval/` 目录下的评估脚本未动
- `run_extraction.py` 的 try/except 保留（非核心路径）
- `extraction_agents.py` 的 try/except 保留（非核心路径）

## 验证方式
- 全量测试：`python -m pytest tests/ -v` → **100 passed, 0 failed**
- 零回归确认

## 风险与后续
- `dependencies.py` 的缓存机制在模块动态安装场景下可能需要 `clear_cache()`
- 建议后续将 `extraction_agents.py` 和 `run_extraction.py` 也迁移到 `dependencies` 模块
