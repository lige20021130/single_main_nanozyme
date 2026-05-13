# 泛化能力优化：正则模式与提取鲁棒性增强

## 更新时间
2026-05-12 18:00

## 更新类型
- 功能开发 / Bug 修复

## 背景
系统在处理多样化文献表达时存在泛化盲点：
- Km/Vmax/kcat 下标变体（K_m, V_max, k_cat）和表观形式（Km,app）无法匹配
- LOD/线性范围缺少点积单位（μg·mL⁻¹）和更多浓度单位
- 酶类型缺少 mimic 表达（peroxidase-mimicking）和新酶类型（ferroxidase-like, superoxide-oxidase-like）
- 应用提取缺少治疗类（photothermal/chemodynamic therapy）和细胞保护类
- pH/温度/尺寸模式缺少等号记法、室温映射等变体
- OCR 噪声（⁻¹上标、控制字符）处理不完整
- catalytic efficiency 模式不支持 "of" 操作符
- superoxide oxidase-like 被 oxidase-like 模式先匹配

## 改动内容

### single_main_nanozyme_extractor.py
1. **Km 模式增强**：添加下标变体（K_m, K_M）、表观形式（Km,app, Km(app)）、更多单位
2. **Vmax 模式增强**：添加下标变体（V_max）、点积单位（M·s⁻¹）、科学计数法
3. **kcat 模式增强**：添加下标变体（k_cat）、表观形式、催化效率
4. **LOD 模式增强**：添加点积单位（μg·mL⁻¹, ng·mL⁻¹）、更多浓度单位
5. **线性范围模式增强**：添加更多浓度单位
6. **酶类型模式增强**：
   - 添加 mimic 表达（peroxidase-mimicking → peroxidase-like）
   - 添加新酶类型（ferroxidase-like, glutathione-reductase-like, superoxide-oxidase-like, peroxynitritase-like, NADH-peroxidase-like, thioredoxin-reductase-like, glutathione-transferase-like, monooxygenase-like, dioxygenase-like, sulfite-oxidase-like）
   - **修复模式顺序**：将 superoxide oxidase-like 移到 oxidase-like 之前，避免被先匹配
7. **catalytic efficiency 模式**：添加 "of" 操作符支持
8. **_normalize_ocr_scientific 增强**：添加 ⁻¹→-1, ⁻²→-2, ⁻³→-3, ⁺¹→+1, ⁺²→+2 转换

### nanozyme_models.py
1. **EnzymeType 枚举扩展**：添加 FERROXIDASE, GLUTATHIONE_REDUCTASE, SUPEROXIDE_OXIDASE, PEROXYNITRITASE, NADH_PEROXIDASE, THIOREDOXIN_REDUCTASE, GLUTATHIONE_TRANSFERASE, MONOOXYGENASE, DIOXYGENASE, SULFITE_OXIDASE
2. **_ENZYME_ALIAS_MAP 扩展**：添加 mimic 表达、缩写映射

### application_extractor.py
1. **therapeutic 模式扩展**：添加 photothermal/chemodynamic/sonodynamic/photodynamic/radio/chemo/immuno/starvation/gas therapy
2. **新增 cytoprotection 类型**：cytoprotect, cell protect, neuroprotect, cardioprotect
3. **新增 bioimaging 类型**：bioimag, cell imag, fluorescen imag, MR imag, photoacoustic imag
4. **新增 sterilization/heavy_metal_detection/impedimetric 模式**

### consistency_agent.py
1. **分析物-酶类型不兼容性检查扩展**：添加 oxidase-H₂O₂, glucose-oxidase-H₂O₂, peroxidase-superoxide 不兼容

### numeric_validator.py
1. **单位归一化增强**：添加点积单位（·）到斜杠（/）的转换

### llm_structured_extractor.py
1. **JSON 解析增强**：添加 _pre_clean_json 预处理（控制字符、尾逗号、μ变体）
2. **_fix_json_string 增强**：更好的未闭合花括号修复

### test/test_regex2.py（新增）
1. 57 个泛化测试用例，覆盖所有增强点

## 未改动内容
- extraction_pipeline.py：管道流程未变
- api_client.py：API 调用逻辑未变
- vlm_extractor.py：VLM 提取逻辑未变
- GUI 层：未涉及

## 验证方式
- `python -m pytest test/test_regex2.py -v`：57 passed
- `python -m pytest tests/ -v`：152 passed，无回归

## 风险与后续
- 新增酶类型枚举需要同步到 schema_constraints.py 的验证逻辑
- 点积单位归一化可能在极端情况下误转换，需观察实际提取结果
- 后续可考虑添加更多 LOD/LOQ 交叉引用模式
