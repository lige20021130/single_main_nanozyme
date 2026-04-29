# 提取准确率系统机制改革 Spec

## Why

当前系统在10篇文献测试中，关键字段填充率仅56-74%，核心瓶颈不是正则模式数量不足，而是**数据在流水线中因机制设计缺陷被丢弃**。三大根因：
1. **kinetics bucket严格过滤无fallback** — 句子不含材料名时kinetics证据全部丢失，后续规则和LLM都无法获得数据
2. **OCR修复覆盖面窄且有误伤** — 只处理9种金属双字母错误，复合规则破坏合法化学式
3. **合并策略过于保守** — 差异>10倍就保留规则值，但规则值本身可能来自错误OCR解析

这三项机制改革预计可将关键字段填充率从56%提升至80%+。

## What Changes

- **改革1: kinetics bucket增加fallback机制** — EvidenceBucketBuilder.build中，当kinetics bucket严格过滤后为空时，回退到宽松过滤（与activity bucket同策略），确保kinetics证据不丢失
- **改革2: OCR修复重构** — 扩充金属覆盖范围、修复误伤规则、增加数字/空格OCR修复
- **改革3: 合并策略优化** — 当规则值与LLM值差异>10倍时，增加"规则值是否来自OCR损坏"的判断，而非一律保留规则值
- **改革4: 单位归一化在提取阶段生效** — 当前normalize_unit仅在validate_schema中调用，需在规则提取写入时就归一化

## Impact

- Affected code:
  - `single_main_nanozyme_extractor.py` — EvidenceBucketBuilder.build、_fix_ocr_name、_OCR_FIXES、_OCR_COMPOUND_FIXES、_merge_llm、规则提取各方法
  - `consistency_guard.py` — check_sentence_attribution（无需修改，但需理解其行为）
  - `numeric_validator.py` — normalize_unit（已增强，无需修改）

## ADDED Requirements

### Requirement: kinetics bucket fallback机制

系统SHALL在EvidenceBucketBuilder.build中为kinetics/application/mechanism bucket提供fallback：当严格过滤后bucket为空时，使用与activity/synthesis相同的宽松过滤策略重新填充。

#### Scenario: kinetics句子不含材料名但含kinetics关键词
- **WHEN** 一条句子包含"Km"、"Vmax"等kinetics关键词但不包含selected_name变体
- **AND** check_sentence_attribution返回belongs_to_selected=False（reason="mentions_other_only"）
- **THEN** 该句子在严格过滤阶段被丢弃，但在fallback阶段被重新纳入kinetics bucket
- **AND** diagnostics中记录"kinetics_bucket_fallback_applied"警告

#### Scenario: kinetics句子含"this work"标记
- **WHEN** 一条句子包含"this work"标记且含kinetics关键词
- **THEN** 该句子直接通过严格过滤，无需fallback

### Requirement: OCR修复重构

系统SHALL扩充OCR修复覆盖范围并消除误伤：

#### Scenario: 金属双字母OCR错误
- **WHEN** 候选材料名包含Ce/Ag/Ti/V/Cr/Mo/W/Ru/Rh/Ir/La的双字母OCR错误
- **THEN** 系统正确修复（如"CeeO2"→"CeO2"、"AgnP"→"AgNP"）

#### Scenario: 合法化学式不被误伤
- **WHEN** 候选材料名是"Fe3C"（碳化铁，合法化学式）
- **THEN** 系统不将其修复为"F-3-C"

#### Scenario: 数字OCR错误
- **WHEN** 候选材料名中"O"与"0"混淆（如"Fe2O3"→"Fe2O3"其中O实为0）
- **THEN** 系统根据上下文正确判断

### Requirement: 合并策略智能判断

系统SHALL在_merge_llm中，当规则值与LLM值差异>10倍时，增加规则值可靠性判断：

#### Scenario: 规则值来自OCR损坏的科学计数法
- **WHEN** 规则Km=1.5，LLM Km=1.51e-07
- **AND** 规则值是LLM值的截断前缀
- **THEN** 使用LLM值替换规则值

#### Scenario: 规则值在合理量级范围外
- **WHEN** 规则Vmax=2.68e-07（无单位或单位异常），LLM Vmax=2.68e-05 M/s
- **AND** 规则值不在Vmax合理量级范围(1e-12, 1e6)内
- **THEN** 使用LLM值替换规则值

### Requirement: 单位在提取阶段归一化

系统SHALL在规则提取写入kinetics单位时立即调用normalize_unit，而非仅在validate_schema中统一归一化。

#### Scenario: 规则提取写入Vmax_unit时
- **WHEN** 规则提取从正则匹配获得Vmax_unit="Ms"
- **THEN** 写入record前先调用normalize_unit("Ms")，得到"M/s"后写入

## MODIFIED Requirements

### Requirement: EvidenceBucketBuilder.build过滤策略

原策略：kinetics/application/mechanism bucket使用严格过滤，无fallback
新策略：严格过滤后bucket为空时，使用宽松过滤（与activity同策略）重新填充

### Requirement: _OCR_FIXES和_OCR_COMPOUND_FIXES

原规则：14条OCR_FIXES + 3条OCR_COMPOUND_FIXES
新规则：扩充至25+条OCR_FIXES + 修正OCR_COMPOUND_FIXES消除误伤

### Requirement: _merge_llm中>10倍差异处理

原策略：差异>10倍一律保留规则值，LLM值存为_alternative
新策略：差异>10倍时判断规则值可靠性，不可靠则使用LLM值
