# LLM-First提取架构替代规则提取

## 更新时间
2026-05-08 22:30

## 更新类型
- 功能开发 / 架构调整

## 背景
当前系统使用RuleExtractor（基于正则表达式）作为主要提取方式，存在以下瓶颈：
1. 正则模式爆炸（50+个正则仍无法覆盖所有表述变体）
2. 上下文丢失（逐行匹配无法理解指代关系）
3. 多底物动力学数据大量丢失
4. 材料名识别差（基于频率+后缀的候选评分）
5. 酶类型在多酶活性论文中常误判
6. 维护成本高

通过阅读三篇文献信息提取论文（CMPB 2025, Chem Soc Rev 2025, Nature Communications 2025），确定了LLM-First架构替代方案。

## 改动内容

### 新增文件
- `schema_constraints.py`: JSON schema约束模块，用于约束LLM输出格式，包含纳米酶提取的完整schema定义、酶类型/应用类型枚举、Km/Vmax量级验证和自动修复
- `extraction_prompts.py`: LLM提取prompt模板库，包含5类子任务的system prompt、user prompt和few-shot examples（动力学3例、形态1例、应用2例），以及self-augmentation prompt
- `llm_structured_extractor.py`: LLM结构化提取核心模块，实现LLMStructuredExtractor类，支持分任务提取（动力学/形态/应用/酶类型）、self-augmentation两步提取、Vmax自动单位转换、Km量级校验
- `tests/test_schema_constraints.py`: schema约束模块测试（15个用例）
- `tests/test_llm_structured_extractor.py`: LLM提取器测试（14个用例）

### 修改文件
- `single_main_nanozyme_extractor.py`:
  - `__init__`中添加`self.llm_structured`（LLMStructuredExtractor实例，当client和enable_llm可用时加载）
  - `extract()`方法中在规则提取之前添加LLM结构化提取路径（LLM-First，规则降级为fallback）
  - 新增`_apply_llm_structured_result()`方法，将LLM提取结果填入record（仅填充空字段，不覆盖已有值）
  - 在数值校验后添加`validate_nanozyme_kinetics()`领域知识验证
- `numeric_validator.py`:
  - 新增`validate_nanozyme_kinetics()`方法：基于酶类型的Km/Vmax典型量级范围验证、kinetics_list逐条验证、分析物-酶类型兼容性检查
  - 新增`_to_mM()`和`_to_uM_per_s()`单位转换辅助方法
  - 新增`_NANOZYME_KM_RANGES`、`_NANOZYME_VMAX_RANGES`、`_ANALYTE_ENZYME_COMPATIBILITY`领域知识常量

## 未改动内容
- Schema（EMPTY_RECORD）结构未修改
- 现有规则提取（RuleExtractor/RuleExtractorAdapter）保留作为fallback
- VLM提取流程不变
- CrossValidationAgent和ConsistencyAgent不变
- GUI层不变
- 配置管理不变

## 验证方式
- 运行`python -m pytest tests/ -v`：139个测试全部通过
- 其中新增29个测试（15个schema约束 + 14个LLM提取器）
- 所有现有测试未被破坏

## 风险与后续
- LLM-First提取依赖API可用性，当API不可用时自动降级为规则提取
- few-shot examples目前只有3个动力学示例，后续需要扩展更多纳米酶领域的示例
- self-augmentation会增加一次API调用，可通过`enable_self_augmentation=False`关闭
- 后续可考虑：1) 用纳米酶领域数据fine-tune模型；2) 增加更多few-shot examples；3) 实现constrained decoding（outlines/instructor库）
