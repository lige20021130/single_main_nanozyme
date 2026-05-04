# TDD驱动修复：自动修正、多源选择、表格解析

## 更新时间
2026-05-04 23:50

## 更新类型
- Bug 修复 / 功能开发 / 测试

## 背景
前两轮修复完成后，仍有遗留问题：
1. ConsistencyAgent 只产生 warning 不自动修正（如 Km/Vmax 单位互换）
2. CrossValidationAgent 结果被"先到先得"策略浪费，高置信度结果无法覆盖已有值
3. _extract_kinetics_from_flattened_table 与 _extract_kinetics_from_text 输入重叠
4. Markdown pipe table 格式无法被 flattened_table 方法解析
5. name_lower 匹配时 dashes 不一致导致材料名匹配失败

本次严格遵循 TDD 流程修复。

## 改动内容

### test/test_consistency_crossval_dedup.py（新增，8个测试）
按照 TDD RED 阶段写了全部 8 个测试，覆盖：
- ConsistencyAgent Km/Vmax 单位自动互换
- ConsistencyAgent catalase_low_pH warning
- CrossValidationAgent 两源一致高置信度
- CrossValidationAgent 高置信度覆盖已有 rule 值
- _extract_kinetics_from_flattened_table 管道表格解析
- _TABLE_NUM_PAT 正则边界情况

### consistency_agent.py
- **check_cross_field_consistency() 新增自动互换逻辑**：当 Km_unit 是速率单位且 Vmax_unit 是浓度单位时，自动互换两者，添加 `Km_Vmax_unit_swapped` 标记
- 保留原有单独 warning（`Km_unit_not_concentration`/`Vmax_unit_not_rate`）作为兜底

### cross_validation_agent.py
- **merge_results() 改进多源选择策略**：当 validation 结果 confidence="high" 时，即使 kin[param] 已有值也应用结果
- **confidence/reason 信息保存**：将 `_confidence_{param}` 和 `_reason_{param}` 写入 kinetics 字段，不再丢弃
- 保留 truncation_detected 和 rule_outside_magnitude_range 的覆盖逻辑

### single_main_nanozyme_extractor.py
- **_extract_kinetics_from_flattened_table()**：
  - 新增 Markdown pipe table 检测和解析（`| col1 | col2 |` → 空格分隔）
  - 新增 separator line（`|---|`）跳过逻辑
  - 修复 `name_lower` 与 `line_compact` 的 dashes 不一致 bug
  - `lines[1:]` → `data_lines` 支持 separator skip

## 未改动内容
- SingleRecordAssembler 未删除（已有 DeprecationWarning，无外部引用）
- DiagnosticsBuilder 两套实现未统一
- _extract_kinetics_from_text 与 _extract_kinetics_from_flattened_table 的功能重叠未完全消除

## 验证方式
- TDD 完整流程：RED（8 tests, 2 failed）→ GREEN（8 tests, 0 fail）
- py_compile.compile() 三个文件均通过
- `python -m pytest test/test_consistency_crossval_dedup.py -v` 8 passed

## 风险与后续
- 高置信度覆盖已有 rule 值可能改变某些文献的提取结果，需观察
- ConsistencyAgent 的互换逻辑依赖于正确的单位分类函数（_is_concentration_unit/_is_rate_unit），需确保覆盖所有常见单位
- 后续可继续 TDD 方式修复 DiagnosticsBuilder 统一和废弃代码清理
