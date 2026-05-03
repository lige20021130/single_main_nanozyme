# 5项精进：正则回退、VLM去重、动态校准、no_evidence交叉确认

## 更新时间
2026-05-03 23:20

## 更新类型
- 功能开发 / Bug 修复 / 架构调整

## 背景
基于前一次代码审查，用户提出5个精进方向。经系统化调试逐项根因调查，确认其中4个为真实缺口，1个（CrossValidationAgent加权投票）已隐式实现。

## 改动内容

### Fix 1: RuleExtractor 正则→Verifier 回退 + LanguageRuleAdapter
**文件**: `single_main_nanozyme_extractor.py`
- 新增 `_verifier_assisted_extract()` 方法：正则提取失败的 kinetics 字段，用数值搜索在全文扫描候选值，按评分（单位匹配+材料匹配+关键词匹配）选取最优
- 新增 `LanguageRuleAdapter` 类：预留中英文扩展接口，含 `_zh_patterns()` 中文正则模板
- 新增辅助函数：`_extract_all_numbers_from_source()`, `_guess_unit_from_snippet()`
- 新增常量：`_KM_RANGES`, `_PARAM_KEYWORDS`, `_UNIT_HINTS`

### Fix 2: VLM 图片去重
**文件**: `single_main_nanozyme_extractor.py`
- 新增 `_deduplicate_vlm_tasks()` 方法：基于 caption + description 词集 Jaccard 相似度（>0.7 + ≥3 共有词→去重），保留高 priority 任务
- 在 `_call_vlm()` 的 priority 排序后、extraction 循环前调用

### Fix 3: NumericValidator 动态校准
**文件**: `numeric_validator.py`, `single_main_nanozyme_extractor.py`
- 新增 `calibrate_magnitude_ranges()` 函数：扫描全文浓度值，推算 paper 典型浓度量级，动态调整 review 范围
- `NumericValidator` 新增 `set_paper_context()`, `_get_adjusted_review_range()` 方法
- `validate_kinetics_entry()` 增加纸制浓度上下文异常检测
- `extract()` 方法中在 validate 前调用校准

### Fix 4: VLM no_evidence 三方交叉确认
**文件**: `single_main_nanozyme_extractor.py`
- 新增 `_cross_verify_vlm_no_evidence()` 方法：对 `_vlm_no_evidence=True` 的 VLM 值，交叉对比 rule/LLM 值
- 有至少一个相符 → 置信度提升，记录到 important_values（needs_review=False）
- 完全孤立无佐证 → 降级，值移到 important_values，kinetics 字段清空

### Fix 5: CrossValidationAgent 加权投票
**结论**: 不修改。现有 `merge_results()` 已通过 source priority（rule>VLM>LLM）隐式实现加权，代码逻辑清晰。

## 未改动内容
- `extraction_verifier.py` 未改动（Verifier 回退逻辑加在 RuleExtractor 内部）
- `consistency_guard.py` 未改动
- `cross_validation_agent.py` 未改动（加权投票已够用）
- `diagnostics_builder.py` 未改动
- LLM/VLM System Prompt 未改动

## 验证方式
- 全部模块 import 成功
- `calibrate_magnitude_ranges()` 功能测试通过：
  - mM量级 paper → Km review 上限 1.5M（而非默认 1.0M）
  - 50M Km 被正确 REJECT
  - 0.15M Km 正常通过

## 风险与后续
- Verifier 回退依赖 `_extract_all_numbers_from_source` 的召回率，极端格式（如分数 "1/4 mM"）可能漏网
- VLM 去重用 Jaccard 相似度而非图像 hash，存在 hash collision 反面风险（不同图相似 caption 被错误去重）
- 动态校准依赖 paper 内浓度标注完整性，无浓度标注的 paper 回退默认范围
- 建议后续收集 real data 微调去重阈值（0.7）和交叉确认阈值（0.2）
