# 规则提取与LLM/VLM补全信息丢失检测与修复

## 更新时间
2026-05-03 15:00

## 更新类型
- Bug 修复 / 功能增强 / 测试

## 背景
检测规则提取与LLM/VLM补全交互过程中是否存在信息丢失。当规则提取已获得某些字段值后，LLM/VLM作为补全来源时，其提取的值可能被完全丢弃而非保存为备选。

## 改动内容

### 1. 修复酶类型子串匹配误判 (single_main_nanozyme_extractor.py L5162-5186)
- **问题**: `peroxidase-like` 和 `oxidase-like` 是完全不同的酶类型，但旧代码用 `in` 子串匹配导致 `"oxidase-like" in "peroxidase-like"` 为 True，误判为子类型关系，LLM被拒绝的值未保存到 `_llm_enzyme_type_rejected`
- **修复**: 用精确的 `_ENZYME_SUBTYPES` 映射表替代子串匹配，只有真正的子类型关系（如 `oxidase-like` → `glucose-oxidase-like`）才视为包含关系

### 2. 修复动力学比值边界问题 (single_main_nanozyme_extractor.py L5001)
- **问题**: `ratio > 100` 条件下，当 ratio 恰好等于 100.0 时不满足，导致 100 倍差异的值走了 >10 分支而非 >=100 分支
- **修复**: 将 `ratio > 100` 改为 `ratio >= 100`

### 3. 修复 ratio>10 分支中LLM替代值未保存到 important_values (single_main_nanozyme_extractor.py L5112-5125)
- **问题**: 当动力学值差异在 10-100 倍之间时，LLM替代值只保存到 `_llm_{kk}_alternative` 字段，未同步保存到 `important_values`，导致信息可能丢失
- **修复**: 在 ratio>10 的 else 分支中添加 `record["important_values"].append()` 保存 LLM 替代值

### 4. 修复VLM observations信息丢失 (single_main_nanozyme_extractor.py L4123-4135)
- **问题**: 当规则已提取 morphology 时，VLM observations 中的形貌信息被完全忽略，无任何保存
- **修复**: 当 morphology 已存在时，将 VLM observations 保存到 `_vlm_morphology_rejected` 字段和 `important_values` 中

### 5. 扩展信息丢失测试 (test/test_merge_info_loss.py)
- 新增 R21-R40 共 20 个测试类别，覆盖：
  - VLM sensing_performance 数据保留
  - VLM Km 差异>50% 时数据保留
  - VLM observations 信息保留
  - VLM particle_size 数据保留
  - 酶类型子类型关系正确处理
  - 动力学比值边界测试
  - important_values 同名去重
  - kinetics_list 字段级合并
  - applications 同类型不同analyte合并
  - synthesis_conditions 部分覆盖
  - _backfill_kinetics_from_important_values 回填
  - LLM signal/composition 等字段保留

### 6. 修复测试中 extract_from_evidence 调用缺少参数
- 旧测试中 `rule.extract_from_evidence(record, evidence)` 缺少 `table_values` 和 `selected_name` 参数
- 修复为 `rule.extract_from_evidence(record, evidence, [], "Fe3O4")`

### 7. 修复 R17/R18 VLM 测试数据格式
- 旧测试使用 `important_values` 格式传入 VLM 数据，但 `_merge_vlm` 期望 `extracted_values` 格式
- 修复为正确的 `extracted_values.Km` 格式

## 未改动内容
- CrossValidationAgent 的合并逻辑（独立模块，不在本次修复范围）
- VLM sensing_performance 写入 applications 的逻辑（当前通过 important_values 保留数据，后续可考虑增强）
- 规则提取中的证据桶截断逻辑

## 验证方式
- 运行 `python test/test_merge_info_loss.py`: 78 passed, 0 failed
- 运行 `python test/test_coverage.py`: 621 passed, 0 failed

## 风险与后续
- **VLM sensing 不写入 applications**: 当 CrossValidationAgent 不可用时，VLM 提取的 sensing 数据只保存在 important_values 中，不会自动成为 application 记录。后续可考虑在 `_merge_vlm` 中添加 sensing → applications 的逻辑
- **VLM 大量字段不合并**: `_merge_vlm` 只处理 Km、Vmax、particle_size、sensing_performance、other_values、morphology 六类，VLM 提取的 pH、temperature、substrate 等信息可能丢失。后续可增强 `_merge_vlm` 的字段覆盖
- **规则值10倍以内差异时LLM值仅存为 alternative**: 当规则值有 OCR 错误但差异<10倍时，LLM 值不会覆盖。后续可考虑增加置信度评分机制
