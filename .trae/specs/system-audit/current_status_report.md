# 纳米酶文献提取系统 — 当前状态审查报告

## 审查时间
2026-05-01

## 审查范围
完整工作流：规则提取 + LLM 增强 + VLM 图像提取 + 交叉验证 + 一致性守卫

---

## 一、Schema 字段提取覆盖率评估

### 1.1 各字段组提取方法归属

| 字段组 | 字段总数 | 规则可提取 | LLM可补充 | VLM可补充 | 完全无提取路径 |
|--------|---------|-----------|----------|----------|-------------|
| paper | 7 | 7(预处理器) | 0 | 0 | 0 |
| selected_nanozyme | 17 | 8 | 9 | 2(size/morphology) | 0 |
| main_activity.conditions | 4 | 0 | 4 | 0 | **0** |
| main_activity.pH_profile | 3 | 3 | 3 | 0 | 0 |
| main_activity.temperature_profile | 3 | 3 | 3 | 0 | 0 |
| main_activity.kinetics | 10 | 8 | 10 | 3(Km/Vmax/substrate) | 0 |
| main_activity(其他) | 5 | 2(enzyme_type/substrates) | 5 | 0 | 0 |
| applications | 7/条 | 2(type/LOD) | 7 | 2(LOD/linear_range) | 0 |
| diagnostics | 4 | 4(自动生成) | 0 | 0 | 0 |

### 1.2 关键发现：纯 LLM 依赖字段

以下字段**完全依赖 LLM**，规则提取无法覆盖，若 LLM 失败则为空：

- `selected_nanozyme.composition` — 材料组成
- `selected_nanozyme.metal_elements` — 金属元素
- `selected_nanozyme.dopants_or_defects` — 掺杂/缺陷
- `selected_nanozyme.characterization` — 表征手段列表
- `selected_nanozyme.stability` — 稳定性
- `main_activity.assay_method` — 检测方法
- `main_activity.signal` — 信号类型
- `main_activity.conditions` (全部4个子字段) — 反应条件
- `main_activity.mechanism` — 催化机制
- `applications.target_analyte` — 检测目标
- `applications.method` — 检测方法
- `applications.sample_type` — 样品类型

**影响**：LLM 不可用时，约 40% 的字段为空，记录质量从 "complete" 降级为 "partial"。

---

## 二、规则提取准确率评估

### 2.1 动力学参数 (Km/Vmax/kcat)

| 维度 | 评估 | 说明 |
|------|------|------|
| 正则覆盖度 | ★★★★☆ | 19个Vmax模式+13个kcat模式+14个kcat/Km模式，覆盖主流写法 |
| OCR兼容性 | ★★★☆☆ | Unicode上标⁻⁸→-8已修复，但⁺³等正上标仍有遗漏风险 |
| 多底物场景 | ★★☆☆☆ | 同一材料多底物Km只保留最后一个，无多底物支持 |
| 表格提取 | ★★★☆☆ | 扁平表/内联表可处理，但跨行合并单元格无法处理 |
| 单位提取 | ★★★★☆ | _RATE_UNITS已统一为共享常量，覆盖nM/s级别 |

**已知缺陷**：
- `_extract_vmax_fallback` 中 `plain_m` 正则只匹配特定Unicode单位格式，ASCII变体如 `mM/s` 可能漏匹配
- `_KCAT_PATTERNS` 中 `(?!\s*/\s*Km)` 负向断言在某些 LLM 输出格式下可能误过滤

### 2.2 晶体结构

| 维度 | 评估 | 说明 |
|------|------|------|
| 结构类型识别 | ★★★★☆ | 19个模式覆盖spinel/perovskite/FCC/BCC等+6个新增结构名 |
| 晶面指数 | ★★★★☆ | 已修复：格式化为(111)而非纯数字 |
| d-spacing | ★★★☆☆ | 可提取但存入important_values而非crystal_structure，信息分散 |

### 2.3 材料选择

| 维度 | 评估 | 说明 |
|------|------|------|
| 候选召回 | ★★★★☆ | CandidateRecaller + 5种别名发现策略 |
| 评分排序 | ★★★☆☆ | 基于提及频率+上下文信号，但无语义理解 |
| SAzyme/单原子 | ★★★☆☆ | 有SAzyme别名发现，但Fe-N-C等配位结构识别弱 |

### 2.4 应用提取

| 维度 | 评估 | 说明 |
|------|------|------|
| LOD/线性范围 | ★★★★☆ | 专用正则+表格兜底 |
| 应用类型分类 | ★★☆☆☆ | 仅关键词匹配，无语义分类 |
| 多应用场景 | ★★★☆☆ | 可提取多个，但去重逻辑简单 |

---

## 三、大模型提取质量评估

### 3.1 Prompt 设计

| 维度 | 评分 | 说明 |
|------|------|------|
| 防幻觉指令 | ★★★★☆ | "Only extract explicitly stated data" + "Never guess" |
| 输出格式约束 | ★★★★☆ | 强制JSON、禁止markdown、null处理缺失值 |
| 枚举值约束 | ★★★☆☆ | enzyme_like_type/application_type有枚举要求，但未在prompt中列出完整枚举 |
| 材料归属约束 | ★★★★☆ | "Extract ONLY ONE main nanozyme" + "Do NOT extract from comparison tables" |
| 底物/分析物区分 | ★★★★☆ | 明确区分substrate(消耗)和analyte(检测) |

### 3.2 幻觉防护体系

| 层级 | 机制 | 评分 | 说明 |
|------|------|------|------|
| L1 | Prompt硬约束 | ★★★★☆ | 4条HARD RULES，但LLM不一定遵守 |
| L2 | JSONFixer+robust_parse | ★★★★★ | 5层回退策略，极强容错 |
| L3 | ConsistencyGuard归属守卫 | ★★★★☆ | 5种别名发现+句子归属判断+VLM归属过滤 |
| L4 | AgenticGuard冲突检测 | ★★★★☆ | rule/LLM检查点+LLM仲裁解决 |
| L5 | CrossValidationAgent | ★★★★☆ | 三源交叉验证+截断检测+量级范围 |
| L6 | NumericValidator | ★★★★☆ | 单位/量级/归属验证+降级机制 |
| L7 | DiagnosticsBuilder | ★★★☆☆ | 49种警告，但置信度判定较粗糙 |

### 3.3 LLM 产出约束问题

| 问题 | 严重程度 | 说明 |
|------|---------|------|
| 枚举值不完整 | 中 | prompt要求enzyme_like_type使用枚举但未列出完整枚举表 |
| 多底物Km覆盖 | 高 | LLM可能输出多个Km，但schema只支持单个 |
| 应用合并/缩减 | 中 | prompt要求"Extract ALL applications"但LLM可能合并 |
| 数值精度丢失 | 低 | LLM可能将3.4521截断为3.45 |
| 材料名简化 | 中 | prompt要求"Keep the material name as given"但LLM可能简化 |

---

## 四、VLM 图文一致性评估

| 维度 | 评分 | 说明 |
|------|------|------|
| 图注-图像匹配评估 | ★★★★☆ | FigureHandler.assess_caption_match，3类匹配+阈值0.4 |
| 图注显式值提取 | ★★★★☆ | 从图注正则提取Km/Vmax作为独立验证源 |
| VLM归属过滤 | ★★★★☆ | ConsistencyGuard.check_vlm_result_attribution |
| VLM任务预过滤 | ★★★☆☆ | 基于图注关键词过滤，可能遗漏无图注的高价值图 |
| 图文数值交叉验证 | ★★☆☆☆ | VLM值默认进important_values而非直接覆盖kinetics |
| 多图一致性 | ★☆☆☆☆ | 无多图间一致性检查机制 |

**关键缺陷**：
1. VLM提取的动力学值**默认不进入kinetics字段**，只进important_values(needs_review=True)
2. 缺少多图间一致性检查：同一材料在Figure 3和Figure 5的Km值可能不同，无检测机制
3. VLM prompt中`linked_activity_type`判断依赖正文上下文（最多400字符），上下文不足时可能误判

---

## 五、数据一致性评估

### 5.1 跨字段一致性

| 检查项 | 实现状态 | 说明 |
|--------|---------|------|
| Km单位必须是浓度 | ✅ | NumericValidator |
| Vmax单位必须是速率 | ✅ | NumericValidator |
| kcat/Km合理性 | ✅ | 1e-3~1e12范围 |
| 酶类型-pH一致性 | ✅ | catalase-like不低pH, peroxidase-like不高pH |
| 合成方法-温度一致性 | ✅ | 水热>100°C, 煅烧>300°C |
| 粒径合理性 | ✅ | >500nm警告 |
| 材料名-动力学归属 | ✅ | NumericValidator检查material与selected_nanozyme匹配 |

### 5.2 缺失的一致性检查

| 检查项 | 状态 | 影响 |
|--------|------|------|
| Km-Vmax底物一致性 | ❌ | Km和Vmax可能来自不同底物但被存入同一kinetics对象 |
| 应用-酶类型一致性 | ❌ | peroxidase-like材料不应有glucose直接检测应用 |
| 合成方法-材料类型一致性 | ❌ | MOF材料应有calcination/carbonization步骤 |
| 表征手段-材料一致性 | ❌ | 磁性材料应有VSM，但无检查 |
| 多来源数值一致性 | ⚠️ | 有CrossValidation但仅限Km/Vmax/kcat |

---

## 六、科研数据集跑图差距评估

### 6.1 当前可支持的科研产出

| 产出类型 | 可行性 | 说明 |
|---------|--------|------|
| Km/Vmax分布统计图 | ★★★★☆ | 数据可提取，但多底物场景需后处理 |
| 酶类型分布饼图 | ★★★★☆ | enzyme_like_type可提取且已归一化 |
| 材料类型分布图 | ★★★☆☆ | composition依赖LLM，纯规则模式为空 |
| pH/温度最优值散点图 | ★★★★☆ | optimal_pH/optimal_temperature可提取 |
| LOD分布图 | ★★★★☆ | detection_limit可提取 |
| 合成方法统计图 | ★★★☆☆ | synthesis_method可提取但分类不细 |
| 应用领域分布图 | ★★☆☆☆ | application_type分类粗糙，无标准分类体系 |

### 6.2 跑数据集的关键差距

| 差距 | 优先级 | 说明 |
|------|--------|------|
| **批量评估框架** | P0 | 无自动化评估脚本，无法计算Precision/Recall/F1 |
| **Gold Standard数据集** | P0 | 无人工标注的基准数据集，无法量化准确率 |
| **多底物Km/Vmax支持** | P1 | Schema只支持单kinetics对象，多底物论文数据丢失 |
| **应用类型标准分类** | P1 | 无标准分类体系（如sensing/therapeutic/environmental） |
| **材料组成结构化** | P1 | composition是自由文本，无法做元素级统计 |
| **提取结果对比工具** | P2 | 无自动对比提取结果与人工标注的工具 |
| **批量提取统计报告** | P2 | 无批量提取后的统计汇总和可视化脚本 |
| **跨论文关联分析** | P3 | 无材料-性能跨论文关联能力 |

### 6.3 科研绘图就绪度

| 图表类型 | 数据就绪 | 格式就绪 | 需要后处理 |
|---------|---------|---------|-----------|
| Km分布直方图 | ✅ | ❌ | 需单位统一化脚本 |
| Vmax分布直方图 | ✅ | ❌ | 需单位统一化+科学计数法处理 |
| 酶类型饼图 | ✅ | ✅ | 直接可用 |
| pH-活性曲线汇总 | ✅ | ❌ | 需数值归一化 |
| LOD分布箱线图 | ✅ | ❌ | 需单位统一化 |
| 材料元素热力图 | ❌ | ❌ | composition未结构化 |

---

## 七、系统成熟度总评

| 维度 | 成熟度 | 评分 |
|------|--------|------|
| Schema设计 | 成熟 | ★★★★☆ |
| 规则提取 | 较成熟 | ★★★★☆ |
| LLM提取+防幻觉 | 较成熟 | ★★★★☆ |
| VLM提取 | 基础可用 | ★★★☆☆ |
| 交叉验证 | 较成熟 | ★★★★☆ |
| 一致性守卫 | 较成熟 | ★★★★☆ |
| 批量处理 | 基础可用 | ★★★☆☆ |
| 评估框架 | 未建设 | ★☆☆☆☆ |
| 科研可视化 | 未建设 | ★☆☆☆☆ |
| **综合** | **原型-产品过渡期** | **★★★☆☆** |
