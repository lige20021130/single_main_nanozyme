# LLM提取能力全面增强设计

## 更新时间
2026-05-12

## 方案选择
方案A：渐进式增强（4个方向逐步增强，风险低，收益最大）

## 目标
在现有 `LLMStructuredExtractor` 架构上，通过4个方向的增强，将关键字段提取率从当前50-70%提升到75-90%。

---

## 1. Prompt工程优化

### 1.1 当前问题
- 动力学few-shot仅4例，缺少kcat提取、optimal_pH/temperature、科学计数法变体
- 形态仅1例，缺少合成条件深度提取、表征技术列表
- 无合成条件专用prompt（当前混在morphology prompt中）
- 无pH/温度专用prompt

### 1.2 改动内容

#### 扩展few-shot examples

| 子任务 | 当前 | 目标 | 新增内容 |
|-------|------|------|---------|
| 动力学 | 4例 | 10例 | +kcat/kcat_Km提取、+科学计数法变体(×10⁻⁵/e-5/上标)、+optimal_pH/temp、+多底物完整示例、+表格数据提取 |
| 形态 | 1例 | 5例 | +单原子催化剂(Mo-SAN)、+MOF框架(ZIF-8/UiO-66)、+核壳结构(Fe3O4@C)、+水热合成条件 |
| 应用 | 5例 | 8例 | +环境检测(重金属离子)、+抗氧化治疗、+多应用场景(检测+治疗) |
| 合成条件 | 0 | 新增3例 | 新建SYNTHESIS_EXTRACTION_PROMPT |
| pH/温度 | 0 | 新增3例 | 新建PH_TEMP_EXTRACTION_PROMPT |

#### 新增2个专用prompt

**SYNTHESIS_EXTRACTION_PROMPT**：
- 专注提取：synthesis_method, temperature, time, precursors, solvent, pH, atmosphere
- 输出格式：`{"synthesis_method": "...", "synthesis_conditions": {...}, "characterization": [...]}`
- 3个few-shot examples：水热法、共沉淀法、溶剂热法

**PH_TEMP_EXTRACTION_PROMPT**：
- 专注提取：optimal_pH, pH_range, optimal_temperature, temperature_range
- 输出格式：`{"pH_profile": {"optimal_pH": ..., "pH_range": "..."}, "temperature_profile": {"optimal_temperature": ..., "temperature_range": "..."}}`
- 3个few-shot examples：直接陈述、图表描述、比较语句

#### 优化SYSTEM_PROMPT
- 增加"表格数据解读"领域知识（如何从表格中识别目标材料行）
- 增加"科学计数法处理"规则（×10⁻⁵ → 1e-5转换）
- 增加"单位体系"知识（常见单位换算关系表）

### 1.3 修改文件
- `extraction_prompts.py`：扩展few-shot examples、新增2个prompt模板、优化SYSTEM_PROMPT
- `llm_structured_extractor.py`：新增 `extract_synthesis()` 和 `extract_ph_temp()` 方法

---

## 2. Constrained Decoding

### 2.1 当前问题
- 仅使用 `response_format: {"type": "json_object"}`，只保证输出是合法JSON，不保证schema合规
- JSON解析失败率约30%（LLM返回Markdown包裹、多余文本、字段名错误等）
- `auto_fix_schema_errors` 只能修复少数已知错误模式

### 2.2 改动内容

#### 集成instructor库

```
当前: client.chat_completion_text(messages) → 手动JSON解析 → validate_against_schema → auto_fix
改后: instructor.from_openai(client) → Pydantic模型约束 → 自动解析+验证 → 零手动解析
```

#### 定义Pydantic模型（在schema_constraints.py中新增）

- `KineticsEntry`：Km/Vmax/kcat等字段 + 类型约束 + validator
  - validator: Km > 1.0 M → None, Vmax < 1.0 M/s → 自动转μM/s
- `SynthesisConditions`：temperature/time/precursors/solvent
- `ApplicationEntry`：application_type/analyte/LOD等 + validator
  - validator: application_type必须在枚举内
- `NanozymeExtraction`：顶层模型，组合所有子模型

#### 修改LLMStructuredExtractor._call_llm_structured
- 优先使用instructor模式（当instructor可用时）
- 降级策略：instructor不可用时回退到当前JSON解析模式
- 通过 `dependencies.py` 管理instructor依赖

### 2.3 依赖管理
- `instructor` 是可选依赖，通过 `dependencies.py` 的 `is_available()` 检测
- 不可用时自动降级到现有JSON模式，零影响
- `pip install instructor` 即可启用

### 2.4 修改文件
- `schema_constraints.py`：新增Pydantic模型定义
- `llm_structured_extractor.py`：修改 `_call_llm_structured` 支持instructor模式
- `dependencies.py`：注册instructor依赖

---

## 3. 表格提取增强

### 3.1 当前问题
- 表格文本仅截取前3000字符传入LLM，大量表格数据被截断
- 无专用表格提取prompt，表格数据混在动力学prompt中
- 表格中的结构化信息（列名、行归属）丢失

### 3.2 改动内容

#### 新增extract_from_table()方法

1. **表格预处理**：
   - 从预处理器获取结构化表格数据
   - 将表格转为"Markdown表格 + 列说明"格式，保留结构信息
   - 表格文本配额从3000→8000字符

2. **专用表格提取prompt**（TABLE_KINETICS_EXTRACTION_PROMPT）：
   - 明确指示LLM从表格中读取Km/Vmax/kcat
   - 指示区分"this work"行 vs 对照行
   - 指示处理科学计数法（表格中常见 ×10⁻⁵ 格式）
   - 指示识别多行数据归属（哪行属于目标材料）
   - 3个表格专用few-shot examples

3. **表格提取流程**：
   ```
   extract_kinetics() → 先从文本提取
                    → 再从表格提取（新增）
                    → 合并结果（表格值补充文本缺失字段）
   ```

4. **表格数据智能截取**：
   - 优先保留包含目标材料名的行
   - 优先保留包含Km/Vmax/kcat关键词的行
   - 保留表头行
   - 截取时保留完整行，不切断

### 3.3 修改文件
- `extraction_prompts.py`：新增TABLE_KINETICS_EXTRACTION_PROMPT + 3个few-shot examples
- `llm_structured_extractor.py`：新增 `extract_from_table()` 方法，修改 `extract_kinetics()` 调用流程

---

## 4. 自我验证循环

### 4.1 当前问题
- self-augmentation仅1轮，且只是"再提取一次"
- 没有验证步骤——不知道提取结果是否正确
- 没有修正步骤——无法针对性修复错误

### 4.2 改动内容

#### Extract → Verify → Correct 三步循环

```
Step 1: EXTRACT — LLM提取（现有逻辑）
         ↓
Step 2: VERIFY — LLM验证提取结果
         ├─ 检查字段完整性（关键字段是否缺失）
         ├─ 检查数值合理性（Km/Vmax量级、单位）
         ├─ 检查语义一致性（酶类型-底物-应用是否匹配）
         ├─ 检查原文覆盖（是否有原文明确提到的值被遗漏）
         └─ 输出：验证报告（issues列表 + 修正建议）
         ↓
Step 3: CORRECT — LLM根据验证报告修正
         ├─ 只修正验证报告中的问题
         ├─ 不改动已验证正确的字段
         └─ 输出：修正后的结果
         ↓
    如果仍有问题且未达最大轮数(2轮) → 回到Step 2
    否则 → 输出最终结果
```

#### 新增验证prompt（VERIFICATION_PROMPT）
- 输入：提取结果 + 原文
- 输出：`{"issues": [{"field": "...", "problem": "...", "suggestion": "..."}], "confidence": 0.0-1.0}`
- 验证维度：完整性、数值合理性、语义一致性、原文覆盖

#### 新增修正prompt（CORRECTION_PROMPT）
- 输入：提取结果 + 验证报告 + 原文
- 输出：修正后的完整JSON
- 约束：只修正报告中指出的问题

#### 循环控制
- 最大2轮验证-修正
- confidence ≥ 0.85 时提前退出
- 每轮验证后如果无新issue则退出

### 4.3 修改文件
- `extraction_prompts.py`：新增VERIFICATION_PROMPT和CORRECTION_PROMPT
- `llm_structured_extractor.py`：新增 `_verify_extraction()` 和 `_correct_extraction()` 方法，修改 `extract_all()` 流程

---

## 文件改动总览

| 文件 | 改动类型 | 改动内容 |
|------|---------|---------|
| `extraction_prompts.py` | 修改 | 扩展few-shot examples、新增4个prompt模板、优化SYSTEM_PROMPT |
| `schema_constraints.py` | 修改 | 新增Pydantic模型定义 |
| `llm_structured_extractor.py` | 修改 | 新增3个提取方法、修改_call_llm_structured支持instructor、新增验证-修正循环 |
| `dependencies.py` | 修改 | 注册instructor依赖 |

## 不改动的文件
- `single_main_nanozyme_extractor.py`：管道集成层不变
- `extraction_agents.py`：规则提取Agent不变
- `cross_validation_agent.py`：交叉验证逻辑不变
- `consistency_agent.py`：一致性修正不变
- `numeric_validator.py`：数值校验不变
- `vlm_extractor.py`：VLM提取不变
- `nanozyme_models.py`：枚举映射不变

## 预期收益

| 字段 | 当前提取率 | 预期提取率 | 提升 |
|------|-----------|-----------|------|
| Km | 50-60% | 75-85% | +25% |
| Vmax | 40-50% | 70-80% | +30% |
| kcat | 10% | 45-55% | +40% |
| optimal_pH | 60% | 80-85% | +20% |
| optimal_temp | 20% | 60-70% | +45% |
| LOD | 40-50% | 70-80% | +30% |
| synthesis_method | 30% | 65-75% | +40% |
| characterization | 低 | 60-70% | +50% |

## 风险与后续
- instructor库是可选依赖，降级策略确保无影响
- 验证-修正循环增加2-4次API调用，可通过config关闭
- 新增few-shot examples增加prompt token消耗，但提升提取质量
- 后续可考虑：用纳米酶领域数据fine-tune模型、增加更多few-shot examples
