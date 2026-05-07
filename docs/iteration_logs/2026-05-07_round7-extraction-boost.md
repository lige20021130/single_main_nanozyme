# 第七轮提取能力优化

## 更新时间
2026-05-07

## 更新类型
- 功能开发

## 背景
第七轮优化聚焦于5个关键能力缺口：关键名称集不足、候选评分缺乏上下文感知、应用提取覆盖窄、全文回退缺少characterization/analyte/dopant回退、表格提取对比表过滤和行级回退不足。

## 改动内容

### A. 扩展关键名称集
- `_SUBSTRATE_NAMES` 从8种扩展到70+种（新增DAPI、Amplex Red、Luminol、NADH/NADPH、pNPP、ONPG、DAB、MTT、WST系列、铁氰化物/亚铁氰化物、L-DOPA、染料类等）
- `_REAGENT_NAMES` 大幅扩展（新增金属盐、有机试剂、生物分子、细胞系、培养基、表面活性剂、溶剂、生物酶等）
- `_GENERIC_PHRASES` 扩展（新增纳米形态通用词、传感器/平台通用词、催化剂通用词等）
- `_NON_MATERIAL_PHRASES` 扩展（新增as-prepared、proposed、newly developed等变体）

### B. 增强NanozymeScorer候选选择逻辑
- 新增MOF/COF/ZIF框架材料评分（+6分）
- 新增金属-氮/碳复合材料评分（+4分）
- 新增金属氧化物评分（+4分）
- 新增常见纳米材料缩写评分（Prussian blue/PB/PBA/LDH/MXene/g-C3N4/rGO/GO +5分，CDs/CQDs/GQDs/CNFs/CNTs +3分）
- 新增多组分材料评分（core@shell +3分，多组分复合 +2分）

### C. 增强应用提取
- `_ANALYTE_PATTERNS` 从14种扩展到35+种（新增碳水化合物、醇类、离子、环境污染物、金属离子、抗生素、霉菌毒素、生物分子、气体分子、维生素、激素等）
- `_SAMPLE_TYPE_MAP` 从18种扩展到80+种（新增食品类、环境水类、土壤/空气、体液类、临床样本、制药/化妆品/纺织/工业/农业样本等）

### D. 增强全文回退
- 新增characterization技术回退（使用_CHARACTERIZATION_TECHNIQUES字典扫描全文）
- 新增应用analyte回退（使用_ANALYTE_PATTERNS在全文中搜索target_analyte）
- 新增应用sample_type回退（使用_SAMPLE_TYPE_MAP在全文中匹配）
- 新增dopant回退（使用_DOPANT_PATTERNS在全文中搜索掺杂元素）

### E. 增强表格提取
- 增强`_filter_this_work`方法：
  - 增加材料名变体匹配（@/拆分、后缀去除）
  - 增加材料列定位和精确匹配
  - 增加首行猜测逻辑（小表格中标记为"1"/"1a"/"a"的行）
  - 区分匹配来源（this_work/name_match/material_col_match/first_entry_guess）
- 增强`get_kinetics_values`方法：
  - 在所有结构化提取失败后，添加宽松回退
  - 扫描所有表格行中包含km/vmax/kcat关键词的行
  - 扫描content_text和markdown中的动力学数据
- 增强`get_sensing_values`方法：
  - 新增selected_name参数，支持行级目标材料过滤
  - 新增linear_range_high列提取
  - 新增target_analyte、method、sample_type列提取
  - 新增analyte正则回退（使用_ANALYTE_PATTERNS）
  - 新增宽松回退（扫描content_text/markdown中的LOD/linear_range）
- 更新调用处传入selected_name参数

## 未改动内容
- nanozyme_models.py（枚举映射未变）
- consistency_agent.py（一致性逻辑未变）
- cross_validation_agent.py（交叉验证逻辑未变）
- llm_extractor.py / vlm_extractor.py（LLM/VLM提取未变）
- nanozyme_gui.py（GUI未变）

## 验证方式
- py_compile 语法检查通过
- pytest 110个测试全部通过
- git commit 成功（push因网络问题待重试）

## 风险与后续
- _SAMPLE_TYPE_MAP扩展后部分关键词（如"water"、"solution"）可能过于宽泛导致误匹配
- _filter_this_work的首行猜测逻辑在小表格中可能误选非目标行
- get_sensing_values的宽松回退可能提取到非目标材料的LOD数据
- 后续需通过实际文献测试评估误匹配率
