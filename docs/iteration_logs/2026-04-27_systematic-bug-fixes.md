# 系统性问题修复 - 标准化、类型转换、名称清洗

## 更新时间
2026-04-27 23:30

## 更新类型
- Bug 修复

## 背景
根据之前系统评估报告和问题清单，系统存在以下问题：
1. 酶类型标准化回退搜索顺序错误，短关键词优先匹配导致复合类型误判
2. 分析物名称清洗正则尾部要求多余空格，导致关键词后无内容时无法清洗
3. 材料名后缀"nanozyme"/"SAzyme"/"nanoparticles"等未清洗
4. Vmax值存储为字符串而非数字类型
5. Vmax 2组匹配时value/unit判断逻辑错误
6. Vmax速率单位正则不支持"M s-1"等常见变体

## 改动内容

### 1. 酶类型标准化回退搜索修复（single_main_nanozyme_extractor.py）
- **问题**：`_normalize_enzyme_type()` 的回退搜索按字典插入顺序遍历，"oxidase"先于"glutathione oxidase"匹配，导致"glutathione oxidase (GSHOx)"被错误标准化为"oxidase-like"
- **修复**：将回退搜索改为按key长度降序排列（最长匹配优先）
- **代码**：`sorted(self._ENZYME_TYPE_NORMALIZE.items(), key=lambda kv: -len(kv[0]))`
- **验证**：`'glutathione oxidase (GSHOx) and peroxidase (POD)'` → `'glutathione-oxidase-like + peroxidase-like'` ✅

### 2. 分析物名称清洗正则修复（single_main_nanozyme_extractor.py）
- **问题**：`_ANALYTE_JUNK_RE` 尾部使用 `\s+.*$`（要求至少一个空格），当关键词后无更多内容时无法匹配
- **修复**：将 `\s+.*$` 改为 `\s*.*$`（空格可选）
- **验证**：`'H2O2 For the detection'` → `'H2O2'` ✅，`'H2O2 for sensing'` → `'H2O2'` ✅

### 3. 材料名后缀清洗（single_main_nanozyme_extractor.py）
- **问题**：LLM输出的材料名常带"nanozyme"/"SAzymes"/"nanoparticles"/"NPs"等后缀，如"MIL-101(CuFe) nanozyme"
- **修复**：新增 `_NAME_SUFFIX_JUNK_RE` 正则，在 `_clean_llm_name()` 中去除尾部冗余后缀
- **正则**：`r'\s+(?:nanozymes?|SAzymes?|enzyme\s+mimics?|catalysts?|nanoparticles?|NPs?)\s*$'`
- **验证**：`'MIL-101(CuFe) nanozyme'` → `'MIL-101(CuFe)'` ✅，`'Fe-N-C SAzymes'` → `'Fe-N-C'` ✅

### 4. Vmax值类型转换（single_main_nanozyme_extractor.py）
- **问题**：Vmax值在多处赋值时存储为字符串（如"76.4"），而非数字类型
- **修复**：在以下4处添加 `float()` 转换：
  1. `_extract_kinetics_from_text()` 中的文本Vmax提取
  2. `_extract_kinetics_from_flattened_table()` 中的扁平化表格Vmax提取
  3. `_try_parse_inline_table()` 中的内联表格Vmax提取
  4. `_extract_kinetics_from_tables()` 中的结构化表格Vmax提取
  5. `_merge_llm()` 中LLM返回的Km/Vmax值
- **验证**：Vmax值现在统一为float类型

### 5. Vmax 2组匹配value/unit判断修复（single_main_nanozyme_extractor.py）
- **问题**：Vmax正则2组匹配时，代码假设第一个组为substrate或unit，但Pattern 3的2组为(value, unit)，导致value和unit互换
- **修复**：改为双向判断——先检查g1是否为速率单位（value在前），再检查g0是否为速率单位（unit在前），最后才假设(substrate, value)
- **影响范围**：`_extract_kinetics_from_text()` 和 `TableProcessor.get_kinetics_values()` 两处
- **验证**：`'Vmax was 3.2e-7 M/s'` → Vmax=3.2e-07, unit='M/s' ✅

### 6. Vmax速率单位正则增强（single_main_nanozyme_extractor.py）
- **问题**：Vmax正则只支持 `M s⁻¹` 和 `M/s`，不支持文献中常见的 `M s-1`（普通减号）
- **修复**：将单位匹配从 `M\s*[sS]⁻¹|M/s` 改为 `M\s*[sS][⁻\-–]1|M/?s`，支持多种减号和省略斜杠的写法
- **同步更新**：`_RATE_UNITS` 元组增加 `"M s-1"`, `"M s–1"`, `"M S-1"` 变体
- **验证**：`'Vmax (TMB) was 3.2 M s-1'` → Vmax=3.2, unit='M s-1' ✅

## 未改动内容
- `nanozyme_preprocessor_midjson.py`：未修改
- `extraction_pipeline.py`：未修改
- `pdf_basic_gui.py`：未修改
- `config.yaml`：未修改
- `test_single_main_nanozyme.py`：未修改（32个现有测试全部通过）
- `batch_test_2021.py`：未修改

## 验证方式
- 32个单元测试全部通过（pytest）
- 专项验证测试全部通过：
  - 酶类型标准化：8/8 PASS
  - 材料名后缀清洗：6/6 PASS
  - 分析物名称清洗：4/4 PASS
  - Vmax类型和值提取：2/2 PASS
  - LLM名称修复：3/3 PASS

## 风险与后续
- **VLM未测试**：图片分析功能仍待实际测试
- **Km/Vmax提取率仍有限**：部分论文的动力学数据在图片中，需要VLM辅助
- **Vmax复杂格式**：如"76.4 × 10⁻⁸ M s⁻¹"等含科学计数法的格式，当前提取可能不完整
- **材料名清洗边界情况**：如"Co-NC-700"不含后缀词时不受影响，但"Fe3O4@C nanozyme"中@后的nanozyme也会被正确清除
