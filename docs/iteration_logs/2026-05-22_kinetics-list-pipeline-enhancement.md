# kinetics_list 全链路增强

## 更新时间
2026-05-22 22:00

## 更新类型
- 功能开发

## 背景
kinetics_list 是多底物动力学数据的核心载体，但当前系统中多个关键环节只处理主 kinetics 字段，不处理 kinetics_list，导致：
1. `_sync_kinetics_list` 去重键包含 Km/Vmax 数值，与交叉验证引擎的 (substrate, material_variant, detection_method) 三元组不一致，导致交叉验证合并后的 entry 被误删
2. `_backfill_kinetics_from_important_values` 只回填主 kinetics，不回填 kinetics_list，多底物数据丢失
3. `_apply_llm_structured_result` 合并 kinetics_list 时发现重复条目直接跳过，不回填空字段（如 kcat）
4. `_final_kinetics_validation` 对 kinetics_list 的校验不完整，缺少 kcat/kcat_Km 量级校验、Vmax 科学计数法转换、Km mM 过大值清除

## 改动内容
- **`single_main_nanozyme_extractor.py`** (170行新增, 15行删除)

### 1.1 _sync_kinetics_list 去重键与交叉验证对齐
- 去重键从 `(Km, Km_unit, Vmax, Vmax_unit, substrate, detection_method, material_variant)` 改为 `(substrate, material_variant, detection_method)` 三元组（统一小写比较）
- 主 kinetics 插入逻辑改为：先在 kinetics_list 中查找匹配三元组的 entry，找到则回填空字段，未找到才插入新 entry
- 去重时发现重复 entry 不再直接跳过，而是回填空字段

### 1.2 _backfill_kinetics_from_important_values 回填到 kinetics_list
- 新增 kinetics_list 读取和回写
- 匹配逻辑使用宽松匹配：substrate/material_variant/detection_method 任一方为空时视为匹配（允许 important_values 无 substrate 信息时匹配到有 substrate 的 entry）
- 匹配到已有 entry 时回填空字段（Km/Vmax/kcat/kcat_Km + 单位）
- 有 substrate/material_variant/detection_method 但无匹配 entry 时创建新 kinetics_list 条目

### 1.3 _apply_llm_structured_result 合并时回填空字段
- kinetics_list 合并逻辑从"发现重复则跳过"改为"发现重复则回填空字段"
- LLM 提供的 kcat/kcat_Km 等字段可以补充到已有 entry 中

### 1.4 _final_kinetics_validation 扩展到 kinetics_list
- 主 kinetics 新增 kcat M/s→μM/s 自动转换、kcat_Km 量级校验（<1e3 /M/s 清除）
- kinetics_list 新增：
  - Km mM > 1000 清除 + needs_review
  - Vmax 科学计数法单位转换（×10^N 格式）
  - Vmax M/s 过大值清除 + needs_review
  - Vmax mM/s→μM/s 自动转换
  - kcat M/s→μM/s 自动转换
  - kcat_Km 量级校验（<1e3 /M/s 清除 + needs_review）

## 未改动内容
- 交叉验证引擎（cross_validation_agent.py）的匹配逻辑未改动
- LLM 结构化提取（llm_structured_extractor.py）未改动
- 一致性修正（consistency_agent.py）未改动
- 已知失败测试 test_extract_from_table 未修复（与本次修改无关）

## 验证方式
- 编写8个针对性单元测试全部通过
- 项目原有141个测试全部通过（排除1个已知失败）
- Python 导入验证通过

## 风险与后续
- 宽松匹配策略（空字段视为匹配）可能在极少数情况下错误匹配不同底物的 entry，但实际场景中 important_values 通常只有一个底物的数据，风险极低
- 下一步建议：继续实施 LLM 提取质量提升和一致性守卫增强
