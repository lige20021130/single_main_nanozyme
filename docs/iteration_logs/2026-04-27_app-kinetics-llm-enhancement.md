# 应用提取增强、Km/Vmax优化、LLM/VLM集成

## 更新时间
2026-04-27 21:30

## 更新类型
- 功能开发 / Bug 修复

## 背景
用户要求三个方向改进：1) 应用信息提取聚焦医学/环境检测方向，未找到时标注"当前文献未包含相关内容"；2) Km/Vmax提取率低需系统性优化；3) 启用大模型能力（LLM/VLM）。

## 改动内容

### 1. 应用提取增强（single_main_nanozyme_extractor.py）

- **扩展应用关键词**：添加医学（diagnos, therapeutic, antitumor, antibacterial, wound heal, cytoprotect等）、环境（pollutant, heavy metal, pesticide, environmental, drinking water等）、生物标志物（glucose, cholesterol, uric acid, dopamine, cysteine等）关键词
- **新增target_analyte提取**：3组正则模式提取检测目标物（"detection of glucose"、"glucose"、"xanthine"等）
- **新增应用分类**：detection, therapeutic, environmental, diagnostic 四类
- **新增检测方法提取**：colorimetric, fluorescent, electrochemical, smartphone-based
- **新增sample_type映射**：serum→serum, wine→food, river→environmental_water等
- **去空壳机制**：只有包含实质信息（LOD/线性范围/analyte/sample_type）或application_type的条目才保留
- **去重机制**：基于(application_type, target_analyte, detection_limit, linear_range)四元组去重
- **未找到标注**：applications为空时设置`applications_note="当前文献未包含相关内容"`

### 2. LOD/线性范围正则增强

- **LOD模式扩展**：3组模式支持"LOD of"、"LOD (36 nM)"、"LOD was 36 nM"等格式
- **线性范围模式扩展**：2组模式支持"calibration range"、括号格式等

### 3. Km/Vmax扁平化表格解析

- **新增 `_extract_kinetics_from_flattened_table` 方法**：解析多行表格文本（用制表符/多空格分隔列）
- **新增 `_try_parse_inline_table` 方法**：解析单行内联表格文本（如"Catalyst Substrate Vmax [10⁻⁸ M s⁻¹] Km (mM) HRP TMB 10.8 0.379 Nanosized CuS TMB 76.4 0.064"）
- **调用链**：规则文本提取 → 扁平化表格解析 → 表格结构化值提取

### 4. VLM集成到新系统

- **新增 `_call_vlm` 方法**：遍历vlm_tasks，调用VLMExtractor提取每张图的信息
- **新增 `_merge_vlm` 方法**：将VLM结果合并到record中
  - 粒径/表面积/ζ电位等→important_values（needs_review=True）
  - 动力学数值→important_values（不进入kinetics，遵守HARD RULE #10）
  - 传感性能参数→important_values
  - 形貌/尺寸→selected_nanozyme
- **管道主流程**：LLM调用后、数值验证前，调用VLM

### 5. LLM/VLM启用

- **测试脚本更新**：`full_pipeline_test.py`添加`--llm`、`--vlm`、`--force`命令行参数
- **APIClient初始化**：使用`async with APIClient() as client`确保session正确初始化
- **降级逻辑**：LLM/VLM失败时自动降级为规则模式，不崩溃

### 6. 数值验证增强

- **Vmax空字符串检查**：Vmax为空字符串时设为None并添加警告
- **Vmax负值检查**：保持原有逻辑

## 未改动内容
- `nanozyme_preprocessor_midjson.py`：未修改
- `extraction_pipeline.py`：未修改
- `pdf_basic_gui.py`：未修改
- `nanozyme_models.py`：未修改
- `config.yaml`：未修改（enable_llm/enable_vlm已默认为true）

## 验证方式
- 32个单元测试全部通过
- 11篇主文PDF规则模式全链路测试：
  - 材料选择10/11正确（91%）
  - 酶类型11/11全部检测到（100%）
  - Km提取4/11成功（48: 2.3mM, 69-70: 0.064mM, 90: 2.0mM, 29-34: 部分匹配）
  - 应用提取：target_analyte成功提取（Cysteine, glucose, H2O2, dopamine, ascorbic acid等），method成功提取（colorimetric, fluorescent, electrochemical）
  - LOD提取：90.pdf成功提取36 nM
  - applications_note标注：无应用的文献正确标注
- LLM模式测试：69-70.pdf LLM调用成功，Km=0.06, Vmax=76.4

## 风险与后续
- **LLM API依赖**：当前使用智谱BigModel API，需确保API key有效
- **VLM图片路径**：VLM调用需要图片文件存在于本地，PDF解析后图片路径需正确
- **Km/Vmax仍有7篇未提取**：部分论文的Km/Vmax数据在图片中（需要VLM），或格式过于特殊
- **target_analyte提取精度**：部分analyte名称过长（如"antioxidants based on the"），需后续优化截断逻辑
