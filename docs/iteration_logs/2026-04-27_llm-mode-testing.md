# LLM大模型模式启用与2021批次文献测试

## 更新时间
2026-04-27 22:20

## 更新类型
- 功能开发 / 测试

## 背景
用户要求启用大模型辅助进行文献提取测试。系统已有完整LLM调用框架（_call_llm + _merge_llm），config.yaml中enable_llm=true，但之前测试脚本未启用。现在直接启用LLM模式进行全链路测试。

## 改动内容

### 1. 启用LLM模式
- `batch_test_2021.py`添加`--llm`参数支持
- APIClient生命周期管理：在main()中创建一次client，传递给所有提取操作
- 正确使用`async with` / `__aenter__` / `__aexit__`管理session

### 2. LLM材料名清洗
- 新增`_LLM_NAME_FIXES`：修复LLM输出中的编码问题
  - FeeNeC → Fe-N-C
  - CueNeC → Cu-N-C
  - FeeN → Fe-N（不匹配FeeNa等正常词）
  - -NeC → -N-C
  - -Ne → -N
- 新增`_clean_llm_name()`方法
- 在`_merge_llm()`中对材料名应用清洗

### 3. 新增过滤规则
- 疾病名黑名单`_DISEASE_NAMES`：SARS, COVID等14项（-40分惩罚）
- 非材料短语黑名单`_NON_MATERIAL_PHRASES`："single atom nanozyme"等9项（-40分惩罚）
- 酶类型+纳米酶组合过滤：POD-like nanozymes等

### 4. 新增酶类型模式
- cascade-enzymatic：匹配"cascade enzymatic activity"
- glutathione-oxidase-like：匹配"glutathione oxidase-like"
- glucose-oxidase-like：匹配"GOx-like"和"glucose oxidase-like"

## 测试结果

### 10篇2021批次文献LLM模式测试

| # | 文献 | 规则模式材料 | LLM模式材料 | 酶类型 | Km | 应用 |
|---|------|------------|------------|--------|-----|------|
| 1 | Mn/PSAE | Mn/PSAE | Mn/PSAE | POD+CAT | None | 1 |
| 2 | Pd单原子 | metal nanoparticles | **Pd SAzyme** | peroxidase-like | None | 0 |
| 3 | Cu-HCF | Cu-HCF | Cu-HCF SSNEs | GSHOx+POD | None | 1 |
| 4 | DNA/Fe | DNA/Fe | **Fe-N-C SAzymes** | peroxidase-like | None | 1 |
| 5 | Cu-N碳片 | Cu-N | **Cu-NC-700** | peroxidase | 0.077 | 4 |
| 6 | MIL-101 | MIL-101(CuFe) nanozyme | MIL-101(CuFe) nanozyme | POD-like | None | 1 |
| 7 | Ti3C2 | Ti3C2 | **Co-doped Ti3C2 MXene** | peroxidase-like | None | 1 |
| 8 | ZnBNC | ZnBNC | ZnBNC | peroxidase | None | 1 |
| 9 | CDs@NC | CDs@NC-x | **CDs@NC-3** | peroxidase-like | None | 1 |
| 10 | 解析失败 | - | - | - | - | - |

**成功率：9/10（90%）**

### LLM vs 规则模式对比

| 指标 | 规则模式 | LLM模式 |
|------|---------|---------|
| 材料选择精确度 | 5/9 (56%) | **8/9 (89%)** |
| Km提取 | 0/9 | **1/9** |
| 应用质量 | 空壳条目多 | **有具体analyte/LOD/method** |
| 重要数值 | 0个 | **8个** |

### LLM模式亮点
- Cu-NC-700：Km=0.077 mM + substrate=TMB + H2O2 LOD=10nM + glucose LOD=100nM
- Co-doped Ti3C2 MXene：从"Ti3C2"精确到完整材料名
- Cu-HCF SSNEs：酶类型精确到"glutathione oxidase (GSHOx) and peroxidase (POD)"
- Fe-N-C SAzymes：从"DNA/Fe"精确到正确的单原子纳米酶名称

## 未改动内容
- `nanozyme_preprocessor_midjson.py`：未修改
- `extraction_pipeline.py`：未修改
- `pdf_basic_gui.py`：未修改
- `config.yaml`：未修改

## 风险与后续
- **LLM API依赖**：依赖智谱BigModel API（glm-4.7），需确保API key有效
- **FeeNeC编码问题**：LLM有时将Fe-N-C输出为FeeNeC，清洗规则已添加但可能不完整
- **VLM未测试**：当前仅启用LLM，VLM模式（图片分析）待后续测试
- **Km提取仍有限**：10篇中仅1篇成功提取Km，大部分Km数据在图片中需VLM辅助
