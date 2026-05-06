# 规则提取能力上限优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 大幅提升规则提取的覆盖率，缩小规则提取与LLM提取之间的差距，使规则提取在无LLM场景下也能达到可用水平

**Architecture:** 针对当前规则提取5大瓶颈（证据桶召回不足、动力学正则覆盖窄、应用提取漏检、形态/合成信息丢失、表格数据浪费），逐项增强规则引擎，不改动LLM/VLM管道

**Tech Stack:** Python 3.10+, re, 已有正则模式库, extraction_agents.py, single_main_nanozyme_extractor.py

---

## 当前瓶颈诊断

基于代码审查和历史评估数据（2026-04-28迭代记录）：

| 字段 | 规则提取率 | LLM提取率 | 差距 | 根因 |
|------|-----------|----------|------|------|
| Km | 50-60% | ~80% | 20-30% | 正则模式不够灵活，OCR变体未覆盖 |
| Vmax | 40-50% | ~75% | 25-35% | 科学计数法处理差，单位匹配过严 |
| kcat | 10% | ~50% | 40% | 模式太少，turnover number等别名未覆盖 |
| optimal_pH | 60% | ~85% | 25% | 只搜桶内文本，全文fallback太晚 |
| optimal_temp | 20% | ~70% | 50% | 模式过少，°C符号变体覆盖不足 |
| size | 50-60% | ~80% | 20% | DLS/hydrodynamic等修饰词未区分 |
| synthesis_method | 50-70% | ~85% | 15-35% | 频率投票有效但搜索范围窄 |
| LOD | 40-50% | ~80% | 30-40% | 只搜application桶，kinetics桶中的LOD被忽略 |
| morphology | 80% | ~90% | 10% | 已较好 |
| enzyme_type | 100% | 100% | 0% | 已完美 |

### 5大核心瓶颈

1. **证据桶召回不足**：`EvidenceBucketBuilder`要求句子同时匹配关键词+材料名，导致大量相关句子被丢弃
2. **动力学正则覆盖窄**：Km/Vmax/kcat模式虽多(26+22+14个)，但都是精确匹配格式，对自由文本表述覆盖差
3. **应用提取漏检严重**：`_extract_applications_from_text`只在application桶搜索，且LOD/linear_range模式太少
4. **pH/温度提取极弱**：optimal_temperature仅20%提取率，模式过少
5. **表格数据浪费**：`TableProcessor`分类了kinetics/sensing表但提取逻辑薄弱

---

## Task 1: 增强证据桶召回 - 放宽材料名匹配约束

**Files:**
- Modify: `single_main_nanozyme_extractor.py:2268-2384` (EvidenceBucketBuilder.build)

**问题**: 当前逻辑要求句子同时匹配桶关键词 AND 材料名，导致大量相关句子被丢弃。对于kinetics/application桶，即使不提及材料名，只要上下文属于同一节也应纳入。

- [ ] **Step 1: 修改EvidenceBucketBuilder.build的桶填充逻辑**

当前代码(L2317-2337):
```python
for text, section in all_sentences:
    text_lower = text.lower()
    name_matched = any(v in text_lower for v in variants)
    for bucket_name, pattern in _BUCKET_KEYWORDS.items():
        if not pattern.search(text):
            continue
        if name_matched:
            buckets[bucket_name].append(text)
        elif bucket_name in ("kinetics", "application", "mechanism"):
            attr = self.consistency_guard.check_sentence_attribution(text)
            if attr["belongs_to_selected"]:
                buckets[bucket_name].append(text)
        elif bucket_name in ("activity", "synthesis", "characterization"):
            ...
```

修改为：
```python
for text, section in all_sentences:
    text_lower = text.lower()
    name_matched = any(v in text_lower for v in variants)
    for bucket_name, pattern in _BUCKET_KEYWORDS.items():
        if not pattern.search(text):
            continue
        if name_matched:
            buckets[bucket_name].append(text)
        elif bucket_name in ("kinetics", "application", "mechanism"):
            attr = self.consistency_guard.check_sentence_attribution(text)
            if attr["belongs_to_selected"]:
                buckets[bucket_name].append(text)
            elif section in ("results", "discussion") and attr["confidence"] != "high":
                buckets[bucket_name].append(text)
        elif bucket_name in ("activity", "synthesis", "characterization"):
            attr = self.consistency_guard.check_sentence_attribution(text)
            if attr["belongs_to_selected"]:
                buckets[bucket_name].append(text)
            elif any(kw in text_lower for kw in ("nanozyme", "enzyme-like", "catalytic",
                                                  "peroxidase", "oxidase", "catalase",
                                                  "synthesized", "prepared", "hydrothermal",
                                                  "solvothermal", "calcination")):
                if attr["confidence"] != "high" or attr["reason"] not in (
                    "previous_work_reference", "mentions_other_only"
                ):
                    buckets[bucket_name].append(text)
            elif bucket_name == "synthesis" and attr["confidence"] == "low":
                buckets[bucket_name].append(text)
```

关键变化：kinetics/application/mechanism桶在results/discussion节中，只要不是高置信度排除就纳入。

- [ ] **Step 2: 增加桶容量上限**

当前`max_sentences=20`太小，改为30：
```python
class EvidenceBucketBuilder:
    def __init__(self, max_sentences: int = 30, consistency_guard=None):
```

- [ ] **Step 3: 语法检查**

Run: `python -m py_compile single_main_nanozyme_extractor.py`

---

## Task 2: 增强Km/Vmax正则 - 增加宽松匹配模式

**Files:**
- Modify: `single_main_nanozyme_extractor.py:299-494` (_KM_PATTERNS, _VMAX_PATTERNS)
- Modify: `extraction_agents.py` (KineticsAgent._extract_kinetics_from_text)

**问题**: 当前Km有26个模式、Vmax有22个模式，但都是精确格式匹配。真实文献中有大量"Km = 0.35"（无单位紧跟）、"the Km value was determined as 0.35 mM"等变体未被覆盖。

- [ ] **Step 1: 在_KM_PATTERNS末尾增加5个宽松模式**

在`_KM_PATTERNS`列表末尾追加：
```python
    re.compile(r'\bKm\b[^.]{0,50}?([\d.]+)\s*(mM|μM|uM|M|mmol/L|umol/L)', re.I),
    re.compile(r'\bKm\b\s*[^.\d]{0,20}?([\d.]+)\s*[×x]\s*10[⁻\-–\u2212\u2013](\d+)\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bMichaelis[^.]{0,30}?constant\b[^.]{0,50}?([\d.]+)\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\b[^.]{0,15}?determined\b[^.]{0,30}?([\d.]+)\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\b[^.]{0,40}?([\d.]+)\s*[eE][\-−]?\d+\s*(mM|μM|uM|M)', re.I),
```

- [ ] **Step 2: 在_VMAX_PATTERNS末尾增加5个宽松模式**

在`_VMAX_PATTERNS`列表末尾追加：
```python
    re.compile(r'\bV\s*max\b[^.]{0,50}?([\d.]+)\s*(M\s*[sS][⁻\-–]?1|M/?s|mM/?s|μM/?s)', re.I),
    re.compile(r'\bV\s*max\b\s*[^.\d]{0,20}?([\d.]+)\s*[×x]\s*10[⁻\-–\u2212\u2013](\d+)\s*(M\s*[sS]|mM\s*[sS])', re.I),
    re.compile(r'\bmaximum\s+velocity\b[^.]{0,50}?([\d.]+)\s*(M\s*[sS][⁻\-–]?1|M/?s|mM/?s)', re.I),
    re.compile(r'\bV\s*max\b[^.]{0,15}?determined\b[^.]{0,30}?([\d.]+)\s*(M\s*[sS][⁻\-–]?1|M/?s|mM/?s)', re.I),
    re.compile(r'\bV\s*max\b[^.]{0,40}?([\d.]+)\s*[eE][\-−]?\d+\s*(M\s*[sS][⁻\-–]?1|M/?s|mM/?s)', re.I),
```

- [ ] **Step 3: 增加Km无单位回退提取**

在`KineticsAgent._extract_kinetics_from_text`中，当所有_KM_PATTERNS都未匹配时，尝试宽松无单位提取：
```python
if not km_candidates:
    _KM_NO_UNIT = re.compile(r'\bKm\b[^.\d]{0,30}?([\d.]+)(?!\s*(?:mM|μM|uM|M|mmol|umol|nmol))', re.I)
    for text in kinetics_texts:
        m = _KM_NO_UNIT.search(text)
        if m:
            try:
                val = float(m.group(1))
                if 1e-6 <= val <= 1e3:
                    km_candidates.append((5, val, None, "text_no_unit", text[:300]))
            except ValueError:
                pass
```

- [ ] **Step 4: 语法检查**

Run: `python -m py_compile single_main_nanozyme_extractor.py && python -m py_compile extraction_agents.py`

---

## Task 3: 增强kcat提取 - 覆盖更多别名和格式

**Files:**
- Modify: `single_main_nanozyme_extractor.py:342-494` (_KCAT_PATTERNS, _KCAT_KM_PATTERNS)

**问题**: kcat提取率仅10%，模式14个但缺少关键别名如"turnover frequency"、"catalytic constant"、以及"×10^n s^-1"等常见格式。

- [ ] **Step 1: 在_KCAT_PATTERNS末尾增加6个模式**

```python
    re.compile(r'\bkcat\b[^.=]{0,40}?([\d.]+)\s*[×x\u00d7]\s*10[⁻\-\u207b]?\s*(\d+)\s*(s[⁻\-–\u207b]?1|s-1|min[⁻\-–\u207b]?1)', re.I),
    re.compile(r'\bturnover\s+frequency\b[^.=]{0,30}?(?:was|=|:|≈|~)\s*([\d.]+)\s*[×x\u00d7]?\s*10[⁻\-\u207b]?\s*(\d+)?\s*(s[⁻\-–\u207b]?1|s-1)', re.I),
    re.compile(r'\bcatalytic\s+rate\b[^.=]{0,30}?(?:was|=|:|≈|~)\s*([\d.]+)\s*[×x\u00d7]?\s*10[⁻\-\u207b]?\s*(\d+)?\s*(s[⁻\-–\u207b]?1|s-1)', re.I),
    re.compile(r'\bkcat\b[^.=]{0,20}?([\d.]+)\s*s\u207b\u00b9', re.I),
    re.compile(r'\bKcat\b[^.]{0,50}?([\d.]+)\s*(s[⁻\-–\u207b]?1|s-1)', re.I),
    re.compile(r'\bturnover\s+(?:number|frequency)\b[^.]{0,50}?([\d.]+)\s*(s[⁻\-–\u207b]?1|s-1|min[⁻\-–\u207b]?1)', re.I),
```

- [ ] **Step 2: 在_KCAT_KM_PATTERNS末尾增加3个模式**

```python
    re.compile(r'\bcatalytic\s+efficiency\b[^.=]{0,40}?([\d.]+)\s*[×x\u00d7]\s*10[⁻\-\u207b]?\s*(\d+)\s*(M[⁻\-–\u207b]?1\s*s[⁻\-–\u207b]?1|M/?s)', re.I),
    re.compile(r'\bspecificity\s+constant\b[^.=]{0,40}?([\d.]+)\s*[×x\u00d7]\s*10[⁻\-\u207b]?\s*(\d+)\s*(M[⁻\-–\u207b]?1\s*s[⁻\-–\u207b]?1)', re.I),
    re.compile(r'\bkcat/Km\b[^.=]{0,30}?([\d.]+)\s*[eE][\-−]?\d+\s*(M[⁻\-–\u207b]?1\s*s[⁻\-–\u207b]?1)', re.I),
```

- [ ] **Step 3: 语法检查**

Run: `python -m py_compile single_main_nanozyme_extractor.py`

---

## Task 4: 增强pH/温度提取 - 扩展模式和搜索范围

**Files:**
- Modify: `single_main_nanozyme_extractor.py:798-870` (_PH_PATTERNS, _TEMPERATURE_PATTERNS)
- Modify: `extraction_agents.py` (RuleExtractorAdapter._extract_pH_profile, _extract_temperature_profile)

**问题**: optimal_temperature仅20%提取率。模式过少，且只搜索桶内文本。

- [ ] **Step 1: 在_TEMPERATURE_PATTERNS["optimal_temperature"]增加5个模式**

```python
    re.compile(r'\boptimal\s+temperature\s*(?:of|was|=|:|≈|~|at)\s*([\d.]+)\s*[\u02da\u00b0\u00ba\u25e6]\s*C', re.I),
    re.compile(r'\boptimum\s+temperature\s*(?:of|was|=|:|≈|~|at)\s*([\d.]+)\s*[\u02da\u00b0\u00ba\u25e6]\s*C', re.I),
    re.compile(r'\btemperature\s+optimum\b[^.]{0,20}?([\d.]+)\s*[\u02da\u00b0\u00ba\u25e6]\s*C', re.I),
    re.compile(r'\bmaximum\s+activity\s*(?:at|was\s+observed\s+at)\s*([\d.]+)\s*[\u02da\u00b0\u00ba\u25e6]\s*C', re.I),
    re.compile(r'\b(?:best|highest)\s+(?:catalytic\s+)?activity\s*(?:at|was)\s*([\d.]+)\s*[\u02da\u00b0\u00ba\u25e6]\s*C', re.I),
```

- [ ] **Step 2: 在_PH_PATTERNS["optimal_pH"]增加3个模式**

```python
    re.compile(r'\bpH\s+optimum\s*(?:was|=|:|≈|~)\s*([\d.]+)', re.I),
    re.compile(r'\bmaximum\s+activity\s*(?:at|was\s+observed\s+at)\s*pH\s*([\d.]+)', re.I),
    re.compile(r'\b(?:best|highest)\s+(?:catalytic\s+)?activity\s*(?:at|was)\s*pH\s*([\d.]+)', re.I),
```

- [ ] **Step 3: 扩展pH/温度搜索范围**

在`RuleExtractorAdapter._extract_pH_profile`中，当前只搜索`buckets.get("activity", [])`，增加搜索范围：
```python
def _extract_pH_profile(self, record, buckets):
    ph_prof = record["main_activity"].setdefault("pH_profile", {})
    search_texts = (buckets.get("activity", []) + buckets.get("kinetics", [])[:5]
                    + buckets.get("mechanism", [])[:3])
```

同样修改`_extract_temperature_profile`：
```python
def _extract_temperature_profile(self, record, buckets):
    temp_prof = record["main_activity"].setdefault("temperature_profile", {})
    search_texts = (buckets.get("activity", []) + buckets.get("kinetics", [])[:5]
                    + buckets.get("synthesis", [])[:3])
```

- [ ] **Step 4: 语法检查**

Run: `python -m py_compile single_main_nanozyme_extractor.py && python -m py_compile extraction_agents.py`

---

## Task 5: 增强应用提取 - 扩展LOD/analyte模式和搜索范围

**Files:**
- Modify: `single_main_nanozyme_extractor.py:659-740` (_LOD_PATTERNS, _LINEAR_RANGE_PATTERNS)
- Modify: `extraction_agents.py` (ApplicationAgent._extract_applications_from_text)

**问题**: LOD提取率40-50%。只在application桶搜索，LOD模式太少(4个)，analyte模式覆盖不足。

- [ ] **Step 1: 在_LOD_PATTERNS增加4个模式**

```python
    re.compile(r'(?:LOD|detection\s+limit)\s*(?:for|of)\s+\S+\s*(?:was|is|=|:|≈|~)\s*([\d.]+)\s*[×x\u00d7]\s*10[⁻\-\u207b]?\s*(\d+)?\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm)', re.I),
    re.compile(r'(?:as\s+low\s+as)\s*([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm)', re.I),
    re.compile(r'(?:detect(?:ed|ion|ing))\s+(?:down\s+to|at)\s*([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm)', re.I),
    re.compile(r'(?:LOD|detection\s+limit)\s*[\(（\[]\s*([\d.]+)\s*[×x\u00d7]?\s*10[⁻\-\u207b]?\s*(\d+)?\s*(nM|μM|uM|mM|M|pg/mL|ng/mL)\s*[\)）\]]', re.I),
```

- [ ] **Step 2: 在_LINEAR_RANGE_PATTERNS增加2个模式**

```python
    re.compile(r'(?:range|concentration\s+range)\s*(?:of|=|:)\s*([\d.]+\s*[-–—~to]+\s*[\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L)', re.I),
    re.compile(r'([\d.]+)\s*[-–—~]\s*([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L)\s+(?:linear|calibration)', re.I),
```

- [ ] **Step 3: 扩展ApplicationAgent搜索范围**

在`ApplicationAgent.extract`中，增加搜索桶：
```python
def extract(self, record, buckets, table_values, selected_name, doc=None):
    app_texts = (buckets.get("application", [])
                 + buckets.get("kinetics", [])[:5]
                 + buckets.get("activity", [])[:3])
    self._extract_applications_from_text(record, app_texts)
    return record
```

- [ ] **Step 4: 增加更多analyte模式**

在`ApplicationAgent._ANALYTE_PATTERNS`增加：
```python
    re.compile(r'\b(?:sensing|detecting|monitoring)\s+(?:of\s+)?([\w\-]+(?:\s[\w\-]+){0,2})', re.I),
    re.compile(r'\b(?:thrombin|lysozyme|trypsin|urease|horseradish|HRP|BSA|albumin)\b', re.I),
    re.compile(r'\b(?:nitrofurantoin|chloramphenicol|tetracycline|kanamycin|gentamicin|ampicillin)\b', re.I),
    re.compile(r'\b(?:malathion|paraoxon|chlorpyrifos|diazinon|atrazine|simazine)\b', re.I),
```

- [ ] **Step 5: 语法检查**

Run: `python -m py_compile single_main_nanozyme_extractor.py && python -m py_compile extraction_agents.py`

---

## Task 6: 增强表格数据提取 - 利用已分类表格

**Files:**
- Modify: `extraction_agents.py` (KineticsAgent._extract_kinetics_from_table)

**问题**: `TableProcessor`已分类kinetics/sensing表，但`_extract_kinetics_from_table`只处理简单的parameter/value结构，对真实表格行数据提取能力弱。

- [ ] **Step 1: 增加表格行级Km/Vmax提取**

在`KineticsAgent._extract_kinetics_from_table`中，增加对表格行数据的扫描：
```python
def _extract_kinetics_from_table(self, record, table_values):
    for val in table_values:
        param = val.get("parameter", "")
        if param == "Km" and record["main_activity"]["kinetics"]["Km"] is None:
            try:
                record["main_activity"]["kinetics"]["Km"] = float(val["value"])
                nu = _norm_unit(val.get("unit"))
                record["main_activity"]["kinetics"]["Km_unit"] = nu if nu else val.get("unit")
                record["main_activity"]["kinetics"]["substrate"] = val.get("substrate")
                record["main_activity"]["kinetics"]["source"] = "table"
            except (ValueError, TypeError):
                pass
        elif param == "Vmax" and record["main_activity"]["kinetics"]["Vmax"] is None:
            try:
                record["main_activity"]["kinetics"]["Vmax"] = float(val["value"])
            except (ValueError, TypeError):
                record["main_activity"]["kinetics"]["Vmax"] = val["value"]
            nu = _norm_unit(val.get("unit"))
            record["main_activity"]["kinetics"]["Vmax_unit"] = nu if nu else val.get("unit")
            record["main_activity"]["kinetics"]["source"] = "table"
        elif param in ("kcat", "Kcat", "k_cat") and record["main_activity"]["kinetics"]["kcat"] is None:
            try:
                parsed = _parse_scientific_notation(str(val["value"]))
                if isinstance(parsed, (int, float)):
                    record["main_activity"]["kinetics"]["kcat"] = parsed
                    nu = _norm_unit(val.get("unit"))
                    record["main_activity"]["kinetics"]["kcat_unit"] = nu if nu else val.get("unit")
                    record["main_activity"]["kinetics"]["source"] = "table"
            except (ValueError, TypeError):
                pass

    if record["main_activity"]["kinetics"]["Km"] is not None:
        return

    for val in table_values:
        raw_text = val.get("raw_text", "") or val.get("text", "")
        if not raw_text:
            continue
        for pat in _KM_PATTERNS:
            m = pat.search(raw_text)
            if m:
                groups = m.groups()
                if len(groups) >= 2:
                    try:
                        km_val = float(groups[-2]) if len(groups) >= 3 else float(groups[0])
                        km_unit = groups[-1] if groups[-1] else None
                        if isinstance(km_val, (int, float)):
                            record["main_activity"]["kinetics"]["Km"] = km_val
                            if km_unit:
                                nu = _norm_unit(km_unit)
                                record["main_activity"]["kinetics"]["Km_unit"] = nu if nu else km_unit
                            record["main_activity"]["kinetics"]["source"] = "table_regex"
                            break
                    except (ValueError, TypeError, IndexError):
                        pass
        if record["main_activity"]["kinetics"]["Km"] is not None:
            break
```

- [ ] **Step 2: 语法检查**

Run: `python -m py_compile extraction_agents.py`

---

## Task 7: 综合验证

**Files:**
- Test: `tests/` 目录

- [ ] **Step 1: 运行全部语法检查**

```bash
python -m py_compile single_main_nanozyme_extractor.py
python -m py_compile extraction_agents.py
python -m py_compile nanozyme_preprocessor_midjson.py
```

- [ ] **Step 2: 运行单元测试**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: 110+ passed, 0 failed

- [ ] **Step 3: 提交**

```bash
git add single_main_nanozyme_extractor.py extraction_agents.py
git commit -m "feat(extraction): 增强规则提取能力 - 扩展正则模式、放宽桶召回、增强表格提取"
```
