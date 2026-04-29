# 文献验证与提取准确率修复

## 更新时间
2026-04-29 10:55

## 更新类型
- Bug 修复 / 功能开发

## 背景
使用 C:\Users\lcl\Desktop\wenxian-2021.6.1\-2021.6.1- 目录中的真实文献随机抽取10篇进行全链路验证，发现三个关键问题：
1. 候选材料选择错误 — AChE（生物酶）和 HUVEC（细胞系）被选为主纳米酶
2. important_values 中的动力学参数未回填到 kinetics
3. Km/Vmax 正则提取模式覆盖不足

## 改动内容

### 1. 扩展 `_REAGENT_NAMES` 排除列表 (single_main_nanozyme_extractor.py L156-174)
- 新增生物酶：AChE, ChOx, LOx, UOx, GalOx, AOx, XOD, Laccase, ALP 等
- 新增细胞系：HUVEC, HeLa, HEK293, MCF-7, 4T1, RAW264.7, HepG2, A549 等
- 新增培养基/试剂：RPMI, DMEM, FBS, HAcNaAc, NaAc-HAc
- 新增细菌：E. coli, S. aureus

### 2. 新增 `_backfill_kinetics_from_important_values` 方法 (L3714-3772)
- 在数值验证之后、profile推断之前调用
- 从 important_values 中识别 Km/Vmax/kcat/kcat_Km 相关条目
- 当 kinetics 对应字段为 None 时回填
- 支持 VLM_Km, LLM_Km, LLM_Km_alternative 等多种命名

### 3. 增强 Km 提取正则模式 (L267-281)
- 新增 "Km values to X and Y are A and B unit" 多底物模式
- 新增 "Km was calculated to be X unit" 计算值模式
- 新增 "Km... (X unit)" 括号内数值模式
- 新增 "Km of/toward X was Y unit" 介词模式

### 4. 增强 kcat/Km 提取模式 (L319-321)
- 新增 "s⁻¹ uM⁻¹" 等逆序单位格式支持
- 新增 "kcat/Km of/for X" 介词模式

## 验证结果

### 修复前（第一轮，LLM+VLM，10篇中8篇成功）
| 字段 | 填充率 |
|------|--------|
| selected_name | 8/8 (100%) |
| enzyme_type | 8/8 (100%) |
| Km | 2/8 (25%) |
| Vmax | 0/8 (0%) |
| kcat | 1/8 (12%) |
| applications | 8/8 (100%) |

**关键问题**：AChE 被选为 Co0.5Ni0.5Fe2O4-MMT 文献的主纳米酶

### 修复后（第二轮，LLM only，7篇已提取）
| 字段 | 填充率 |
|------|--------|
| selected_name | 7/7 (100%) |
| enzyme_type | 7/7 (100%) |
| Km | 2/7 (29%) |
| Vmax | 0/7 (0%) |
| kcat | 1/7 (14%) |
| applications | 7/7 (100%) |

**改进**：不再选择 AChE/HUVEC 等生物酶/细胞系作为主纳米酶

### Vmax=0% 的根因分析
逐篇检查发现，5篇有动力学数据的文献中，Vmax的具体数值**全部在补充材料(ESM)的表格中**，正文中只有定性描述（如"Km and Vmax are summarized in Table S3"）。这是当前系统的根本限制：
- 系统只解析主文PDF，无法访问ESM
- VLM严重限流(429)，无法从图片中提取表格数据
- LLM也无法从正文中提取不存在的数值

## 未改动内容
- 预处理流程（nanozyme_preprocessor_midjson.py）
- VLM提取逻辑（vlm_extractor.py）
- 数值验证逻辑（numeric_validator.py）
- 一致性检查逻辑（consistency_guard.py）

## 风险与后续
- Vmax提取率0%是ESM数据不可达的根本限制，需要考虑ESM PDF解析方案
- VLM限流问题严重，需要考虑更稳定的VLM API或本地部署
- 当前kinetics结构只支持一组Km/Vmax，但实际文献常对TMB和H2O2分别给出参数
- kcat_Km=1.88 的值应该是 1.88×10⁻⁸，科学记数法解析可能有问题，需进一步排查
