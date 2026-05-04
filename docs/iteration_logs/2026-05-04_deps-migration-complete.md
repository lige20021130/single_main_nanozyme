# 依赖管理统一迁移完成

## 更新时间
2026-05-04 22:30

## 更新类型
- 重构

## 背景
项目中存在大量分散的 `try/except ImportError` 模式和重复的 `from numeric_validator import normalize_unit` 导入，导致代码冗余、维护困难。需要将所有依赖检查统一迁移到 `dependencies` 模块。

## 改动内容
- **api_client.py**: `CONFIG_MANAGER_AVAILABLE` 从 `try/except` 迁移到 `is_available("config_manager")`
- **run_extraction.py**: PDF预处理依赖迁移到 `is_available()` 检查 `opendataloader_pdf` 和 `nanozyme_preprocessor_midjson`
- **extraction_agents.py**: 数值验证函数迁移到 `get_attr()` 获取 `normalize_unit`、`is_concentration_unit`、`is_rate_unit`
- **single_main_nanozyme_extractor.py** (核心大文件):
  - 顶层 `IssueSeverity` 导入从 `try/except` 迁移到 `is_available("consistency_guard_agentic")`
  - 模块级添加 `_normalize_unit_fn`、`_is_concentration_unit_fn`、`is_rate_unit_fn` 通过 `get_attr()` 获取
  - 消除 7 处重复 `from numeric_validator import normalize_unit as _norm_unit` try/except 块
  - 消除 5 处 inline `from numeric_validator import` 调用
  - 9 处类内部 `try/except ImportError` 迁移到 `is_available()` 模式
  - `_validate_and_assign_kinetics_unit` 函数改用模块级函数引用
  - `calibrate_magnitude_ranges` 迁移到 `get_attr()` 模式
- **tests/test_dependencies_migration.py**: 新增迁移验证测试

## 未改动内容
- dependencies.py 核心逻辑未变
- extraction_pipeline.py 未变（已在之前迁移完成）
- GUI 相关模块未涉及

## 验证方式
- `python -m pytest tests/ -v --tb=short` → 107 passed, 0 failed
- `py_compile.compile` 语法检查通过
- 确认 `single_main_nanozyme_extractor.py` 中无残留 `from numeric_validator import` 和 `except ImportError`

## 风险与后续
- GitHub push 因网络问题失败，本地已提交，待网络恢复后手动 push
- 后续可考虑将 `_normalize_unit_fn` 等模块级引用封装为更优雅的延迟加载模式
