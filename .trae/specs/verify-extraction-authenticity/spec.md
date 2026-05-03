# 纳米酶文献提取信息真实性验证系统 Spec

## Why

当前系统存在严重的**信息真实性盲区**：LLM/VLM 提取结果可能包含大模型捏造的数值、模糊推断的结论、以及跨材料/跨上下文的信息错配。现有验证机制（NumericValidator、ConsistencyGuard、CrossValidationAgent）仅关注数值量级合理性和归属判断，**无法验证提取值是否真正存在于原文中**。需要一个专门的验证层，确保每条提取信息都可溯源到原文具体位置，杜绝大模型幻觉和模糊处理。

## What Changes

- **新增1: 证据锚定机制（Evidence Anchoring）** — 每个提取字段必须绑定原文证据片段（evidence_text）和位置标记（sentence_id / page），无证据的字段标记为 `unverified`
- **新增2: LLM/VLM 输出反幻觉验证（Anti-Hallucination Verification）** — 对 LLM/VLM 提取的每个数值型字段，在原文中搜索匹配验证；无法在原文中找到对应数值的字段降级为 `needs_review=True, source="llm_unverified"`
- **新增3: 信息错配检测（Cross-Context Mismatch Detection）** — 检测提取结果中不同字段是否来自原文中不同材料/不同实验条件，防止信息混杂
- **新增4: 验证报告生成（Verification Report）** — 在 diagnostics 中新增 `verification` 子结构，记录每个字段的验证状态（verified / unverified / mismatched / hallucination_suspect）

## Impact

- Affected code:
  - `single_main_nanozyme_extractor.py` — 提取流程中增加证据锚定步骤，_merge_llm/_merge_vlm 增加反幻觉验证
  - `llm_extractor.py` — LLM 提取结果增加 evidence_text 必填校验
  - `vlm_extractor.py` — VLM 提取结果增加 evidence_text 和位置信息
  - `cross_validation_agent.py` — 增加反幻觉验证逻辑
  - `consistency_guard.py` — 增加跨上下文错配检测
  - `diagnostics_builder.py` — 增加 verification 子结构和相关 WARNING_ENUMS
  - `nanozyme_models.py` — 数据模型增加 verification_status 字段

## ADDED Requirements

### Requirement: 证据锚定机制

系统SHALL为每个提取字段绑定原文证据，确保信息可溯源。

#### Scenario: 动力学参数证据锚定
- **WHEN** 规则提取到 Km=0.15 mM
- **THEN** 该字段必须附带 evidence_text（包含该值的原文片段）和 source（text/table/figure_caption）
- **AND** 如果无法提供 evidence_text，字段标记 verification_status="unverified"

#### Scenario: LLM 提取结果证据锚定
- **WHEN** LLM 提取到 Vmax=3.2e-8 M/s
- **THEN** 该字段必须附带 evidence_text（LLM 返回的原文片段引用）
- **AND** 如果 LLM 返回中无 evidence_text，该值标记 verification_status="llm_no_evidence"

#### Scenario: 应用信息证据锚定
- **WHEN** 提取到 application_type="biosensing", target_analyte="H2O2", detection_limit="0.5 μM"
- **THEN** 每个非空值字段都应有 evidence_text 指向原文
- **AND** detection_limit 必须附带原文中包含该数值的句子

### Requirement: LLM/VLM 输出反幻觉验证

系统SHALL对 LLM/VLM 提取的数值型字段在原文中进行回查验证，检测大模型幻觉。

#### Scenario: 数值回查验证——匹配成功
- **WHEN** LLM 提取 Km=0.15 mM，evidence_text="The Km value was determined to be 0.15 mM"
- **AND** 在原文 text_chunks 中搜索到包含 "0.15" 的句子
- **THEN** 标记 verification_status="verified", confidence="high"

#### Scenario: 数值回查验证——数值不在原文中
- **WHEN** LLM 提取 Km=0.15 mM，但在原文 text_chunks 中搜索不到 "0.15" 或近似值
- **THEN** 标记 verification_status="hallucination_suspect", needs_review=True
- **AND** 将该值降级存入 important_values，kinetics 中 Km 设为 None
- **AND** diagnostics.verification 中记录 "Km_hallucination_suspect"

#### Scenario: 数值回查验证——近似值匹配
- **WHEN** LLM 提取 Km=0.15 mM，原文中为 "Km = 1.5 × 10⁻¹ mM"（科学计数法）
- **THEN** 系统将 1.5 × 10⁻¹ 归一化为 0.15，匹配成功
- **AND** 标记 verification_status="verified"

#### Scenario: VLM 提取值回查
- **WHEN** VLM 从图中提取 Km=0.23 mM
- **AND** 原文 figure caption 或正文中无该值
- **THEN** 标记 verification_status="vlm_unverified", needs_review=True
- **AND** 保留该值但 confidence="low"

#### Scenario: 文本型字段反幻觉验证
- **WHEN** LLM 提取 enzyme_like_type="peroxidase-like"
- **AND** 原文中确实包含 "peroxidase" 相关描述
- **THEN** 标记 verification_status="verified"
- **WHEN** LLM 提取 synthesis_method="hydrothermal"
- **AND** 原文中无 "hydrothermal" 或相关词
- **THEN** 标记 verification_status="hallucination_suspect"

### Requirement: 信息错配检测

系统SHAL检测提取结果中不同字段是否来自原文中不同材料或不同实验条件，防止信息混杂。

#### Scenario: 动力学参数与材料错配
- **WHEN** Km 值来自原文中描述材料 A 的段落，Vmax 值来自描述材料 B 的段落
- **AND** 材料 A 和材料 B 是不同候选材料
- **THEN** 标记 verification_status="cross_material_mismatch"
- **AND** diagnostics.verification 中记录 "kinetics_cross_material_mismatch"

#### Scenario: 实验条件错配
- **WHEN** Km 的 evidence_text 表明实验条件为 pH=7.0
- **AND** Vmax 的 evidence_text 表明实验条件为 pH=3.0
- **THEN** 标记 verification_status="condition_mismatch"
- **AND** diagnostics.verification 中记录 "kinetics_condition_mismatch"
- **AND** needs_review=True

#### Scenario: 应用与酶活类型错配
- **WHEN** 提取的 enzyme_like_type="catalase-like"
- **AND** application 中 detection_limit 的 evidence_text 描述的是 peroxidase-like 反应体系
- **THEN** 标记 verification_status="activity_application_mismatch"
- **AND** diagnostics.verification 中记录 "activity_application_mismatch"

### Requirement: 验证报告生成

系统SHAL在 diagnostics 中生成 verification 子结构，记录每个字段的验证状态。

#### Scenario: 验证报告结构
- **WHEN** 提取流程完成
- **THEN** diagnostics 中包含 verification 字典，结构为：
  ```
  verification: {
    "field_status": {
      "kinetics.Km": "verified",
      "kinetics.Vmax": "hallucination_suspect",
      "kinetics.kcat": "unverified",
      "enzyme_like_type": "verified",
      "applications[0].detection_limit": "verified",
    },
    "hallucination_suspects": ["kinetics.Vmax"],
    "mismatches": [],
    "unverified_fields": ["kinetics.kcat"],
    "overall_verification_rate": 0.75,
  }
  ```

#### Scenario: 整体验证率计算
- **WHEN** 提取结果中 8 个非空字段有 6 个 verified、1 个 unverified、1 个 hallucination_suspect
- **THEN** overall_verification_rate = 6/8 = 0.75
- **AND** confidence 根据 verification_rate 调整：rate>=0.8 → high, 0.5-0.8 → medium, <0.5 → low

#### Scenario: 验证率影响最终 confidence
- **WHEN** verification_rate < 0.5
- **THEN** diagnostics.confidence 强制降为 "low"
- **AND** diagnostics.needs_review 强制为 True

## MODIFIED Requirements

### Requirement: LLM 提取结果结构

原结构：LLM 返回的 kinetics 可无 evidence_text
新结构：LLM 返回的每个 kinetics 条目必须包含 evidence_text，否则在合并时标记为 unverified

### Requirement: _merge_llm 合并策略

原策略：LLM 值直接补充规则空值
新策略：LLM 值先经过反幻觉验证，验证通过后才补充；未通过的降级为 important_values

### Requirement: _merge_vlm 合并策略

原策略：VLM 值直接补充规则空值
新策略：VLM 值先经过回查验证，验证通过后才补充；未通过的保留但标记 needs_review=True, confidence="low"

### Requirement: DiagnosticsBuilder.WARNING_ENUMS

原枚举：约30种警告类型
新枚举：增加 hallucination_suspect、vlm_unverified、cross_material_mismatch、condition_mismatch、activity_application_mismatch、llm_no_evidence

### Requirement: diagnostics 输出结构

原结构：diagnostics 包含 status、confidence、needs_review、warnings
新结构：增加 verification 子结构（field_status、hallucination_suspects、mismatches、unverified_fields、overall_verification_rate）

## REMOVED Requirements

无删除项。
