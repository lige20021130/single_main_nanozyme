# 纳米酶文献提取系统 — 优化修复 Spec

## 版本
v1.0 | 2026-05-01

## 目标
将系统从"原型-产品过渡期"推进到"可跑数据集、可出科研图"的成熟度

---

## P0: 批量评估框架（无此能力则无法量化任何改进）

### T0-1: 构建 Gold Standard 标注数据集
- **输入**: 20-30篇代表性纳米酶论文PDF
- **输出**: 每篇论文的 `gold_standard.json`，与 `EMPTY_RECORD` schema 对齐
- **标注字段**: name, enzyme_like_type, Km, Vmax, Km_unit, Vmax_unit, substrate, optimal_pH, optimal_temperature, synthesis_method, size, morphology, crystal_structure, application_type, detection_limit
- **格式**: 与 `validate_schema` 输出完全一致，便于自动对比
- **文件**: `eval/gold_standards/`

### T0-2: 自动化评估脚本
- **功能**:
  - 逐字段对比提取结果 vs gold_standard
  - 计算 Precision / Recall / F1（按字段、按字段组、全局）
  - 数值字段额外计算 MAE（平均绝对误差）和量级正确率
  - 生成评估报告 JSON + Markdown
- **数值匹配规则**:
  - 精确匹配: 字符串字段完全一致
  - 数值匹配: |extracted - gold| / |gold| < 0.1 视为正确
  - 单位匹配: 归一化后比较
  - 部分匹配: 材料名子串包含
- **文件**: `eval/evaluate.py`

### T0-3: 批量提取+评估一键脚本
- **功能**: 输入PDF目录 → 批量提取 → 自动评估 → 生成报告
- **文件**: `eval/run_eval.py`

---

## P1: Schema 与提取逻辑优化

### T1-1: 多底物动力学支持
- **问题**: 当前 `kinetics` 是单对象，多底物论文只保留最后一个 Km/Vmax
- **方案**:
  - `kinetics` 改为列表 `kinetics_list: [{Km, Km_unit, Vmax, Vmax_unit, substrate, source}, ...]`
  - 保留 `kinetics` 作为默认取第一个元素的兼容字段
  - 规则提取时收集所有底物的 Km/Vmax 对
  - LLM prompt 中明确要求按底物分组输出
- **影响文件**: `single_main_nanozyme_extractor.py`, `extraction_agents.py`, `cross_validation_agent.py`, `consistency_agent.py`, `numeric_validator.py`

### T1-2: 应用类型标准分类体系
- **问题**: `application_type` 是自由文本，无法做统计
- **方案**:
  - 定义标准枚举: `sensing`, `therapeutic`, `antibacterial`, `environmental`, `antioxidant`, `biofilm_inhibition`, `other`
  - 在 RuleExtractor 中添加分类映射表
  - LLM prompt 中列出完整枚举
  - ConsistencyAgent 中添加归一化
- **影响文件**: `single_main_nanozyme_extractor.py`, `consistency_agent.py`

### T1-3: 材料组成结构化
- **问题**: `composition` 是纯文本，无法做元素级统计
- **方案**:
  - 新增 `composition_structured`: `{core: str, dopants: [str], support: str, organic_component: str}`
  - 规则提取: 从材料名中解析（如 "Fe-N-C SAzyme" → core="Fe", dopants=["N"], support="C"）
  - LLM prompt: 要求输出结构化 composition
  - 保留 `composition` 自由文本字段兼容
- **影响文件**: `single_main_nanozyme_extractor.py`

### T1-4: 纯规则字段补强
- **问题**: conditions/buffer/assay_method/signal/mechanism 完全依赖 LLM
- **方案**:
  - `assay_method`: 添加正则匹配 UV-vis/fluorescence/electrochemical/SERS/colorimetric
  - `signal`: 添加关键词匹配 absorbance/fluorescence/current/color change
  - `conditions.buffer`: 添加正则匹配 NaAc/HAc/PBS/citrate/Tris 等缓冲液
  - `mechanism`: 添加 ROS 类型检测 + Fenton/Haber-Weiss 关键词
- **影响文件**: `single_main_nanozyme_extractor.py`

---

## P2: VLM 与图文一致性增强

### T2-1: VLM 动力学值直接进入 kinetics（有条件）
- **问题**: VLM Km/Vmax 默认只进 important_values，不进入 kinetics
- **方案**:
  - 当 rule 和 LLM 的 Km 均为空时，VLM 值直接填入 kinetics（标记 source="vlm"）
  - 当 rule 有值但 VLM 值差异 <20% 时，视为确认信号，提高 confidence
  - 当 rule 有值但 VLM 值差异 >50% 时，保留 rule 值，VLM 值进 important_values
- **影响文件**: `single_main_nanozyme_extractor.py` (_merge_vlm)

### T2-2: 多图间一致性检查
- **问题**: 同一材料在不同图中的 Km 值可能不同，无检测机制
- **方案**:
  - 收集所有 VLM 结果中的 Km/Vmax 值
  - 同一参数多值时检查一致性（差异 >30% 标记 warning）
  - 多值时取中位数或标记 needs_review
- **影响文件**: `single_main_nanozyme_extractor.py`

### T2-3: VLM 任务智能选择
- **问题**: 当前基于图注关键词过滤，可能遗漏无图注的高价值图
- **方案**:
  - 添加图片类型预判：基于图片文件名、所在页面位置、周围文本
  - 优先选择：包含 kinetics 曲线、pH/温度曲线、传感性能图的图片
  - 限制：每篇论文最多处理 8 张图（避免 API 成本过高）
- **影响文件**: `single_main_nanozyme_extractor.py`

---

## P3: 数据一致性增强

### T3-1: Km-Vmax 底物一致性检查
- **问题**: Km 和 Vmax 可能来自不同底物但被存入同一 kinetics 对象
- **方案**:
  - 在 NumericValidator 中添加：如果 Km 的 substrate 与 Vmax 的 substrate 不同，拆分为两条 kinetics 记录
  - 在 ConsistencyAgent 中添加跨字段检查
- **影响文件**: `numeric_validator.py`, `consistency_agent.py`

### T3-2: 应用-酶类型一致性检查
- **问题**: peroxidase-like 材料不应有 glucose 直接检测应用
- **方案**:
  - 定义酶类型-应用类型兼容矩阵
  - 不兼容时标记 warning，不删除
- **影响文件**: `consistency_agent.py`

### T3-3: validate_schema 增强
- **问题**: 当前不验证 applications/important_values 内部结构
- **方案**:
  - 验证 applications 每个元素包含至少 application_type
  - 验证 important_values 每个元素包含 name + value
  - 验证 enzyme_like_type 在已知枚举内
  - 验证数值字段不是字符串
- **影响文件**: `single_main_nanozyme_extractor.py`

---

## P4: 科研可视化与批量报告

### T4-1: 批量提取统计报告生成器
- **功能**:
  - 输入: 批量提取结果目录
  - 输出: 统计报告 Markdown + 数据汇总 CSV
  - 统计项: 总论文数、成功率、各字段非空率、Km/Vmax提取率、酶类型分布、应用分布
  - 识别常见提取失败模式
- **文件**: `eval/batch_report.py`

### T4-2: 科研绘图脚本集
- **功能**:
  - `plot_km_distribution.py`: Km 分布直方图（自动单位统一化）
  - `plot_enzyme_type_pie.py`: 酶类型分布饼图
  - `plot_ph_temperature_scatter.py`: pH/温度最优值散点图
  - `plot_lod_boxplot.py`: LOD 分布箱线图（按应用类型分组）
  - `plot_extraction_heatmap.py`: 各字段提取率热力图
- **依赖**: matplotlib, pandas
- **文件**: `eval/plots/`

### T4-3: 单位统一化工具
- **功能**:
  - 将所有 Km 统一为 mM
  - 将所有 Vmax 统一为 M·s⁻¹
  - 将所有 size 统一为 nm
  - 将所有 detection_limit 统一为 μM
  - 处理科学计数法
- **文件**: `eval/unit_normalizer.py`

---

## 实施优先级与依赖关系

```
T0-1 (Gold Standard) ──→ T0-2 (评估脚本) ──→ T0-3 (一键脚本)
                                                    │
                                                    ▼
T1-1 (多底物) ─────────────────────────────→ T4-1 (批量报告)
T1-2 (应用分类) ───────────────────────────→ T4-2 (绘图脚本)
T1-3 (组成结构化) ─────────────────────────→ T4-2
T1-4 (规则补强) ───────────────────────────→ T0-2 (提高baseline)

T2-1 (VLM→kinetics) ──→ T2-2 (多图一致性)
T2-3 (VLM智能选择)

T3-1 (底物一致性) ──→ T3-3 (schema增强)
T3-2 (应用-酶一致性)

T4-3 (单位统一) ──→ T4-2 (绘图脚本)
```

## 预期成果

| 阶段 | 完成后能力 | 预计工作量 |
|------|-----------|-----------|
| P0 完成 | 可量化评估提取准确率，有 baseline 数据 | 中 |
| P1 完成 | 多底物支持、应用分类、组成结构化、规则补强 | 大 |
| P2 完成 | VLM 值有效利用、多图一致性 | 中 |
| P3 完成 | 数据一致性全面保障 | 小 |
| P4 完成 | 可直接生成科研图表 | 中 |

## 风险

1. **Gold Standard 标注成本高**: 需要领域专家逐篇标注，建议先标 10 篇做 pilot
2. **多底物 Schema 变更**: 向后不兼容，需要迁移脚本处理已有结果
3. **VLM 值直接进 kinetics**: 可能引入图片误读值，需严格条件控制
4. **LLM prompt 枚举约束**: 枚举过严可能遗漏罕见类型，过宽则失去约束效果
