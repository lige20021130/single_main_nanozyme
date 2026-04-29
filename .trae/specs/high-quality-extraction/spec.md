# 高质量纳米酶文献提取系统进化 Spec

## Why

当前系统在10篇真实文献验证中，关键字段填充率远未达标：Km=25%、Vmax=0%、kcat_Km=12%、LOD=38%。核心瓶颈不是正则模式不足，而是**三层机制缺陷叠加**：(1) NumericValidator 过于严格的校验逻辑系统性拒绝有效值；(2) 候选材料选择准确率不足（生物酶/细胞系误选、复合材料拆分错误）；(3) LLM/VLM 提取结果与规则提取的合并策略不够智能，导致高价值补充数据被丢弃。三项改革预计可将关键字段填充率从当前水平提升至60%+。

## What Changes

- **改革1: NumericValidator 校验策略放宽** — 放宽量级范围下限、Lineweaver-Burk 数据从硬性拒绝改为 needs_review 标记、figure_candidate 来源从硬性拒绝改为 needs_review、扩充单位集合覆盖
- **改革2: 候选材料选择准确率提升** — 扩展生物酶/细胞系/培养基排除列表、增加复合材料拆分逻辑（如 MoS2@CoFe2O4 → 主材料 CoFe2O4）、增加候选材料与酶活类型的关联性评分
- **改革3: LLM/规则合并策略智能化** — 规则值为 None 时直接采用 LLM 值（不再要求量级一致性）、LLM 提供了规则未提取的字段时自动补充、合并时保留信息来源标记
- **改革4: 输出一致性保障** — 统一单位输出格式、统一酶类型命名规范、统一材料名称格式（去除冗余前后缀）

## Impact

- Affected code:
  - `numeric_validator.py` — validate_kinetics_entry、_MAGNITUDE_RANGES、CONCENTRATION_UNITS/RATE_UNITS 集合
  - `single_main_nanozyme_extractor.py` — CandidateRecaller、_merge_llm、NanozymeScorer、_REAGENT_NAMES
  - `single_record_assembler.py` — 记录组装逻辑
  - `nanozyme_models.py` — 酶类型归一化

## ADDED Requirements

### Requirement: NumericValidator 校验策略放宽

系统SHALL放宽动力学参数校验策略，减少有效值被系统性拒绝的情况。

#### Scenario: kcat 下限放宽
- **WHEN** 提取到 kcat=0.0005 s⁻¹（低于当前下限 1e-3）
- **THEN** 系统接受该值，标记 needs_review=True
- **AND** 不再返回 None

#### Scenario: kcat_Km 下限放宽
- **WHEN** 提取到 kcat_Km=0.05 M⁻¹s⁻¹（低于当前下限 1e0）
- **THEN** 系统接受该值，标记 needs_review=True

#### Scenario: Lineweaver-Burk 数据不再硬性拒绝
- **WHEN** 动力学数据来源文本包含 "Lineweaver-Burk" 关键词
- **THEN** 系统接受该值，标记 needs_review=True，而非返回 None

#### Scenario: figure_candidate 来源不再硬性拒绝
- **WHEN** 动力学数据来源为 figure_candidate
- **THEN** 系统接受该值，标记 needs_review=True，而非返回 None

#### Scenario: 单位集合扩充
- **WHEN** Vmax 单位为 "M/h" 或 "mM/h"
- **THEN** normalize_unit 将其归一化到 RATE_UNITS 集合中的标准形式

### Requirement: 候选材料选择准确率提升

系统SHALL提升候选材料选择的准确率，减少误选和漏选。

#### Scenario: 复合材料拆分
- **WHEN** 文献标题包含 "MoS2@CoFe2O4" 或 "Fe-N-C" 等复合结构
- **THEN** 系统将复合名称拆分为子组件，分别作为候选材料
- **AND** 优先选择包含金属元素的子组件作为主材料

#### Scenario: 候选材料与酶活类型关联评分
- **WHEN** 候选材料在 kinetics/activity bucket 中被频繁提及
- **AND** 该候选材料与检测到的酶活类型在同一句子中共现
- **THEN** 该候选材料的评分获得额外加分

#### Scenario: 排除列表扩展
- **WHEN** 候选材料名为 "RPMI-1640" 或 "DMEM" 等培养基名称
- **THEN** 系统将其排除，不作为候选材料

### Requirement: LLM/规则合并策略智能化

系统SHALL在合并规则提取和LLM提取结果时采用更智能的策略。

#### Scenario: 规则值为 None 时直接采用 LLM 值
- **WHEN** 规则提取的 Km=None，LLM 提取的 Km=0.35
- **THEN** 直接采用 LLM 值，无需量级一致性检查

#### Scenario: LLM 补充规则未提取的字段
- **WHEN** 规则提取了 Km 但未提取 Vmax，LLM 提取了 Vmax=3.2e-8
- **THEN** 将 LLM 的 Vmax 值补充到 kinetics 中

#### Scenario: 信息来源标记
- **WHEN** 合并后的字段来自 LLM 提取
- **THEN** kinetics.source 标记为 "llm_supplement"

### Requirement: 输出一致性保障

系统SHALL确保输出的纳米酶信息格式一致。

#### Scenario: 单位输出格式统一
- **WHEN** Km_unit 为 "mM·s⁻¹" 或 "mM s-1" 等变体
- **THEN** 统一输出为 "mM/s" 格式

#### Scenario: 酶类型命名统一
- **WHEN** enzyme_like_type 为 "peroxidase (POD)-like" 或 "POD-like"
- **THEN** 统一输出为 "peroxidase-like"

#### Scenario: 材料名称格式统一
- **WHEN** selected_nanozyme.name 为 "Fe3O4 nanoparticles" 或 "Fe3O4 NPs"
- **THEN** 统一输出为 "Fe3O4"（去除冗余后缀）

## MODIFIED Requirements

### Requirement: NumericValidator 量级范围

原范围：
- Km: [1e-9, 1.0]
- Vmax: [1e-12, 1e6]
- kcat: [1e-3, 1e8]
- kcat_Km: [1e0, 1e10]

新范围：
- Km: [1e-12, 10.0]
- Vmax: [1e-15, 1e8]
- kcat: [1e-6, 1e10]
- kcat_Km: [1e-3, 1e12]

超出原范围但在新范围内的值标记 needs_review=True。

### Requirement: Lineweaver-Burk 数据处理

原策略：包含 Lineweaver-Burk 关键词的动力学数据一律硬性拒绝
新策略：标记 needs_review=True，保留数据

### Requirement: figure_candidate 来源处理

原策略：figure_candidate 来源的动力学数据一律硬性拒绝
新策略：标记 needs_review=True，保留数据

### Requirement: _REAGENT_NAMES 排除列表

原列表：HRP, GOx, SOD, CAT + 少量新增
新列表：扩展至包含所有常见生物酶、细胞系、培养基、细菌名称

## REMOVED Requirements

无删除项。
