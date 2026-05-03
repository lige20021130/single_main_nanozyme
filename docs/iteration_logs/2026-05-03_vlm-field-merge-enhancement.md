# VLM字段合并增强与LLM替代值可追溯性优化

## 更新时间
2026-05-03 16:30

## 更新类型
- 功能增强 / Bug 修复 / 测试

## 背景
上一轮检测发现 `_merge_vlm` 只处理了6类VLM字段（Km/Vmax/particle_size/sensing_performance/other_values/observations），而VLM实际返回的 `linked_activity_type` 和 `application_hints` 完全被忽略。同时 `_merge_llm` 中 ratio<10x 分支的LLM替代值只存到内部字段，未保存到 `important_values`，导致信息不可追溯。

## 改动内容

### 1. VLM sensing_performance → applications (single_main_nanozyme_extractor.py L4110-4135)
- **新增**: VLM提取的 sensing 数据（LOD/linear_range）现在不仅存入 important_values，还会写入 applications
- 匹配逻辑：按 target_analyte 匹配已有 application，填入空的 detection_limit/linear_range
- 无匹配时创建新的 sensing 类型 application
- **修复**: 字段名使用标准 `detection_limit` 而非 `LOD`，与 applications 模板一致

### 2. VLM linked_activity_type → enzyme_like_type (single_main_nanozyme_extractor.py L4167-4176)
- **新增**: VLM从图片识别的酶类型现在合并到 enzyme_like_type
- 当规则值为 None 或 "unknown" 时填入
- 当规则值已存在且不同时，保存到 `_vlm_enzyme_type_rejected`

### 3. VLM application_hints → applications (single_main_nanozyme_extractor.py L4178-4196)
- **新增**: VLM从图片识别的应用类型现在合并到 applications
- 按 application_type 去重，不重复添加已有类型
- 新增的 application 带 `notes: "from VLM application_hints"` 标记

### 4. LLM ratio<10x 替代值保存到 important_values (single_main_nanozyme_extractor.py L5194-5203)
- **修复**: 当动力学值差异在10倍以内时，LLM替代值现在也保存到 important_values
- 之前只存到 `_llm_{kk}_alternative` 内部字段，无法在最终输出中追溯
- context 字段标注 `LLM alternative value (rule={rule_val}, within 10x)`

### 5. 测试扩展 (test/test_merge_info_loss.py)
- 新增 R41-R49 共9个测试类别15个测试用例
- 覆盖：VLM sensing→applications、VLM enzyme_type、VLM application_hints、LLM ratio<10x IV保存
- 总测试数：93 passed, 0 failed

## 未改动内容
- CrossValidationAgent 的合并逻辑（独立模块）
- VLM Km/Vmax 的差异判断逻辑（保持现有50%阈值）
- 旧测试 R1/R14 中的 LOD 字段名（这些测试的是 LLM 合并逻辑，不影响实际输出）

## 验证方式
- `python test/test_merge_info_loss.py`: 93 passed, 0 failed
- `python test/test_coverage.py`: 621 passed, 0 failed

## Codex审查发现
- **已修复**: VLM sensing 写入 applications 时初始使用了 `LOD` 字段名，与标准模板 `detection_limit` 不一致。已统一为 `detection_limit`

## 风险与后续
- VLM sensing 创建的 application 可能与规则提取的 application 重复（如果规则提取用了不同的 target_analyte 表述）。后续可考虑更智能的匹配
- VLM application_hints 只按 application_type 去重，不区分 target_analyte。如果同一类型有不同 analyte，可能丢失
