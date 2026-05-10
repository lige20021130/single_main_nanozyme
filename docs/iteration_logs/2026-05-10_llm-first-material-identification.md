# LLM-First 材料识别 + 预处理升级

## 更新时间
2026-05-10 01:30

## 更新类型
- 架构调整 / 功能开发 / Bug 修复

## 背景
系统对 4-5.pdf（R-MnCo2O4 纳米管论文）的提取完全失败：
1. 材料名识别为 "ABSTRACT"（致命）
2. 多体系（MnCo2O4 vs R-MnCo2O4）被合并
3. 金属元素 "In" 错误（来自引用文献 InAs/GaAs）
4. 动力学数据无归属链，多体系数据混在一起
5. 分析物识别错误（crystal violet 是探针，ascorbic acid 才是分析物）

根本原因：正则无法理解语义，LLM 被限制在规则之后做精炼。

## 改动内容

### 新增模块: material_identifier.py
- **MaterialIdentifier 类**: LLM-First 材料识别器
  - `identify()`: 从标题+摘要+前N个chunks中，用LLM识别主纳米酶和关联体系
  - `enhance_candidates()`: 将LLM识别结果注入规则候选列表
  - `is_probe_molecule()`: 探针分子判断（静态方法）
- **LLM Prompt**: 专门设计材料识别 prompt，区分主纳米酶/对照材料/引用材料
- **降级策略**: LLM 不可用时回退到 CandidateRecaller + NanozymeScorer

### 修改: single_main_nanozyme_extractor.py
1. **SingleMainNanozymePipeline.__init__**: 初始化 MaterialIdentifier
2. **_extract() 方法**: 在规则候选召回后调用 LLM 材料识别，注入候选列表
3. **NanozymeScorer.score()**: LLM 识别的候选获得 +25 加分，关联体系 +5
4. **_NON_MATERIAL_PHRASES**: 添加 "abstract", "introduction" 等段落标题
5. **record["selected_nanozyme"]**: 保存 llm_identified, llm_confidence, related_systems
6. **TableProcessor._extract_kinetics_from_structured_rows()**: 提取时保留 material_variant 字段

### 修改: extraction_prompts.py
1. **KINETICS_EXTRACTION_PROMPT**: 增加 material_variant 和 detection_method 字段
2. **KINETICS_FEW_SHOT_EXAMPLES**: 添加多材料体系 few-shot 示例（R-MnCo2O4 vs MnCo2O4）
3. **APPLICATION_EXTRACTION_PROMPT**: 增加探针分子/底物/分析物语义角色区分

### 修改: application_extractor.py
1. **_PROBE_MOLECULES**: 新增探针分子黑名单（crystal violet, methylene blue 等）
2. **_INVALID_ANALYTE_PHRASES**: 新增无效分析物短语（"catalytic reactions" 等）
3. **_filter_analyte()**: 新增方法，过滤探针分子和无效分析物短语
4. **_build_application()**: 在构建应用时调用 _filter_analyte()

### 修改: extraction_agents.py
1. **_extract_metal_elements()**: 只在材料名附近的文本中搜索元素，不再全文搜索
   - 先从材料名中提取元素（最可靠）
   - 只在包含材料名的文本块中搜索补充元素
   - 避免引用文献中的元素（如 InAs/GaAs 中的 In）污染结果

## 未改动内容
- Schema 结构不变（selected_nanozyme 仍为单体系）
- CandidateRecaller 和 NanozymeScorer 保留作为降级
- ConsistencyGuard 保留
- NumericValidator 保留
- VLM 提取器保留
- 预处理器（nanozyme_preprocessor_midjson.py）未改动（已在上次迭代中增强）

## 验证方式
- 语法检查：所有修改文件通过 py_compile
- 单元测试：139 个测试全部通过
- 待验证：在 4-5.pdf 上运行（禁用缓存），对比人工提取结果

## 风险与后续
- LLM 材料识别依赖 API 可用性，降级到规则候选时可能仍出现 ABSTRACT 错误
- kinetics_list 中的 material_variant 字段是新增的，下游消费者需要适配
- 需要在更多文献上验证，确保 LLM 识别不会误判
- 后续可考虑方案B：多体系 Schema 重构
