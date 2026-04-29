# 14篇真实文献全链路测验与修复

## 更新时间
2026-04-27 20:20

## 更新类型
- Bug 修复 / 功能开发 / 测试

## 背景
使用14篇真实纳米酶文献（11篇主文+3篇SI）对系统进行全链路测验（PDF→解析→预处理→提取→JSON），发现并修复材料选择、酶类型检测、动力学提取等方面的多个问题。

## 改动内容

### 1. 候选材料提取增强（single_main_nanozyme_extractor.py）

- **添加技术缩写黑名单** `_TECHNIQUE_ABBREVIATIONS`：SERS, HAADFSTEM, XRD, XPS, TEM, SEM等80+项
- **添加试剂黑名单** `_REAGENT_NAMES`：NaAc, NaCl, PBS, HRP等30+项
- **添加小分子黑名单** `_SMALL_MOLECULE_NAMES`：O2, H2O, CO2, NH3等20+项
- **添加底物+后缀过滤** `_SUBSTRATE_PLUS_RE`：过滤"H2O2 system"、"TMB solution"等
- **添加离子片段过滤**：过滤"Cu2+"、"Fe3+"等裸离子，以及"Cu2"等无符号离子片段
- **添加连字符片段过滤**：过滤"me-li"、"gh-ef"等英文连字符词片段
- **添加复合名含底物过滤**：过滤"CDs/H2O2"等含底物的复合名
- **添加双元素化合物验证**：3字符以下无数字名称需验证为已知双元素化合物（如CuS, ZnO）

### 2. 标题优先策略（CandidateRecaller）

- **新增 `_extract_title_material` 方法**：从标题中提取材料名，包括化学式、MOF/COF/ZIF名、元素-缩写名（如Cu-CDs）
- **新增 `_clean_candidate_name` 方法**：清洗候选名前缀（"formation of"、"catalyst"、"that magnetic"等），提取核心化学式
- **增强 `recall` 方法**：标题提取优先，hints候选名清洗后入库

### 3. 去重逻辑优化（CandidateRecaller._deduplicate）

- **优先保留短名**：避免"formation of Fe3C nanoparticles"覆盖"Fe3C"
- **复合结构优先**：有@或/的长名优先（Fe3O4@C > Fe3O4）
- **数字优先**：有更多数字的长名优先（MnO2 > MnO）
- **复数优先**：有复数后缀的长名优先（Cu-CDs > Cu-CD）

### 4. 评分增强（NanozymeScorer）

- **底物/技术/试剂/小分子惩罚**：-25到-30分
- **标题匹配加分**：+10分（名字出现在标题中）
- **标题来源加分**：+5分（从标题提取的候选）
- **黑名单项不享受加分**：避免通用词/底物通过标题加分获得高分

### 5. 酶类型检测增强（RuleExtractor）

- **添加缩写模式**：POD-like→peroxidase-like, OXD-like→oxidase-like, CAT-like→catalase-like, GPx-like→glutathione-peroxidase-like
- **全文本回退搜索**：当evidence bucket中未找到酶类型时，搜索所有chunks
- **标题+摘要优先搜索**：先搜索标题和摘要，再搜索bucket

### 6. 动力学参数提取增强

- **Km模式增加"of"**：`Km value of ... was 0.04853 mM`格式
- **Vmax模式增加方括号格式**：`Vmax [10−8 M s−1] 3.315`
- **表格格式支持**：`Km (mM) 0.548`

### 7. 正则表达式修复

- **`_MATERIAL_PATTERN_RE`添加词边界**：防止匹配英文连字符词片段
- **`_COMPOSITE_PATTERN_RE`修复**：支持多元素符号在@两侧（如FeP@C），移除IGNORECASE防止误匹配
- **第三替代模式重构**：元素符号序列+@+元素符号序列，支持FeP@C等复杂复合名

### 8. Bug修复

- **`_TABLE_TYPE_PATTERNS`键名修复**：sensing_performance_table → sensing_table，修复547.pdf KeyError
- **`RuleExtractor.extract_from_evidence`签名更新**：添加doc参数用于全文本搜索

## 未改动内容
- `nanozyme_preprocessor_midjson.py`：未修改
- `extraction_pipeline.py`：未修改
- `pdf_basic_gui.py`：未修改
- `nanozyme_models.py`：未修改
- `config.yaml`：未修改

## 验证方式
- 32个单元测试全部通过
- 11篇主文PDF全链路测试：材料选择10/11正确（91%），酶类型11/11全部检测到（100%）
- Km提取2/11（48.pdf和69-70.pdf成功）

## 风险与后续
- **Km/Vmax提取率低**：大部分论文的动力学参数在表格中，扁平化文本格式难以正则匹配。后续需要增强表格解析，提取结构化表格数据。
- **15-19.pdf材料名不精确**：标题无标准化学式，"SAEs"是可接受但不够精确的结果。后续可增加"single atom catalyst"等描述性材料名的提取。
- **应用信息缺失**：部分论文应用字段为空，需要增强应用提取规则。
- **LLM未启用**：当前测试全部为规则提取，LLM启用后预期可大幅提升提取质量。
