# 多项提取质量修复 — LLM冲突、kcat推导、单位归一化

## 更新时间
2026-04-28 23:45

## 更新类型
- Bug 修复 / 功能开发

## 背景
LLM模式测试（10篇文献）显示：
- Km: 50%, Vmax: 40%, kcat: 0%
- LLM正确值被规则错误值拒绝（Vmax=1.5 vs LLM=1.51e-07）
- kcat提取率为0%
- Vmax单位损坏（Ms, mM·s⁻¹等）未归一化
- LLM返回科学记数法字符串（"2.06 × 10–3"）未被解析为数字

## 改动内容

### 1. 修复LLM值被规则错误值拒绝的bug
- 文件：[single_main_nanozyme_extractor.py](file:///d:/ocrwiki版本/single_main_nanozyme/single_main_nanozyme_extractor.py)
- 当LLM值与规则值差异>100x时，增加两种检测：
  - **截断检测**：规则值是否是LLM值科学记数法尾数的前几位（如1.5是1.51e-07的截断）
  - **量级检测**：规则值是否在合理量级范围外（如Km=5.55 > 1.0，不在Km范围内）
- 任一条件满足时，使用LLM值替代规则值

### 2. 增强kcat提取
- 新增3个OCR容错kcat模式（E记数法、科学记数法、catalytic constant）
- 新增从kcat/Km和Km反推kcat的逻辑
- kcat = kcat_Km × Km（单位统一为M后计算）

### 3. 修复LLM科学记数法字符串解析
- LLM返回"2.06 × 10–3"等字符串时，先用`_parse_scientific_notation`解析
- 解析失败时先用`_normalize_ocr_scientific`归一化再解析

### 4. 增强单位归一化
- 文件：[numeric_validator.py](file:///d:/ocrwiki版本/single_main_nanozyme/numeric_validator.py)
- `·` → `/`（而非空格），确保mM·s⁻¹ → mM/s
- 新增`⁻` → `^-`的通用替换
- 新增多种单位格式归一化：`M s-1` → `M/s`，`mM s^-1` → `mM/s`
- 在[single_record_assembler.py](file:///d:/ocrwiki版本/single_main_nanozyme/single_record_assembler.py)中调用`normalize_unit`统一归一化所有动力学单位

### 5. VLM速率限制优化
- 请求间隔从2秒增加到5秒
- 429错误时增加指数退避重试（5s, 10s, 20s, 30s）

## 验证方式
- 32个单元测试全部通过
- LLM模式测试（10篇文献）：
  - Km: 50% → 50%（但值更准确：FeN3P-SAzyme从5.55mM修正为2.06e-03mM）
  - Vmax: 40% → 40%（但GSHOx从错误1.5修正为1.97e-05）
  - 单位归一化：Ms→M/s, mM·s⁻¹→mM/s 全部正确

## 风险与后续
- kcat推导可能产生不准确的值（kcat/Km和Km可能对应不同底物）
- VLM仍严重受速率限制影响，需要API服务端配合
- 3篇文献（MGC803, Zr6, Fe-N）完全无动力学数据，可能需要VLM才能提取
- 下一步：解决VLM速率限制问题，启用VLM模式进行全链路测试
