# LLM-First 材料识别 + 预处理升级 设计文档

## 日期
2026-05-09

## 背景
系统对 4-5.pdf（R-MnCo2O4 纳米管论文）的提取完全失败：
- 材料名识别为 "ABSTRACT"
- 多体系（MnCo2O4 vs R-MnCo2O4）被合并
- 金属元素 "In" 错误（来自引用文献）
- 动力学数据无归属链
- 分析物识别错误（crystal violet 是探针，ascorbic acid 才是分析物）

根本原因：正则无法理解语义，LLM 被限制在规则之后做精炼。

## 设计目标
1. LLM 先理解论文语义，识别主纳米酶和关联体系
2. 表格保留行列结构，LLM 直接处理结构化表格
3. 动力学数据关联到具体材料+底物
4. 应用提取区分探针/底物/分析物语义角色

## 架构变更

```
当前: PDF→预处理→正则候选→评分选1→规则提取→LLM精炼
目标: PDF→预处理(增强表格)→LLM材料识别→规则+LLM并行提取→归属校验→输出
```

## 4 个核心改动

### 改动1: LLM 材料识别器 (新模块 `material_identifier.py`)

**职责**: 从标题+摘要+前N个chunks中，用LLM识别主纳米酶和关联体系

**输入**: 
- title (str)
- abstract_chunks (List[str])
- first_n_chunks (List[str])

**输出**:
```python
{
    "primary_nanozyme": "R-MnCo2O4",
    "primary_description": "Reduced MnCo2O4 nanotubes with oxygen vacancies",
    "related_systems": [
        {
            "name": "MnCo2O4",
            "relationship": "pristine_counterpart",
            "description": "Original MnCo2O4 nanotubes without reduction"
        }
    ],
    "confidence": 0.95,
    "reasoning": "The title and abstract focus on R-MnCo2O4..."
}
```

**降级策略**: 当 LLM 不可用时，回退到 CandidateRecaller + NanozymeScorer

**集成点**: `SingleMainNanozymePipeline._extract()` 中，在 `self.recaller.recall(doc)` 之前调用

### 改动2: 预处理表格增强

**文件**: `nanozyme_preprocessor_midjson.py`

**变更**:
- `_build_table_extraction_task()` 保留完整 headers + rows 结构
- 表格标题关联增强：支持 "Table S1", "Table A1" 等补充材料编号
- 表格内容传递给 LLM TableExtractor 时保持 markdown 格式

**验证**: 确保 mid_task.json 中 tables 字段包含完整行列结构

### 改动3: 动力学归属链

**文件**: `extraction_agents.py`, `llm_structured_extractor.py`, `extraction_prompts.py`

**变更**:
- KineticsAgent 提取时标注 `material_variant` 字段
- LLM kinetics prompt 要求输出 `material_name` 字段
- `kinetics_list` 每项增加 `material_variant` 字段（可选，默认 null）
- kinetics_list 示例：
```json
[
    {"Km": 0.018, "Km_unit": "mM", "Vmax": 0.12, "Vmax_unit": "μM/s", "substrate": "TMB", "material_variant": "R-MnCo2O4"},
    {"Km": 0.05, "Km_unit": "mM", "Vmax": 0.17, "Vmax_unit": "μM/s", "substrate": "TMB", "material_variant": "MnCo2O4"}
]
```

### 改动4: 应用语义角色

**文件**: `extraction_prompts.py`, `application_extractor.py`

**变更**:
- LLM application prompt 增加语义角色区分说明：
  - probe molecule: 用于验证催化活性的分子（crystal violet, methylene blue, Rhodamine B）
  - substrate: 催化反应中被消耗的分子（TMB, H2O2, ABTS）
  - target_analyte: 应用中要检测的目标分子（ascorbic acid, glucose, dopamine）
- 规则提取增加探针分子黑名单
- ApplicationExtractor 过滤掉 target_analyte 为探针分子的结果

## 不改动的部分
- Schema 结构不变（selected_nanozyme 仍为单体系）
- CandidateRecaller 和 NanozymeScorer 保留作为降级
- ConsistencyGuard 保留
- NumericValidator 保留
- VLM 提取器保留

## 验证方式
1. 在 4-5.pdf 上运行（禁用缓存）
2. 对比人工提取的正确结果
3. 确认5类错误全部修复
4. 运行全量测试确保无回归
