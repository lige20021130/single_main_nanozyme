# 第六轮优化 - 多酶动力学/上下文追踪/对比表检测/buffer信号/LOD回退

## 更新时间
2026-05-07 22:00

## 更新类型
- 功能开发

## 背景
第五轮优化增强了泛化能力后，第六轮聚焦于更精细的提取场景：多底物/多酶动力学数据提取、段落级上下文追踪、对比表中"this work"检测与负面句过滤、buffer/assay_method/signal提取、LOD/linear_range宽松回退。

## 改动内容

### extraction_agents.py
- **Task A**: 大幅增强 `_fill_kinetics_list` 方法
  - 新增7组多底物Km提取模式（`_MULTI_KM_PATTERNS`）
  - 新增4组多底物Vmax提取模式（`_MULTI_VMAX_PATTERNS`）
  - 新增3组多底物kcat提取模式（`_MULTI_KCAT_PATTERNS`）
  - 新增2组催化效率提取模式（`_MULTI_KCAT_KM_PATTERNS`）
  - 新增2组联合Km/Vmax提取模式（`_JOINT_KM_VMAX_PATTERNS`）
  - 新增2组酶类型动力学提取模式（`_ENZYME_TYPE_KM_PATTERNS`, `_ENZYME_TYPE_VMAX_PATTERNS`）
  - 支持substrate_km、substrate_vmax、enzyme_type_kinetics等多维度动力学数据提取

- **Task C**: 增强对比表"this work"检测 + 负面句过滤
  - 扩展 `_THIS_WORK_CONTEXT` 模式，新增"our nanozyme/catalyst/material/system/sample/result"、"as-prepared/as-synthesized"、"proposed/newly developed"等标记
  - 新增 `_CONTRAST_KEYWORDS` 元组（20+对比关键词）
  - 新增 `_NEGATION_PHRASES` 正则（15+否定短语模式）
  - 新增 `_context_aware_fallback` 方法，实现上下文感知的全文回退提取
    - 检查selected_variants匹配
    - 检查"this work"标记
    - 检测对比关键词并跳过
    - 检测否定短语并跳过

### single_main_nanozyme_extractor.py
- **Task B**: 段落级上下文追踪
  - 增强 `EvidenceBucketBuilder` 的段落归属追踪
  - 新增 `_SECTION_KEYWORDS_PRIORITY` 字典（8个section类型，40+关键词）
  - 新增 `_nearby_name_mention` 方法（窗口=3的邻近名称检测）
  - 增强 `_infer_section` 方法，支持多级section推断
  - 放宽kinetics/application/mechanism桶的准入条件

- **Task D**: 增强buffer/condition + assay_method/signal提取
  - 扩展 `_ASSAY_METHOD_PATTERNS` 从21到43种（新增SERS、DPV、SWV、CV、chronoamperometric、potentiometric、conductometric、impedimetric、smartphone-based、paper-based、microfluidic、lateral flow、ELISA、immunoassay、aptasensor等）
  - 扩展 `_SIGNAL_PATTERNS` 从25到41种（新增reflectance、transmittance、scattering、DLS、phosphorescence、upconversion、downconversion、ratiometric、pH change、O2/H2 evolution等）
  - 扩展 `_BUFFER_PATTERNS` 从17到43种（新增ammonium-acetate、Tris-acetate、Tris-EDTA、HEPES-NaOH、MES、MOPS、Britton-Robinson、borate、carbonate-bicarbonate、glycine-NaOH、PIPES、CHES、CAPS、TAPS、TES、BES、Bicine、Tricine、HEPPSO、EPPS、ADA、bis-Tris、imidazole、succinate、malonate、tartrate、formate、propionate、phthalate等）

- **Task E**: 增强LOD/linear_range宽松回退提取
  - 新增5个LOD宽松模式（scientific notation LOD、detectable down to、LOD reached/obtained、LOQ、lowest detectable concentration）
  - 新增3个linear range宽松模式（response from、concentration range、quantif/determin/measur from）

### consistency_guard.py
- 增强别名发现
  - 新增 `_discover_unicode_formula_aliases` 方法（Unicode下标↔ASCII数字互转）
  - 新增 `_discover_hereafter_aliases` 方法（"hereafter/hereinafter/referred to as/denoted as"定义模式检测）
  - 新增 `_discover_pronoun_aliases` 方法（代词别名发现）

### nanozyme_models.py
- 修复 EnzymeType.XYLANASE 条目拼写

## 未改动内容
- extraction_pipeline.py（管道编排层未改动）
- cross_validation_agent.py（交叉验证逻辑未改动）
- consistency_agent.py（一致性修正逻辑未改动）
- llm_extractor.py / vlm_extractor.py（LLM/VLM提取器未改动）
- GUI层未改动

## 验证方式
- py_compile语法检查：3个核心文件全部通过
- pytest单元测试：110个测试全部通过
- git commit成功（745行新增，62行删除）

## 风险与后续
- git push因网络问题失败，需后续手动推送
- 多底物动力学提取模式可能产生误匹配，需在实际文献中验证
- 上下文感知回退的否定检测可能过于保守，需根据实际效果调整
- buffer模式库已覆盖40+种，但仍可能有罕见buffer类型遗漏
