# 第四轮提取能力增强

## 更新时间
2026-05-07 02:30

## 更新类型
- 功能开发

## 背景
第三轮优化新增了 reaction_time/stability/selectivity/response_time/reusability/composition_structured/dopants_or_defects 提取。第四轮聚焦于：1) specific_activity 和 method_detail 两个 schema 字段完全没有规则提取逻辑；2) 全文回退策略覆盖不足，大量字段在 evidence bucket 提取失败后没有全文兜底。

## 改动内容

### A. 新增 specific_activity 规则提取
- 在 KineticsAgent 中新增 `_SPECIFIC_ACTIVITY_PATTERNS`（5个模式）
- 覆盖：specific activity of X U/mg、X U/mg of specific activity、specific activity reached X
- 结果写入 important_values 列表（与 VLM 提取路径一致）

### B. 新增 method_detail 规则提取
- 在 SynthesisAgent 中新增 `_METHOD_DETAIL_PATTERNS`（11个模式）
- 覆盖：under N2/Ar atmosphere、stirred for X h、aged at X、dried at X、calcined at X、washed with X、centrifuged at X、autoclaved、ground/milled、freeze-dried、lyophilized
- 最多收集3条细节，以分号连接写入 synthesis_conditions.method_detail

### C. 大幅增强全文回退策略
- 新增 enzyme_like_type 全文回退（使用 _ENZYME_TYPE_PATTERNS）
- 新增 Km 全文回退（使用 _KM_PATTERNS + 科学计数法解析）
- 新增 Vmax 全文回退（使用 _VMAX_PATTERNS + 科学计数法解析）
- 新增 mechanism 全文回退（使用 _FULLTEXT_MECHANISM_PATTERNS）
- 新增 stability 全文回退（使用 _FULLTEXT_STABILITY_PATTERNS）
- 新增 reaction_time 全文回退（使用 _FULLTEXT_REACTION_TIME_PATTERNS）

### D. 新增 surface_area/pore_size/zeta_potential 全文回退
- 使用已有的 _SURFACE_AREA_PATTERNS/_PORE_SIZE_PATTERNS/_ZETA_POTENTIAL_PATTERNS
- 在全文回退中补充这三个物性参数的兜底提取

### E. 新增模块级全文回退模式
- `_FULLTEXT_STABILITY_PATTERNS`（5个模式）
- `_FULLTEXT_REACTION_TIME_PATTERNS`（3个模式）
- `_FULLTEXT_MECHANISM_PATTERNS`（8个模式）
- 这些模式独立于 RuleExtractor 类，供 RuleExtractorAdapter 的全文回退使用

## 未改动内容
- nanozyme_models.py（枚举映射未变）
- consistency_agent.py（一致性逻辑未变）
- cross_validation_agent.py（交叉验证逻辑未变）
- llm_extractor.py / vlm_extractor.py（LLM/VLM提取未变）
- nanozyme_gui.py（GUI未变）

## 验证方式
- py_compile 语法检查通过
- pytest 110个测试全部通过
- git push 成功

## 风险与后续
- specific_activity 写入 important_values 可能与 VLM 提取结果重复，需后续去重
- method_detail 收集的细节可能包含非关键步骤，需后续评估
- 全文回退的 Km/Vmax 可能匹配到非目标纳米酶的值，需 consistency_guard 过滤
