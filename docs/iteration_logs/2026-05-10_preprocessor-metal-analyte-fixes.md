# 修复预处理器丢弃关键句子、金属元素误识别、分析物兼容性误判

## 更新时间
2026-05-10 11:45

## 更新类型
- Bug 修复

## 背景
4-5.pdf提取验证中发现以下问题：
1. 预处理器`_enforce_text_budget`阶段裁剪掉了包含"ascorbic acid (AA)"的关键句子，导致目标分析物信息丢失
2. `_extract_metal_elements`使用全名子串匹配，"reduced"误匹配Re，"RMnCo2O4"误匹配Ce
3. 分析物兼容性检查使用精确匹配，"ascorbic acid (AA)"不等于"ascorbic acid"，产生误报警告
4. VLM返回的Vmax值（3.3×10^11 M/s）明显异常但未被清除

## 改动内容

### nanozyme_preprocessor_midjson.py
- 在`_HARD_RECALL_PATTERNS`中添加两条泛化模式：
  - `detect \w+`：匹配任何"detect + 分析物"的句子，确保应用检测信息不被budget裁剪
  - `LOD/detection limit + 浓度单位`：匹配带单位的检测限信息
- 这两个模式是泛化的，不针对特定分析物名称

### extraction_agents.py
- `_extract_metal_elements`方法重写：
  - 旧方法：在完整材料名（如"reduced MnCo2O4"）中做子串匹配，导致"Re"匹配"reduced"、"Ce"匹配"RMnCo2O4"
  - 新方法：先用正则`([A-Z][a-z]?\d*(?:[A-Z][a-z]?\d*)+)`提取化学式部分（如"MnCo2O4"），再用`[A-Z][a-z]?`分词提取元素符号
  - 结果：从['Ce', 'Co', 'Mn', 'Re']修正为['Co', 'Mn']

### numeric_validator.py + single_main_nanozyme_extractor.py
- 分析物兼容性检查逻辑同步更新：
  - 添加括号缩写清理：`re.sub(r'\s*\(.*?\)\s*', '', analyte)` → "ascorbic acid (AA)" → "ascorbic acid"
  - 添加子串匹配：`any(c in analyte.lower() for c in compat_lower)`
  - 三重匹配策略：精确匹配 → 清理后匹配 → 子串匹配

### single_main_nanozyme_extractor.py
- `_final_kinetics_validation`添加Vmax异常大值检查：
  - 当Vmax单位为M/s且绝对值>1e-3时，清除并标记needs_review
  - 纳米酶Vmax典型范围：10^-9 ~ 10^-4 M/s，超过1e-3 M/s明显异常

## 未改动内容
- VLM提取器本身的科学计数法解析（VLM模型返回值已错误，无法在提取器层面修复）
- 表征方法完整性（需要LLM提取增强，不在本次修复范围）
- 合成方法细节（需要LLM提取增强，不在本次修复范围）

## 验证方式
- 重新运行4-5.pdf提取（--no-cache），验证以下改进：
  - ✅ 材料名: ABSTRACT → reduced MnCo2O4 (RMnCo2O4)
  - ✅ metal_elements: ['In'] → ['Co', 'Mn']
  - ✅ target_analyte: 'catalytic reactions'/'crystal violet' → 'ascorbic acid (AA)'
  - ✅ ascorbic acid兼容性警告消除
  - ✅ Vmax异常值被自动清除
  - ✅ kinetics_list有结构化数据

## 风险与后续
- hard recall模式`detect \w+`可能匹配到"detect the signal"等非分析物句子，但这类句子在budget裁剪中被保留不会造成数据错误，只是多占预算
- 表征方法（XRD, XPS, EDX, TEM, HRTEM）仍不完整，需要增强LLM结构化提取的morphology prompt
- 合成方法仍为"general synthesis"，需要增强LLM结构化提取的synthesis prompt
- 多体系动力学归属（R-MnCo2O4 vs MnCo2O4, SERS vs UV-vis）仍需改进
