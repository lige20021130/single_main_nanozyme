# 硬编码规则覆盖度测试与优化

## 更新时间
2026-05-02 22:30

## 更新类型
- 测试 / Bug 修复 / 功能优化

## 背景
对系统中所有涉及硬编码实现或存在规则局限性的模块进行全面的覆盖度测试。设计 621 项测试用例，覆盖 23 个类别，包括酶类型识别、应用类型分类、检测方法、缓冲液、机制、信号、材料组成解析、单位归一化、酶-应用兼容性、动力学提取、形貌术语、合成方法、样品类型、跨字段一致性、Schema 校验、证据分桶、标准化映射、底物关键词、掺杂模式、金属元素识别、OCR 归一化、分析物识别、载体材料等。

## 改动内容

### 1. 酶类型系统扩展 (M1/M15/M17)
- `_ENZYME_TYPE_PATTERNS`: 新增 phosphatase-like, nitroreductase-like, hydrolase-like, laccase-like, haloperoxidase-like, NADH-oxidase-like 模式及 ALP/NTR 缩写
- `_VALID_ENZYME_TYPES`: 新增 phosphatase-like, nitroreductase-like, hydrolase-like, esterase-like, glucose-oxidase-like, nuclease-like, glutathione-oxidase-like, cascade-enzymatic
- `_ENZYME_TYPE_NORMALIZE`: 新增 phosphatase/ALP, nitroreductase/NTR, hydrolase, laccase, haloperoxidase, tyrosinase, nuclease, cascade enzymatic 映射
- `EnzymeType` 枚举: 新增 GLUCOSE_OXIDASE, GLUTATHIONE_OXIDASE, NUCLEASE, TYROSINASE, CASCADE_ENZYMATIC
- `ENZYME_REGISTRY`: 为新增枚举添加关键词/底物/检测方法元数据
- `_ENZYME_ALIAS_MAP`: 新增 GOx, ALP, NTR, GSHOx 别名映射
- `_ALIASES_TO_CANONICAL`: 新增所有新酶类型的别名

### 2. 应用类型系统扩展 (M2/M2B)
- `_APP_TYPE_KEYWORDS`: sensing 新增 ELISA/immunoassay/lateral flow/paper-based; therapeutic 新增 tumor ablation/各类 therapy; antibacterial 新增 antiviral/antifungal; environmental 新增 water purification/soil remediation/air purification; antioxidant 新增 radioprotect; biofilm 新增 quorum sensing inhibition
- `_APP_TYPE_NORMALIZE`: 新增 immunotherapy, gene therapy, photoacoustic imaging

### 3. 检测方法扩展 (M3)
- `_ASSAY_METHOD_PATTERNS`: 新增 electrochemiluminescent (优先于 electrochemical), cyclic voltammetry, DPV/SWV/EIS/CV 缩写, differential/square wave voltammetry, impedance spectroscopy, photoelectrochemical

### 4. 缓冲液系统重构 (M4)
- `_BUFFER_PATTERNS`: 新增 ammonium-acetate, Tris-EDTA, Tris-acetate, HEPES-NaOH, Britton-Robinson (全称), borate, carbonate-bicarbonate, glycine-NaOH, PIPES, CHES, CAPS
- 修复匹配优先级: 更具体的模式排在更通用的模式之前

### 5. 机制系统扩展 (M5)
- `_MECHANISM_PATTERNS`: 修复 M-Nx site 模式 (去除 \b 前缀, 支持 Fe-N4/Co-Nx 格式), 新增 photo-Fenton, photocatalytic, sonocatalytic, piezocatalytic

### 6. 合成方法扩展 (M12)
- `_SYNTHESIS_METHODS`: 新增 atomic_layer_deposition, pulsed_laser_deposition, freeze_drying, ball_milling, spray_pyrolysis, 3d_printing, supercritical_drying
- 修复匹配优先级: spray_pyrolysis 在 pyrolysis 之前, sacrificial_template 在 template_method 之前
- calcination 模式新增 "calcined" 变体

### 7. 样品类型扩展 (M13)
- `_SAMPLE_TYPE_MAP`: 新增 river water, lake water, cerebrospinal fluid, CSF, sweat, interstitial fluid, soil, sediment, industrial effluent
- 修复匹配逻辑: 按关键词长度从长到短排序，避免 "water" 先于 "tap water" 匹配

### 8. 酶-应用兼容性表扩展 (M9)
- `_ENZYME_APP_COMPATIBILITY`: 新增 glucose-oxidase-like, phosphatase-like, laccase-like, esterase-like, nitroreductase-like, hydrolase-like, haloperoxidase-like, glutathione-oxidase-like, nuclease-like, cascade-enzymatic 的兼容应用类型

### 9. 载体材料扩展 (M23)
- `_SUPPORT_MATERIALS`: 新增 carbon cloth, carbon fiber, activated carbon, mesoporous carbon, biochar, COF
- 修复匹配逻辑: 按长度从长到短排序，避免 "carbon" 先于 "g-C3N4" 匹配

### 10. 动力学模式增强 (M10)
- `_KM_PATTERNS`: 新增 "Km value was" 模式, 所有模式添加 mmol/L/umol/L/nmol/L 单位支持
- `_KCAT_PATTERNS`: 所有模式添加 s\^-1/min\^-1 格式支持

### 11. 覆盖度测试套件 (test_coverage.py)
- 621 项测试用例，覆盖 23 个类别
- 多维度测试: 正面匹配、负面匹配、边界情况、变体识别、优先级验证

## 未改动内容
- VLM 提取逻辑
- LLM Refiner 核心逻辑
- 批量评估脚本
- 数据输出格式

## 验证方式
- 运行 `python test/test_coverage.py`
- 结果: 621 passed, 0 failed

## 风险与后续
- 新增的酶类型模式可能需要根据实际文献进一步调整
- 应用类型关键词匹配优先级问题（如 "quorum sensing inhibition" 先匹配 sensing 而非 biofilm_inhibition）需要后续优化匹配算法
- 部分非常规表述（如 "peroxidase mimicking"）仍未被模式覆盖，后续可考虑添加 mimetic/mimicking 变体
