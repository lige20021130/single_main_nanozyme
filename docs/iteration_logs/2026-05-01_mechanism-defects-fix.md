# 修复多个机制级提取缺陷

## 更新时间
2026-05-01 22:30

## 更新类型
- Bug 修复 / 重构

## 背景
系统审查发现多个机制级提取缺陷，涉及 Vmax 指数处理、晶体结构提取、PDF 解析流程、bucket 分配正则等。这些缺陷会导致数据提取错误或丢失。

## 改动内容

### 1. 修复 Vmax fallback 指数符号处理（高优先级）
- **文件**: `single_main_nanozyme_extractor.py`
- **问题**: `_extract_vmax_fallback` 中对 OCR 归一化后的指数做了错误的"正变负"假设，正指数 Vmax 会被错误缩小若干数量级
- **修复**: 
  - 不再使用 `_parse_scientific_notation` 返回值判断正负，改为从完整匹配文本 `m.group(0)` 中检测负号
  - 2组和3组匹配统一使用 `match_has_minus` + `exp_clean` 双重检测
  - 添加 `_SUPERSCRIPT_TO_ASCII` 转换表，在 fallback 中将 Unicode 上标数字转为 ASCII

### 2. 修复晶体结构提取缺陷（高优先级）
- **文件**: `extraction_agents.py`, `single_main_nanozyme_extractor.py`
- **问题**: 
  - 晶面指数匹配后存入纯数字（如 `"111"`）而非格式化的 `"(111)"`
  - d-spacing 数值被误存为 crystal_structure
  - 结构名列表缺少 "rock salt", "zinc blende", "wurtzite", "graphitic" 等
- **修复**:
  - 统一3处晶体结构提取逻辑：先检测3位数字晶面 → 格式化为 `(111), (220)` 
  - 排除 d-spacing 数值（含小数点和 Å 的纯数字）
  - 补充6个缺失结构名

### 3. 修复 run_extraction.py PDF 解析流程（高优先级）
- **文件**: `run_extraction.py`
- **问题**: `--input PDF` 模式直接调用 `NanozymePreprocessor`，但缺少 `opendataloader_pdf.convert` 解析步骤
- **修复**: 在 `preprocess_pdf` 中先检查 JSON 是否存在，不存在则调用 `opendataloader_pdf.convert` 解析

### 4. 优化 kinetics bucket 正则
- **文件**: `single_main_nanozyme_extractor.py`
- **问题**: `_BUCKET_KEYWORDS["kinetics"]` 缺少 `M·s⁻¹`、`M/s` 等速率单位模式
- **修复**: 补充 `Ms⁻¹`、`M·s⁻¹`、`M/?s`、`[mμunp]?M/?s`、`catalytic efficiency`、`steady state` 等模式

### 5. 提取 _RATE_UNITS 为共享常量
- **文件**: `single_main_nanozyme_extractor.py`, `extraction_agents.py`
- **问题**: `_RATE_UNITS` 在3处重复定义，修改时极易遗漏
- **修复**: 提取为模块级 `frozenset` 常量，补充 `nM/s` 等缺失单位

### 6. 清理残留 print() 调试语句
- **文件**: `extraction_agents.py`
- 删除 `_extract_kinetics_from_flattened_table` 中的 `print(f'[TRACE]...')` 

## 未改动内容
- `_normalize_ocr_scientific` 函数主体逻辑未改（保持 Unicode 上标输出用于显示）
- `_VMAX_PATTERNS` 主逻辑未改（由 `_VMAX_OCR_PATTERNS` + fallback 覆盖 OCR 场景）
- Dashboard GUI 未改
- Cross-validation / Consistency agents 未改

## 验证方式
- 语法检查：3个修改文件全部通过 `py_compile`
- 导入测试：`extraction_agents`、`extraction_pipeline` 全部导入成功
- Vmax fallback 单元测试：
  - 负指数 `1.5 × 10⁻⁸` → `1.5e-8` ✅
  - 正指数 `2.3 × 10³` → `2.3e3` ✅
  - E记数法 `3.45e-7` → `3.45e-7` ✅
  - ASCII减号 `4.56 × 10-3` → `4.56e-3` ✅
  - maximum velocity `8.72 × 10⁻⁵ M·s⁻¹` → `8.72e-5` ✅

## 风险与后续
- `_SUPERSCRIPT_TO_ASCII` 转换可能影响 `_VMAX_OCR_PATTERNS` 中使用 Unicode 上标的模式匹配，但测试验证通过
- 后续建议：对 `_VMAX_PATTERNS` 主逻辑也做类似的 Unicode 上标数字兼容
- 后续建议：将晶体结构提取逻辑提取为共享函数，避免3处维护不一致
