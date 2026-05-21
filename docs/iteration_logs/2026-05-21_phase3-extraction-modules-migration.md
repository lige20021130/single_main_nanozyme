# Phase 3: 提取模块硬编码全面迁移到领域知识中心

## 更新时间
2026-05-21 23:55

## 更新类型
- 架构调整 / 重构

## 背景
Phase 2 完成了核心提取器/验证器/一致性修正器的硬编码消除。但提取管道中仍有多个模块包含大量硬编码领域知识：application_extractor 有 150+ 行应用类型/方法/样品/分析物正则和集合，activity_selector 有硬编码酶类型集合，figure_handler 有硬编码图标题分类正则，extraction_agents 有硬编码机制正则和酶类型列表。这些硬编码导致新增应用类型或酶类型时需要手动修改多个文件。

## 改动内容

### domain_knowledge.yaml 新增数据节
- `application_type_regex_patterns`: 13 种应用类型的 73 个正则模式
- `method_regex_patterns`: 4 种检测方法的正则
- `sample_type_regex_patterns`: 9 种样品类型的正则
- `known_analytes`: 46 个已知分析物
- `invalid_analyte_phrases`: 6 个无效分析物描述
- `figure_caption_patterns`: 3 类图标题（kinetics/application/morphology）的 21 个正则
- `mechanism_regex_patterns`: 8 个催化机制识别正则

### domain_knowledge.py 新增接口
- `get_application_type_regex_patterns()`: 返回编译后的应用类型正则映射
- `get_method_regex_patterns()`: 返回编译后的方法正则映射
- `get_sample_type_regex_patterns()`: 返回编译后的样品类型正则映射
- `get_known_analytes()`: 返回已知分析物集合
- `get_invalid_analyte_phrases()`: 返回无效分析物描述集合
- `get_figure_caption_patterns()`: 返回图标题分类正则映射
- `get_mechanism_regex_patterns()`: 返回机制识别正则列表
- `get_enzyme_type_short_names()`: 返回酶类型短名列表（用于动态生成 Km/Vmax 提取正则）
- `get_probe_molecules()`: 返回探针分子集合

### 重构文件
- `application_extractor.py`: 150+ 行硬编码 → 10 行从 domain_knowledge 加载（APPLICATION_TYPE_PATTERNS/METHOD_PATTERNS/SAMPLE_TYPE_PATTERNS/KNOWN_SUBSTRATES/KNOWN_ANALYTES/PROBE_MOLECULES/INVALID_ANALYTE_PHRASES）
- `activity_selector.py`: 6 行硬编码 VALID_ENZYME_TYPES → 1 行从 domain_knowledge 动态生成
- `figure_handler.py`: 18 行硬编码 CAPTION_PATTERNS → 4 行从 domain_knowledge 加载
- `extraction_agents.py`: 8 行硬编码 _FULLTEXT_MECHANISM_PATTERNS → 1 行从 domain_knowledge 加载；4 行硬编码酶类型列表 → 动态生成

### 设计决策
- 算法型正则（如 _MULTI_KM_PATTERNS、_SPECIFIC_ACTIVITY_PATTERNS）不迁移：这些是提取算法本身，不是领域知识
- 领域知识型正则（如应用类型分类、机制识别、图标题分类）迁移：这些是分类规则，属于领域知识

## 验证方式
- `python -m pytest tests/ --ignore=tests/test_llm_structured_extractor.py -v` → 141 passed
- 综合验证: 13 app types, 73 app patterns, 4 methods, 9 sample types, 46 analytes, 6 invalid phrases, 23 probes, 3 caption categories, 8 mechanism patterns
- 功能验证: classify_application_type/extract_method/extract_sample_type 全部正确

## 风险与后续
- 风险: _ENZYME_TYPE_KM_PATTERNS 动态生成后，短名列表可能包含新增的酶类型别名，需要确保正则匹配不会过于宽泛
- 后续: 可将 single_main_nanozyme_extractor.py 中的 _KM_PATTERNS/_VMAX_PATTERNS 等核心提取正则也迁移到 YAML（但需谨慎，这些是算法核心）
- 后续: 可为 YAML 数据节添加 JSON Schema 验证
