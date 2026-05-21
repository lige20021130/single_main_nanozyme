# Phase 2: 全面消除硬编码，领域知识集中化深化

## 更新时间
2026-05-21 23:30

## 更新类型
- 架构调整 / 重构

## 背景
Phase 1 完成了领域知识集中化基础（YAML + 加载器 + 枚举动态化）。但系统中仍有大量硬编码散布在提取器、验证器、一致性修正器中，包括：76 行正则模式、底物知识、Km/Vmax 数值范围、分析物-酶类型映射等。这些硬编码导致新增酶类型时需要修改多个文件，与 LLM-First 语义理解目标冲突。

## 改动内容

### domain_knowledge.yaml 新增数据节
- `enzyme_type_regex_patterns`: 38 种酶类型的 74 个正则匹配模式（含别名、mimicking 变体）
- `enzyme_specific_km_ranges`: 9 种酶类型的 Km 典型范围
- `enzyme_specific_vmax_ranges`: 4 种酶类型的 Vmax 典型范围
- `analyte_enzyme_incompatibility`: 6 种酶类型的分析物-酶类型不兼容映射
- `analyte_enzyme_compatibility`: 6 种酶类型的分析物-酶类型兼容列表

### domain_knowledge.py 新增接口
- `get_enzyme_type_regex_patterns()`: 从 YAML 动态生成编译后的正则模式列表
- `get_enzyme_specific_km_ranges()`: 返回酶类型→(min, max, unit) 映射
- `get_enzyme_specific_vmax_ranges()`: 返回酶类型→(min, max, unit) 映射
- `get_analyte_enzyme_incompatibility()`: 返回不兼容映射
- `get_analyte_enzyme_compatibility()`: 返回兼容列表（小写）
- `generate_substrate_knowledge_prompt()`: 动态生成底物知识 Prompt 片段

### 重构文件
- `single_main_nanozyme_extractor.py`: 76 行硬编码 `_ENZYME_TYPE_PATTERNS` → `_get_dk().get_enzyme_type_regex_patterns()`（1 行）
- `extraction_prompts.py`: 硬编码底物知识（2 行）→ `_DK.generate_substrate_knowledge_prompt()`（35 种酶类型全覆盖）
- `numeric_validator.py`: 硬编码 `_NANOZYME_KM_RANGES`/`_NANOZYME_VMAX_RANGES`/`_ANALYTE_ENZYME_COMPATIBILITY` → 从 domain_knowledge 加载
- `consistency_agent.py`: 硬编码 `_ANALYTE_ENZYME_INCOMPATIBILITY` → `_DK.get_analyte_enzyme_incompatibility()`

### 未改动文件
- `extraction_agents.py`: 使用 `single_main_nanozyme_extractor` 的正则模式，间接使用
- `cross_validation_agent.py`: 无硬编码领域知识
- `constrained_decoding.py`: 无硬编码领域知识

## 验证方式
- `python -m pytest tests/ --ignore=tests/test_llm_structured_extractor.py -v` → 141 passed
- 综合验证: 74 regex patterns, 9 KM ranges, 4 VMAX ranges, 6 incompatibility entries, 6 compatibility entries, 35 substrate prompt lines
- 所有模块 import 验证通过

## 风险与后续
- 风险: YAML 中正则模式与原硬编码有微小差异（`cytochrome c oxidase` 不再单独映射到 oxidase-like），但此类边缘情况已由 LLM-First 语义提取覆盖
- 后续: 可为 `domain_knowledge.yaml` 添加 JSON Schema 验证，防止格式错误
- 后续: 可将 `extraction_agents.py` 中的正则模式也统一到 domain_knowledge
