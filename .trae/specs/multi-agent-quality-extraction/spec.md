# 高质量纳米酶文献提取系统多智能体进化 Spec

## Why

当前系统经过多轮优化后，关键字段提取率仍不理想（Vmax~40%、kcat~25%、pH稳定性~20%），且存在**双管线逻辑分裂、合并策略缺陷、归一化不一致**三大架构级问题。核心瓶颈不再是单一正则或校验规则，而是**提取流程缺乏专业化分工和交叉验证机制**。引入多智能体架构，将提取流程拆分为专业化Agent协作，配合交叉验证和一致性保障机制，预计可将关键字段填充率从当前水平提升至70%+，输出一致性达到95%+。

## What Changes

- **改革1: 提取Agent专业化拆分** — 将当前单体RuleExtractor拆分为KineticsAgent、MorphologyAgent、SynthesisAgent、ApplicationAgent四个专业Agent，每个Agent拥有独立的正则库、上下文窗口和验证逻辑
- **改革2: 交叉验证Agent** — 新增CrossValidationAgent，对多源提取结果（规则/LLM/VLM）进行交叉验证，实现多数投票、置信度加权、异常值检测
- **改革3: 一致性保障Agent** — 新增ConsistencyAgent，统一酶类型归一化（消除下划线/连字符双系统）、统一单位输出、统一材料名称格式、全局去重
- **改革4: 双管线统一** — 废弃SingleRecordAssembler独立合并路径，统一由SingleMainNanozymePipeline作为唯一入口，消除逻辑分裂
- **改革5: 诊断与覆盖率追踪** — 扩充WARNING_ENUMS、增加字段级提取率统计、增加正则命中率追踪

## Impact

- Affected code:
  - `single_main_nanozyme_extractor.py` — RuleExtractor拆分、_merge_llm/_merge_vlm重构、双管线统一
  - `single_record_assembler.py` — **BREAKING** 废弃独立合并路径，仅保留数据结构定义
  - `numeric_validator.py` — resolve_kinetics增加多候选交叉验证
  - `nanozyme_models.py` — 酶类型归一化统一为连字符格式
  - `activity_selector.py` — 酶类型归一化统一，消除下划线格式
  - `consistency_guard.py` — 增加跨字段一致性检查
  - `diagnostics_builder.py` — 扩充WARNING_ENUMS、增加覆盖率统计
  - `application_extractor.py` — substrate/analyte区分增强

## ADDED Requirements

### Requirement: 提取Agent专业化拆分

系统SHALL将RuleExtractor拆分为四个专业Agent，每个Agent独立负责一个提取域。

#### Scenario: KineticsAgent提取动力学参数
- **WHEN** 文献包含 "Km = 0.15 mM" 和 "Vmax = 3.0 × 10⁻⁸ M/s"
- **THEN** KineticsAgent独立提取Km=0.15、Km_unit="mM"、Vmax=3.0e-8、Vmax_unit="M/s"
- **AND** 返回结构包含confidence_score和evidence_text

#### Scenario: MorphologyAgent提取形貌参数
- **WHEN** 文献包含 "TEM image showed spherical nanoparticles with diameter of 50 nm"
- **THEN** MorphologyAgent提取morphology="spherical"、size=50、size_unit="nm"
- **AND** 返回结构包含confidence_score和evidence_text

#### Scenario: SynthesisAgent提取合成信息
- **WHEN** 文献包含 "hydrothermal method at 180°C for 12 h using FeCl3 and NaOH"
- **THEN** SynthesisAgent提取synthesis_method="hydrothermal"、temperature="180°C"、time="12h"、precursors=["FeCl3","NaOH"]
- **AND** 联合提取温度-时间-前驱体，避免碎片化

#### Scenario: ApplicationAgent提取应用信息
- **WHEN** 文献包含 "detection of H2O2 with LOD of 0.5 μM"
- **THEN** ApplicationAgent提取application_type="biosensing"、target_analyte="H2O2"、detection_limit="0.5 μM"
- **AND** 区分substrate和target_analyte（H2O2作为底物时不误标为analyte）

### Requirement: 交叉验证Agent

系统SHAL新增CrossValidationAgent，对多源提取结果进行交叉验证。

#### Scenario: 多数投票——规则与LLM值接近
- **WHEN** 规则提取Km=0.15 mM，LLM提取Km=0.20 mM（差异33%）
- **THEN** CrossValidationAgent标记两者为"consistent"，取规则值（来源优先级更高）
- **AND** confidence_score="high"

#### Scenario: 异常值检测——规则与LLM值差异大
- **WHEN** 规则提取Vmax=2.68（OCR截断），LLM提取Vmax=2.68e-7 M/s
- **THEN** CrossValidationAgent检测到规则值是LLM值的截断前缀
- **AND** 使用LLM值，标记confidence_score="medium"、needs_review=True

#### Scenario: 三源交叉验证
- **WHEN** 规则提取Km=0.15，LLM提取Km=0.15，VLM提取Km=0.14
- **THEN** CrossValidationAgent确认三源一致，confidence_score="high"
- **AND** 取规则值作为最终值

#### Scenario: 冲突无法解决
- **WHEN** 规则提取Km=0.15 mM，LLM提取Km=1.5 mM（差异10倍），VLM无数据
- **THEN** CrossValidationAgent标记为"conflict"，保留规则值
- **AND** LLM值存入_alternative，confidence_score="low"、needs_review=True

### Requirement: 一致性保障Agent

系统SHALL新增ConsistencyAgent，确保输出格式统一。

#### Scenario: 酶类型归一化统一
- **WHEN** 不同模块产生enzyme_like_type="peroxidase_like"和"peroxidase-like"
- **THEN** ConsistencyAgent统一为"peroxidase-like"格式（连字符）
- **AND** 消除activity_selector.py的下划线格式和nanozyme_models.py的连字符格式双系统

#### Scenario: 单位输出统一
- **WHEN** kinetics中Km_unit="mM·s⁻¹"或"mM s-1"
- **THEN** ConsistencyAgent统一为"mM/s"格式
- **AND** 所有单位字段在最终输出前经过统一归一化

#### Scenario: 材料名称格式统一
- **WHEN** selected_nanozyme.name="Fe3O4 nanoparticles"或"Fe3O4 NPs"
- **THEN** ConsistencyAgent统一为"Fe3O4"（去除冗余后缀）
- **AND** 后缀列表：nanoparticles/NPs/nanosheets/nanocubes/nanorods/nanozyme等

#### Scenario: 应用去重
- **WHEN** 规则和LLM分别提取了相同的应用（application_type="biosensing", target_analyte="H2O2"）
- **THEN** ConsistencyAgent合并为一条，保留信息更完整的版本
- **AND** 去重键为(application_type, target_analyte)二元组

#### Scenario: 跨字段一致性检查
- **WHEN** enzyme_like_type="catalase-like"但optimal_pH=3.0
- **THEN** ConsistencyAgent标记warning="catalase_like_low_pH"，needs_review=True
- **AND** 检查Km单位是否为浓度单位、Vmax单位是否为速率单位、kcat与Km量级合理性

### Requirement: 双管线统一

系统SHALL废弃SingleRecordAssembler的独立合并路径，统一由SingleMainNanozymePipeline作为唯一入口。

#### Scenario: 统一入口
- **WHEN** 外部调用extract()方法
- **THEN** 仅通过SingleMainNanozymePipeline.extract()执行
- **AND** SingleRecordAssembler仅保留数据结构定义辅助方法，不再有独立合并逻辑

#### Scenario: VLM合并死代码修复
- **WHEN** _merge_vlm()中Km冲突检测条件record["main_activity"]["kinetics"].get("Km") is not None在Km为None时永远不成立
- **THEN** 修复条件逻辑，使VLM值能正确填充空值
- **AND** VLM的sensing_performance（LOD/linear_range）参与applications构建

### Requirement: 诊断与覆盖率追踪

系统SHALL扩充诊断系统，增加字段级覆盖率追踪。

#### Scenario: WARNING_ENUMS扩充
- **WHEN** NumericValidator产生"Km_unit_not_concentration"警告
- **THEN** 该警告出现在diagnostics.warnings中（当前被过滤掉）
- **AND** WARNING_ENUMS包含所有模块产生的警告类型

#### Scenario: 字段级提取率统计
- **WHEN** 系统完成一次提取
- **THEN** diagnostics中包含field_coverage字典，记录每个字段的提取状态（extracted/missing/default）
- **AND** 包含regex_hit_stats字典，记录每个正则模式的命中次数

#### Scenario: 提取率报告
- **WHEN** 批量处理N篇文献后
- **THEN** 可生成提取率汇总报告，按字段统计提取率百分比
- **AND** 识别系统性低提取率字段，给出改进建议

## MODIFIED Requirements

### Requirement: RuleExtractor架构

原架构：单体RuleExtractor类包含所有正则模式和提取逻辑（~1500行）
新架构：拆分为KineticsAgent、MorphologyAgent、SynthesisAgent、ApplicationAgent四个专业Agent，每个Agent独立维护正则库

### Requirement: _merge_llm合并策略

原策略：规则值优先，LLM仅填充空值，差异>50%保留规则值
新策略：通过CrossValidationAgent交叉验证，支持多数投票、截断检测、量级合理性判断

### Requirement: _merge_vlm合并策略

原策略：VLM值写入important_values和kinetics，冲突时保留规则值
新策略：VLM值参与CrossValidationAgent三源交叉验证，sensing_performance参与applications构建

### Requirement: 酶类型归一化

原系统：activity_selector.py使用下划线格式（peroxidase_like），nanozyme_models.py使用连字符格式（peroxidase-like）
新系统：统一为连字符格式（peroxidase-like），由ConsistencyAgent在最终输出时保障

### Requirement: NumericValidator.resolve_kinetics

原策略：按来源优先级取第一个通过验证的候选
新策略：收集所有通过验证的候选，交由CrossValidationAgent交叉验证后选择最优值

### Requirement: DiagnosticsBuilder.WARNING_ENUMS

原枚举：12种警告类型
新枚举：扩充至包含所有模块产生的警告类型（预计25+种）

## REMOVED Requirements

### Requirement: SingleRecordAssembler独立合并路径
**Reason**: 双管线导致逻辑分裂和输出不一致
**Migration**: SingleRecordAssembler仅保留数据结构定义辅助方法，合并逻辑统一到SingleMainNanozymePipeline
