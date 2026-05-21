# 领域知识集中化 + Rule→Validator 升级

## 更新时间
2026-05-21 22:00

## 更新类型
- 架构调整 / 重构

## 背景
纳米酶领域知识（酶类型、应用类型、底物、探针分子、数值范围等）散布在多个代码文件中硬编码，导致维护困难、一致性差、扩展受限。Rule 层的 Km/Vmax 提取逻辑会覆盖 LLM 已提取的结果，与 LLM-First 架构目标冲突。

## 改动内容

### 新增文件
- `domain_knowledge.yaml`：领域知识单一真相源，包含 38 种酶类型、9 种应用类型、17 种探针分子、底物映射、数值范围、单位转换等
- `domain_knowledge.py`：领域知识加载器，提供统一接口（别名映射、枚举值、Prompt 片段生成等），单例模式
- `tests/test_domain_knowledge.py`：加载器 11 项单元测试

### 重构文件
- `nanozyme_models.py`：`_ENZYME_ALIAS_MAP`、`_APPLICATION_TYPE_ALIAS_MAP`、`EnzymeType` 枚举、`ApplicationType` 枚举、`ENZYME_REGISTRY` 全部改为从 `domain_knowledge` 动态加载
- `schema_constraints.py`：`_ENZYME_TYPE_ENUM`、`_APPLICATION_TYPE_ENUM` 改为从 `domain_knowledge` 加载
- `single_main_nanozyme_extractor.py`：
  - `_SUBSTRATE_KEYWORDS` 硬编码集合替换为 `domain_knowledge.get_all_substrates()`
  - `_extract_kinetics_from_text` 中 Km/Vmax 提取条件从 `is None or best[0] < 5` 改为 `is None`，Rule 层不再覆盖 LLM 结果
- `material_identifier.py`：`PROBE_MOLECULES` 硬编码集合替换为 `domain_knowledge.get_probe_molecule_names()`

### 未改动文件
- `extraction_prompts.py`：已通过 `schema_constraints.get_enzyme_type_enum_string()` 间接使用加载器，无需修改
- `extraction_agents.py`、`numeric_validator.py`、`consistency_agent.py` 等验证层模块未改动
- `constrained_decoding.py` 未改动

## 验证方式
- `python -m pytest tests/test_domain_knowledge.py tests/test_enzyme_type_normalization.py -v` → 92 passed
- `python -m pytest tests/ --ignore=tests/test_llm_structured_extractor.py -v` → 141 passed
- `test_llm_structured_extractor.py` 中 3 个失败是已有问题（schema 验证 `selected_nanozyme.name is required`），与本次改动无关
- 核心模块 import 验证通过：EnzymeType=38, ApplicationType=9, PROBE_MOLECULES=23, Substrates=77

## 风险与后续
- 风险：`EnzymeType` 枚举成员名从 `PEROXIDASE` 变为 `PEROXIDASE_LIKE`，但代码中只使用 `.value` 和 `.normalize_canonical()`，不受影响
- 后续：Phase 2 可将 `domain_knowledge.yaml` 中的底物和探针分子信息注入 `extraction_prompts.py` 的 Prompt 模板，实现完全动态化
- 后续：可添加 `domain_knowledge.yaml` 的 JSON Schema 验证，防止格式错误
