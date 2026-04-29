# Vmax缺失修复 — OCR科学记数法鲁棒解析

## 更新时间
2026-04-28 22:30

## 更新类型
- Bug 修复 / 功能开发

## 背景
Vmax 缺失是系统三大短板之一。OCR 文本中科学记数法被严重破坏，导致 Vmax 值无法被正则模式提取。典型破坏模式：
1. 上标负号 `⁻` (U+207B) → 替换字符 `�` (U+FFFD)，如 `10⁻⁸` → `10�8`
2. 乘号 `×` → `�`，如 `1.5 × 10⁻¹²` → `1.5 � 10�12`
3. 中间点 `·` → 空格或丢失，如 `M·s⁻¹` → `M s�1`
4. 等号 `=` → `¼`，`±` → `\u0006`，`≈` → `e`
5. 单位拆分 `mM` → `m M`

此外发现 Vmax 提取只在 `Km is None` 时才尝试，导致 Km 已提取但 Vmax 未提取时无法补救。

## 改动内容

### 1. 新增 `_normalize_ocr_scientific()` 函数
- 文件：[single_main_nanozyme_extractor.py](file:///d:/ocrwiki版本/single_main_nanozyme/single_main_nanozyme_extractor.py)
- 预处理 OCR 文本，修复常见科学记数法破坏
- 处理优先级：`10□digit` → `10⁻digit` > `number□10` → `number×10` > `letter□digit` → `letter⁻digit` > `digit□digit` → `digit-digit`
- 修复 `¼` → `=`，`\u0006` → `±`，`word e digit` → `word ≈ digit`
- 修复单位拆分 `m M` → `mM`，`M s⁻¹` → `M·s⁻¹`

### 2. 增强 `_parse_scientific_notation()`
- 新增 E 记数法支持：`1.23e-8`、`1.23E-8`
- 新增缺失乘号格式：`1.23 10⁻⁸`
- 新增紧凑格式：`1.23×10⁻⁸`（无空格）
- 统一处理 Unicode 减号变体：`⁻`、`-`、`–`、`−`、`⁻`

### 3. 新增 OCR 容错 Vmax 模式和回退提取
- 新增 `_VMAX_OCR_PATTERNS`：7 个专门处理 OCR 破坏格式的正则
- 新增 `_VMAX_RATE_UNIT_RE`：更宽松的速率单位匹配（支持 `¹` 上标）
- 新增 `_extract_vmax_fallback()`：三层回退策略
  - 第一层：OCR 容错模式匹配
  - 第二层：Vmax 关键词 + 科学记数法数值搜索（150字符窗口）
  - 第三层：E 记数法搜索
  - 第四层：普通数字 + 速率单位匹配

### 4. 修复 Vmax 提取条件逻辑
- 将 `if Km is None` 改为 `if Km is None or Vmax is None`
- 确保 Km 已提取但 Vmax 未提取时仍会尝试文本和表格提取

### 5. 在动力学提取流程中应用 OCR 归一化
- `_extract_kinetics_from_text`：先归一化再匹配，标准模式失败后调用回退
- `_extract_kinetics_from_flattened_table`：归一化表头和值
- `_extract_kcat_from_text`：归一化后匹配

### 6. 图注 Vmax 提取增强
- 文件：[figure_handler.py](file:///d:/ocrwiki版本/single_main_nanozyme/figure_handler.py)
- 导入并使用 `_normalize_ocr_scientific` 和 `_parse_scientific_notation`
- 新增科学记数法 Vmax 图注模式 `vmax_sci_pat`
- 在图注提取前先归一化

## 未改动内容
- `numeric_validator.py`：未修改，量级范围检查逻辑不变
- `consistency_guard.py`：未修改，归因检查逻辑不变
- `single_record_assembler.py`：未修改，记录组装逻辑不变
- `CandidateRecaller` 的 OCR 修复逻辑：之前已实现，本次未改动

## 验证方式
- 32 个单元测试全部通过
- OCR 归一化测试：8 种典型 OCR 破坏模式全部正确修复
- 科学记数法解析测试：9 种格式全部正确解析
- Vmax 回退提取测试：6 种 OCR 破坏文本全部正确提取
- 端到端测试（10 篇文献，无 LLM/VLM）：Vmax 提取率从 1/10 提升到 3/10，其中 2 个通过回退提取

## 风险与后续
- 回退提取可能产生误提取（如将非 Vmax 的科学记数法数值误判为 Vmax），需通过 `numeric_validator` 的量级检查过滤
- 部分文献的 Vmax 数据仅在 VLM body_context 中，禁用 VLM 时无法提取，后续可考虑将 body_context 也纳入文本提取范围
- `2021_73e66402` 的 Vmax 单位 `Ms` 被损坏，需要更鲁棒的单位归一化
- 下一步建议：启用 LLM 模式进行全链路测试，验证 OCR 归一化与 LLM 提取的协同效果
