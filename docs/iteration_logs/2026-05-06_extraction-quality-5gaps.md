# 高质量提取能力增强 - 5大能力差距补齐

## 更新时间
2026-05-06

## 更新类型
- 功能开发

## 背景
当前系统面对各色文献时，规则提取覆盖率仅约40-50%，5大能力差距明显：酶类型检测（缺多酶/cascade/罕见类型）、合成条件提取（缺pH/溶剂/时间范围）、机制提取（仅18种模式）、应用提取（LOD/analyte不够）、全文回退（仅回退pH/温度/合成/形貌）。需要定向增强这些短板。

## 改动内容
- **single_main_nanozyme_extractor.py**：
  1. 酶类型检测：新增28种酶类型模式（multi-enzyme-like, tyrosinase-like, cellulase-like, amylase-like, protease-like, lipase-like, urease-like, ascorbate-oxidase-like, haloperoxidase-like, dehydrogenase-like, nuclease-like, invertase-like, chitinase-like, xylanase-like等）；扩展搜索范围到kinetics和application bucket
  2. 合成条件：新增6种温度模式（dried at, maintained at, reaction temperature等）；新增3种时间模式（时间范围, aged/stirred/incubated, overnight）；新增4种pH模式；新增3种溶剂模式；在_extract_synthesis_method中集成pH和溶剂提取
  3. 机制提取：从18种扩展到54种模式（新增sono-Fenton, electro-Fenton, single-atom catalysis, defect-mediated, sulfur/nitrogen vacancy, surface-mediated, interfacial catalysis, enzyme-mimicking, biomimetic, chemodynamic/photodynamic/sonodynamic, GSH depletion, water oxidation, oxygen evolution/reduction, hydrogen evolution, CO2 reduction, N2 fixation等）；扩展搜索范围到kinetics和application bucket
  4. 应用提取：新增2个应用类型（food_safety, drug_delivery）；扩展sensing/therapeutic/antibacterial/environmental/antioxidant关键词；新增9种analyte模式（蛋白质/抗生素/农药/毒素/肿瘤标志物/核酸/细菌/癌细胞）；新增3种LOD宽松模式（minimum detectable, sensitivity, could detect）；新增2种线性范围模式（working range, linear from）
  5. 全文回退：新增Km/Vmax动力学回退、酶类型回退、机制回退、应用回退（含LOD/analyte/linear_range）

## 未改动内容
- 管道架构未变
- LLM/VLM提取逻辑未变
- 交叉验证逻辑未变
- 一致性修正逻辑未变
- GUI未变

## 验证方式
- py_compile语法检查通过
- pytest 110个测试全部通过
- git push成功

## 风险与后续
- 新增模式可能产生误匹配，需在实际文献上验证
- 酶类型归一化映射（nanozyme_models.py）需要同步更新以支持新类型
- 机制提取目前只返回第一个匹配，多机制文献可能丢失
- 后续可考虑：多机制提取、模式优先级排序、误匹配过滤
