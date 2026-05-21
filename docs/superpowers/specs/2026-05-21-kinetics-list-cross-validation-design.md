# kinetics_list 交叉验证引擎设计

## 更新时间
2026-05-21

## 背景

当前 CrossValidationAgent 只验证主 kinetics 字段（Km/Vmax/kcat/kcat_Km），不验证 kinetics_list（多底物/多材料变体）。VLM 回填 kinetics_list 硬编码 substrate="TMB"/detection_method="UV-vis"。LLM kinetics_list 合并仅按 substrate 去重不做数值交叉验证。导致多底物/多材料场景下数据丢失和冲突未裁决。

## 5大缺陷

1. CrossValidationAgent 只验证主 kinetics，不验证 kinetics_list
2. VLM 回填 kinetics_list 硬编码 substrate="TMB", detection_method="UV-vis"
3. LLM kinetics_list 合并仅按 substrate 去重，不交叉验证数值
4. VLM 多图动力学数据不回填到 kinetics_list
5. VLM sensing_performance 回填不与 Rule/LLM 交叉验证

## 设计方案

### 1. kinetics_list 交叉验证引擎

新增 `CrossValidationAgent.validate_kinetics_list(rule_list, llm_list, vlm_list)`:

- 匹配键: (substrate, material_variant, detection_method)，None 统一为 ""
- 逐条匹配 Rule/LLM/VLM 的 kinetics_list 条目
- 匹配到的条目: 复用 validate_kinetics 逐参数验证
- 未匹配的条目: 直接采用，标记 source 和 confidence
- 返回合并后的 kinetics_list，每个条目带 _confidence 和 _source

### 2. VLM 回填修复

新增 `single_main_nanozyme_extractor._build_vlm_kinetics_entries(vlm_results)`:

- 从 VLM 原始结果提取 material/substrate/detection_method
- 不再硬编码默认值
- 同一图中 Km/Vmax 按 material 匹配合并
- 多图数据按 (substrate, material_variant) 分组聚合
- 一致则合并，不一致则保留多条并标记 needs_review

### 3. LLM kinetics_list 合并增强

- Rule 和 LLM 的 kinetics_list 统一进入 validate_kinetics_list
- 同 substrate 条目做数值一致性检查
- 一致→高置信度合并，不一致→保留 Rule 值，LLM 值进 _llm_alternative

### 4. sensing 交叉验证

新增 `CrossValidationAgent.validate_sensing_performance(rule_apps, vlm_sensing)`:

- LOD/linear_range 的 Rule/LLM vs VLM 交叉验证
- 两者都有且接近→高置信度
- 只有一方→中/低置信度
- 冲突→保留 Rule 值，VLM 值进 important_values

### 5. 管道集成

新流程:
```
Rule提取 → 收集三源kinetics_list → validate_kinetics_list → merge_results(主kinetics) → validate_sensing_performance → _sync_kinetics_list
```

## 改动文件

| 文件 | 改动 |
|------|------|
| cross_validation_agent.py | 新增 validate_kinetics_list、validate_sensing_performance、_build_match_key、_merge_kinetics_entry |
| single_main_nanozyme_extractor.py | 修改 _add_vlm_kinetics_to_list→_build_vlm_kinetics_entries；修改 extract 合并流程；简化 _merge_llm/_merge_vlm 的 kinetics_list 部分 |

## 不改动文件

extraction_prompts.py, schema_constraints.py, domain_knowledge.py, consistency_agent.py, numeric_validator.py
