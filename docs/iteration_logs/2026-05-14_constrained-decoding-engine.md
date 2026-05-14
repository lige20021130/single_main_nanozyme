# 约束解码引擎实现

## 更新时间
2026-05-14 12:00

## 更新类型
- 功能开发

## 背景
系统LLM输出的JSON结构合规率约92%，主要问题包括：未知字段、数值字符串、无效枚举值、缺少必要字段。参考research_思路报告的阶段一方案，实现多层约束解码策略，目标将合规率提升至>99%。

## 改动内容

### 新增文件
- `constrained_decoding.py`：ConstrainedDecodingEngine核心引擎
  - 4层约束策略：json_schema模式 → json_object模式 → 后验证+auto_fix → Schema Prompt注入
  - 模型能力自动检测（SUPPORTED_JSON_SCHEMA_PREFIXES）
  - 子任务Schema路由（TASK_SCHEMAS）
  - JSON解析容错（代码块提取、嵌入JSON提取）

### 修改文件
- `schema_constraints.py`：
  - 主Schema增强：所有object添加additionalProperties=False、required字段、enum约束
  - 新增6个子任务Schema：KINETICS_TASK_SCHEMA、MORPHOLOGY_TASK_SCHEMA、SYNTHESIS_TASK_SCHEMA、APPLICATION_TASK_SCHEMA、ENZYME_TYPE_TASK_SCHEMA、PH_PROFILE_TASK_SCHEMA
  - 新增TASK_SCHEMAS注册表和get_task_schema_for_openai()函数
  - 新增_fix_numeric_strings()：递归修复数值字符串为数字类型
  - 新增_remove_unknown_fields()：基于Schema递归删除未知字段
  - 新增_fix_enum_values()：基于Schema递归修复无效枚举值
  - 增强auto_fix_schema_errors()：集成上述3个修复函数+enum错误修复

- `api_client.py`：
  - 新增supports_json_schema()方法：检测当前模型是否支持json_schema模式

- `llm_structured_extractor.py`：
  - 替换instructor模式为ConstrainedDecodingEngine
  - 新增_get_engine()懒加载方法
  - _call_llm_structured()优先使用CDE，失败后fallback到原有json_object模式

- `llm_extractor.py`：
  - 新增_get_engine()懒加载方法
  - extract_single_chunk()优先使用CDE，失败后fallback到原有直接调用

### 文档更新
- `.trae/rules/MODULE_MAP.md`：新增constrained_decoding.py条目，更新api_client/schema_constraints/llm_structured_extractor/llm_extractor条目，新增约束解码数据流路径

## 未改动内容
- `extraction_agents.py`：纯正则Agent，不涉及LLM调用，无需修改
- `extraction_prompts.py`：Prompt模板不变
- `single_main_nanozyme_extractor.py`：核心管道不变
- `consistency_agent.py`、`numeric_validator.py`等验证层不变

## 验证方式
- test/test_task1_schema.py：6项Schema测试全部通过
- test/test_task2_cde.py：15项CDE测试全部通过（模型检测、Prompt注入、JSON解析、async调用）
- test/test_integration_cde.py：6项集成测试全部通过（全模块导入、跨模块交互、Mock端到端）

## 风险与后续
- json_schema模式对非OpenAI兼容模型可能不支持，已有fallback机制
- 子任务Schema与主Schema的验证策略差异需要实际PDF测试验证
- 后续可考虑：VLM提取器也接入CDE、更多模型前缀添加到SUPPORTED_JSON_SCHEMA_PREFIXES
