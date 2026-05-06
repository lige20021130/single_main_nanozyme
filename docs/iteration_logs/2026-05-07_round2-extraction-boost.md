# 第二轮提取能力增强

## 更新时间
2026-05-07 00:30

## 更新类型
- 功能开发

## 背景
第一轮优化已增强酶类型检测、合成条件、机制提取、应用提取和全文回退策略。第二轮聚焦于底物/信号/形态/候选召回/表格回退等剩余能力差距最大的领域。

## 改动内容

### A. 底物关键词库扩展 (9→42种)
- `_SUBSTRATE_KEYWORDS` 从9种扩展到42种
- 新增：DAP, Amplex Red, NADH, NADPH, L-DOPA, dopamine, NBT, ONPG, pNPP, DTNB, GSH, ferrocyanide, glucose, cholesterol, uric acid, lactate, ascorbic acid, xanthine 等
- 底物提取搜索范围从 activity bucket 扩展到 kinetics + mechanism bucket
- 匹配方式从精确匹配改为大小写不敏感匹配

### B. 信号/颜色提取模式扩展 (9→25种)
- `_SIGNAL_PATTERNS` 从9种扩展到25种
- 新增：chemiluminescence, Raman, SERS, electrochemical, amperometric, voltammetric, impedance, EIS, UV-vis, spectrophotometric, turn-on/off, ratiometric, DPV, CV, chronoamperometric

### C. 多底物动力学提取 (kinetics_list)
- 新增 `_fill_kinetics_list` 方法
- 将主动力学数据填入 kinetics_list[0]
- 用正则提取 Km(substrate)/Vmax(substrate) 格式的多底物动力学数据
- 填充 kinetics_list 供后续交叉验证使用

### D. 形态学提取增强
- `_MORPHOLOGY_TERMS` 从56种扩展到73种
- 新增：nanoplate, nanocage, nanoframe, nanobranch, nanopyramid, nanocone, quantum dot, 2D/3D, hierarchical, tetrahedr, bipyramid, sea-urchin, aerogel, hydrogel, MOF-derived 等

### E. 尺寸模式扩展
- `_SIZE_PATTERNS` 新增6个模式
- 覆盖：length/thickness/width 显式描述, lattice/crystallite size, average 前缀, approximately 前缀

### F. 候选召回增强
- `_extract_material_names` 新增4组模式
- MOF/COF/ZIF/HOF 等框架材料 (MIL, UiO, HKUST, PCN, NU, NOTT, DUT 等)
- 单原子材料 (Fe Single-Atom, Fe-SAC, Fe-SAzyme 等)
- 常见纳米材料缩写 (Prussian blue, PB, PBA, LDH, MXene, g-C3N4, rGO, GO 等)

### G. 表格行级提取宽松回退
- `_extract_kinetics_from_flattened_table` 末尾新增宽松回退
- 当结构化表格解析失败时，用 _KM_PATTERNS/_VMAX_PATTERNS 直接在表格文本中搜索
- 标记 source 为 "flattened_table_regex" 以区分来源

## 未改动内容
- nanozyme_models.py (枚举映射未变)
- consistency_agent.py (一致性逻辑未变)
- cross_validation_agent.py (交叉验证逻辑未变)
- llm_extractor.py / vlm_extractor.py (LLM/VLM提取未变)

## 验证方式
- py_compile 语法检查通过
- pytest 110个测试全部通过
- git push 成功

## 风险与后续
- 底物关键词扩展可能引入误匹配（如 "TA" 可能匹配非底物上下文），需后续评估
- kinetics_list 填充逻辑仅覆盖 Km(substrate) 格式，更复杂的多底物表格需 LLM 辅助
- 候选召回新增模式可能增加误召回，需通过 _is_valid_candidate 过滤
