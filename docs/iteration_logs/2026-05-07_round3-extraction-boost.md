# 第三轮提取能力增强

## 更新时间
2026-05-07 01:30

## 更新类型
- 功能开发

## 背景
前两轮优化已增强底物/信号/形态/候选召回/表格回退。第三轮聚焦于 schema 中定义但完全没有规则提取逻辑的字段：reaction_time、stability、selectivity、response_time、reusability、composition_structured、dopants_or_defects。

## 改动内容

### A. 新增 reaction_time 提取
- 新增 `_REACTION_TIME_PATTERNS`（6个模式）
- 覆盖：reaction/incubation/catalytic time、incubated for、after/within X min of reaction
- 在主提取流程中调用，搜索 activity + kinetics bucket

### B. 新增 stability 提取
- 新增 `_STABILITY_PATTERNS`（6个模式）
- 覆盖：stable for X days/weeks/months、retained X% after Y cycles、storage/long-term stability、good/excellent stability、no significant loss in activity
- 在主提取流程中调用，搜索 characterization + activity + material bucket

### C. 新增 selectivity/interference 提取
- 在 ApplicationAgent 中新增 `_SELECTIVITY_PATTERNS`（6个模式）和 `_SELECTIVITY_DETAIL_PATTERNS`（3个模式）
- 覆盖：selectivity、interference、anti-interference、specificity、no significant interference、high/excellent selectivity
- 提取选择性目标：selective toward/for/over X
- 结果写入 applications[0].notes

### D. 新增 response_time 提取
- 在 ApplicationAgent 中新增 `_RESPONSE_TIME_PATTERNS`（5个模式）
- 覆盖：response/detection time、within/in X s/min of response/detection、rapid/fast response
- 结果写入 applications[0].notes

### E. 新增 reusability 提取
- 在 ApplicationAgent 中新增 `_REUSABILITY_PATTERNS`（6个模式）
- 覆盖：retained X% after Y cycles、reusable、recyclable、reused/recycled for X cycles
- 结果写入 applications[0].notes

### F. 新增 composition_structured 提取
- 在 MorphologyAgent 中新增 `_CORE_PATTERN`、`_SUPPORT_PATTERN`、`_ORGANIC_PATTERN`
- 覆盖：core@shell 格式（Fe3O4@C）、supported/deposited/loaded on X、coated/wrapped/functionalized with X
- 自动从 dopants_or_defects 同步到 composition_structured.dopants

### G. 新增 dopants_or_defects 提取
- 在 MorphologyAgent 中新增 `_DOPANT_PATTERNS`（10个模式）
- 覆盖：N/B/S/P/F-doped、co-doped/tri-doped、doped with/by X、oxygen/sulfur/nitrogen vacancy、vacancy/defects、metal-doped

## 未改动内容
- nanozyme_models.py（枚举映射未变）
- consistency_agent.py（一致性逻辑未变）
- cross_validation_agent.py（交叉验证逻辑未变）
- llm_extractor.py / vlm_extractor.py（LLM/VLM提取未变）
- nanozyme_gui.py（GUI未变）

## 验证方式
- py_compile 语法检查通过
- pytest 110个测试全部通过
- git commit 成功
- git push 因网络问题暂未成功，待网络恢复后推送

## 风险与后续
- selectivity/response_time/reusability 结果写入 notes 字段，可能需要后续 schema 扩展为独立字段
- composition_structured 的 core@shell 模式可能匹配非纳米酶相关的格式
- dopants_or_defects 的 vacancy/defects 模式可能过于宽泛，需后续评估误匹配率
