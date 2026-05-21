# 系统模块知识图谱

> 本规则是编程 AI 对系统架构的实时认知地图。任何涉及模块增删改查的代码修改后，必须同步更新此文件对应条目。

## 架构总览

```
PDF输入 → 预处理 → 规则/LLM/VLM多源提取 → 交叉验证 → 一致性修正 → 数值校验 → Schema验证 → 输出JSON
                ↘ GUI交互 ↗                      ↘ 诊断报告 ↗
```

## 核心管道层（按数据流顺序）

| 模块文件 | 核心类/函数 | 职责 | 关键依赖 |
|----------|-----------|------|---------|
| `run_extraction.py` | `main()` | 系统入口，CLI参数解析，PDF→JSON全流程调度 | extraction_pipeline, nanozyme_preprocessor_midjson, opendataloader_pdf |
| `extraction_pipeline.py` | `ExtractionPipeline` | 管道编排，超时控制，缓存/配置/队列集成，批量处理 | api_client, single_main_nanozyme_extractor, config_manager, cache_manager, task_queue |
| `nanozyme_preprocessor_midjson.py` | `NanozymePreprocessor`, `BlockInfo`, `FigureInfo`, `SentenceInfo` | PDF中JSON预处理，分块/分句/分表/分图，结构化文档对象 | 无外部依赖 |
| `single_main_nanozyme_extractor.py` | `SingleMainNanozymePipeline`, `SMNConfig`, `PreprocessedDocument`, `RuleExtractor`, `NanozymeScorer`, `EvidenceBucketBuilder`, `TableProcessor`, `FigureProcessor`, `NumericValidator`, `DiagnosticsBuilder`, `PaperMetadataExtractor`, `CandidateRecaller`, `LanguageRuleAdapter` | **核心大文件(6400+行)**：单主纳米酶提取全流程，含正则模式库、候选筛选、规则提取(LLM-First兜底)、LLM精炼、VLM调用、动力学回填、Schema验证 | extraction_agents, cross_validation_agent, consistency_agent, consistency_guard_agentic, extraction_verifier, vlm_extractor, llm_refinement, numeric_validator, domain_knowledge |

## 提取引擎层

| 模块文件 | 核心类/函数 | 职责 | 关键依赖 |
|----------|-----------|------|---------|
| `extraction_agents.py` | `KineticsAgent`, `MorphologyAgent`, `SynthesisAgent`, `ApplicationAgent`, `RuleExtractorAdapter` | 4个专业提取Agent + 适配器，替代原始RuleExtractor | single_main_nanozyme_extractor(正则模式), numeric_validator |
| `material_identifier.py` | `MaterialIdentifier`, `PROBE_MOLECULES` | LLM-First材料识别器，识别主纳米酶和关联体系，探针分子黑名单从domain_knowledge加载 | api_client, domain_knowledge |
| `llm_extractor.py` | `LLMExtractor`, `TableExtractor`, `JSONFixer`, `_get_engine()` | LLM文本提取（全文+表格），JSON修复，ConstrainedDecodingEngine集成 | api_client, constrained_decoding |
| `llm_structured_extractor.py` | `LLMStructuredExtractor`, `_get_engine()` | LLM结构化提取核心模块（LLM-First模式），分任务提取（动力学/形态/应用/酶类型），self-augmentation两步提取，Vmax自动单位转换，Km量级校验，ConstrainedDecodingEngine集成 | extraction_prompts, schema_constraints, api_client, constrained_decoding |
| `extraction_prompts.py` | `build_kinetics_prompt()`, `build_morphology_prompt()`, `build_application_prompt()`, `build_enzyme_type_prompt()`, `build_self_augmentation_prompt()` | LLM提取prompt模板库，底物知识从domain_knowledge动态注入 | schema_constraints, domain_knowledge |
| `schema_constraints.py` | `validate_against_schema()`, `auto_fix_schema_errors()`, `get_schema_for_openai()`, `get_task_schema_for_openai()`, `NANOZYME_EXTRACTION_SCHEMA`, `TASK_SCHEMAS`, `_fix_numeric_strings()`, `_remove_unknown_fields()`, `_fix_enum_values()` | JSON schema约束定义，用于constrained decoding和输出验证，6个子任务Schema，增强auto_fix | domain_knowledge |
| `vlm_extractor.py` | `VLMExtractor` | 视觉语言模型图像提取（动力学图表/形态图） | api_client |
| `activity_selector.py` | `ActivitySelector` | 催化活性类型选择与匹配 | 无外部依赖 |
| `application_extractor.py` | `ApplicationExtractor`, `extract_method()`, `extract_sample_type()` | 应用信息提取（类型/方法/样品） | 无外部依赖 |
| `figure_handler.py` | `FigureHandler`, `extract_figure_candidates()`, `extract_caption_explicit_values()` | 图像分类与标题值提取 | single_main_nanozyme_extractor |
| `table_classifier.py` | `TableClassifier` | 表格分类（动力学/表征/合成/传感） | 无外部依赖 |

## 验证与一致性层

| 模块文件 | 核心类/函数 | 职责 | 关键依赖 |
|----------|-----------|------|---------|
| `cross_validation_agent.py` | `CrossValidationAgent`, `check_multi_figure_kinetics_consistency()` | 多源(Rule/LLM/VLM)交叉验证，冲突检测与合并，多图间动力学一致性检查 | 无外部依赖 |
| `consistency_agent.py` | `ConsistencyAgent`, `check_analyte_enzyme_consistency()`, `_ANALYTE_ENZYME_INCOMPATIBILITY` | 输出一致性修正：酶类型归一化、材料名去后缀、应用去重、单位归一化、分析物-酶类型兼容性检查(从domain_knowledge加载) | nanozyme_models, domain_knowledge |
| `consistency_guard.py` | `ConsistencyGuard` | 对比表/他人物质检测，防止提取非目标纳米酶数据 | 无外部依赖 |
| `consistency_guard_agentic.py` | `AgenticConsistencyGuard`, `IssueSeverity`, `GuardIssue`, `GuardCheckResult` | 智能一致性守卫，LLM辅助裁决冲突 | nanozyme_models, api_client |
| `extraction_verifier.py` | `ExtractionVerifier` | 提取结果验证，字段与原文证据交叉核对 | 无外部依赖 |
| `numeric_validator.py` | `NumericValidator`, `normalize_unit()`, `is_concentration_unit()`, `is_rate_unit()`, `calibrate_magnitude_ranges()`, `validate_nanozyme_kinetics()` | 数值范围校验、单位归一化、量级标定、纳米酶领域知识验证（酶类型-量级范围-分析物兼容性，从domain_knowledge加载） | domain_knowledge |

## 数据模型层

| 模块文件 | 核心类/函数 | 职责 | 关键依赖 |
|----------|-----------|------|---------|
| `domain_knowledge.yaml` | (YAML数据) | 领域知识单一真相源：38种酶类型、9种应用类型、17种探针分子、底物映射、数值范围、单位转换 | 无外部依赖 |
| `domain_knowledge.py` | `DomainKnowledge`, `get_domain_knowledge()` | 领域知识加载器，提供别名映射、枚举值、Prompt片段生成等统一接口，单例模式 | yaml |
| `nanozyme_models.py` | `EnzymeType(Enum)`, `ApplicationType(Enum)`, `normalize_canonical()`, `_ENZYME_ALIAS_MAP`, `_APPLICATION_TYPE_ALIAS_MAP`, `get_application_type_enum_string()` | 酶类型+应用类型枚举与归一化映射，动态从domain_knowledge加载 | domain_knowledge |
| `single_main_nanozyme_extractor.py` 顶层 | `EMPTY_RECORD`, `validate_schema()`, `_SCHEMA_TOP_KEYS` | 输出JSON Schema定义与验证（含EnzymeType/ApplicationType枚举校验） | nanozyme_models |

## 基础设施层

| 模块文件 | 核心类/函数 | 职责 | 关键依赖 |
|----------|-----------|------|---------|
| `dependencies.py` | `is_available()`, `get_module()`, `get_attr()`, `require()`, `clear_cache()` | 统一依赖管理，替代散布的try/except ImportError | importlib |
| `logging_setup.py` | `setup_logging()`, `get_logger()`, `ColoredFormatter`, `GUILogHandler` | 统一日志配置，RotatingFileHandler，模块级日志级别 | logging |
| `api_client.py` | `APIClient`, `RateLimitConfig`, `TokenBucket`, `supports_json_schema()` | LLM/VLM API调用，令牌桶限流，重试机制，json_schema支持检测 | config_manager, constrained_decoding |
| `config_manager.py` | `ConfigManager`, `LLMConfig`, `VLMConfig`, `PipelineConfig`, `FieldDefinition`, `RateLimitConfig`, `CacheConfig`, `PreprocessorConfig`, `ImageFilterConfig`, `QueueConfig` | 全局配置管理，YAML加载，默认值 | yaml |
| `constrained_decoding.py` | `ConstrainedDecodingEngine`, `SUPPORTED_JSON_SCHEMA_PREFIXES` | 多层约束解码引擎：json_schema模式→json_object模式→后验证+auto_fix，模型能力检测，Schema Prompt注入 | schema_constraints, api_client |

## GUI层

| 模块文件 | 核心类/函数 | 职责 | 关键依赖 |
|----------|-----------|------|---------|
| `pdf_basic_gui.py` | `PDFBasicGUI`, `FileProcessReport`, `ResultReviewDialog` | 桌面GUI，PDF选择/处理/结果审阅 | extraction_pipeline, tkinter |

## 评估层

| 模块文件 | 核心类/函数 | 职责 | 关键依赖 |
|----------|-----------|------|---------|
| `eval/evaluate.py` | `Evaluator` | 提取结果与金标准对比评估 | 无外部依赖 |
| `eval/run_eval.py` | `run_extraction()`, `run_evaluation()`, `main()` | 评估流程入口 | evaluate |
| `eval/unit_normalizer.py` | (模块级函数) | 单位归一化与转换 | 无外部依赖 |
| `eval/batch_report.py` | (模块级函数) | 批量评估报告生成 | evaluate |

## 测试层

| 模块文件 | 职责 |
|----------|------|
| `tests/conftest.py` | pytest共享fixture |
| `tests/test_dependencies.py` | dependencies模块单元测试 |
| `tests/test_dependencies_migration.py` | 依赖迁移验证测试 |
| `tests/test_enzyme_type_normalization.py` | 酶类型归一化测试 |
| `tests/test_domain_knowledge.py` | 领域知识加载器测试 |
| `tests/test_logging_setup.py` | 日志配置测试 |
| `tests/test_pipeline_timeout.py` | 管道超时测试 |
| `test_single_main_nanozyme.py` | 核心提取器集成测试（旧式） |

## 脚本与工具

| 文件 | 职责 |
|------|------|
| `batch_test_2021.py` | 2021批次文献批量测试脚本 |
| `full_pipeline_test.py` | 全流程端到端测试脚本 |
| `start.bat` | Windows启动脚本 |
| `diagnostics_builder.py` | 独立诊断构建器（25+警告枚举，field_coverage，batch_report） |

## 关键数据流路径

1. **动力学提取**: `LLMStructuredExtractor.extract_kinetics`(LLM-First) → `RuleExtractor` → `KineticsAgent` → `_extract_kinetics_from_text/table/flattened_table` → `_backfill_kinetics_units` → `NumericValidator`
2. **LLM精炼**: `SingleMainNanozymePipeline._call_llm_with_refinement` → `llm_refinement.AgenticLLMExtractor` → `LLMSchemaValidator` → 回填
3. **VLM提取**: `SingleMainNanozymePipeline._call_vlm` → `VLMExtractor` → 结果合并到important_values → 回填kinetics
4. **交叉验证**: Rule结果 + LLM结果 + VLM结果 → `CrossValidationAgent.merge_results` → 冲突检测 → 合并 → `check_multi_figure_kinetics_consistency` 多图一致性
5. **一致性修正**: `ConsistencyAgent.normalize_output` → 酶类型/材料名/应用/单位归一化 → `check_analyte_enzyme_consistency` 分析物-酶类型兼容性检查
6. **数值校验**: `NumericValidator.validate` → 量级范围检查 → 单位验证 → 诊断标记
7. **Schema验证**: `validate_schema` → 字段完整性 → EnzymeType/ApplicationType枚举校验 → 状态/置信度赋值
8. **约束解码**: `ConstrainedDecodingEngine.call` → 模型能力检测(`_detect_json_schema_support`) → json_schema模式(OpenAI兼容) / json_object模式(通用) → `_inject_schema_prompt` Schema约束注入 → `_validate_and_fix` 后验证+auto_fix

## 更新规则

当发生以下情况时，必须更新本文件：

- **新增模块**：在对应层级添加条目
- **删除模块**：移除条目并检查所有引用该模块的"关键依赖"列
- **模块职责变更**：更新职责描述和核心类/函数
- **类/函数重命名**：更新核心类/函数列
- **依赖关系变化**：更新关键依赖列
- **数据流变化**：更新关键数据流路径

更新时只需修改受影响的条目，不需要重写整个文件。
