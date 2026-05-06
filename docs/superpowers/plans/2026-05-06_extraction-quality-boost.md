# 高质量提取能力增强实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐系统面对各色文献时能力差距最大的5个短板，使规则提取覆盖率从当前~40-50%提升到~65-75%

**Architecture:** 在现有RuleExtractor+Agent架构上，针对5个最大能力缺口进行定向增强——(1)酶类型检测扩展 (2)合成条件深度提取 (3)机制提取扩展 (4)应用提取增强 (5)全文回退策略增强。不改变管道架构，只增强各提取器的模式库和搜索策略。

**Tech Stack:** Python, re (正则), 现有RuleExtractor/Agent框架

---

## 能力差距诊断

| 领域 | 当前覆盖率 | 目标覆盖率 | 差距原因 |
|------|-----------|-----------|---------|
| 酶类型检测 | ~70% | ~90% | 缺少多酶类型、cascade、罕见酶类型 |
| 合成条件 | ~30% | ~65% | 温度/时间/前驱体模式太少，pH/溶剂未提取 |
| 机制提取 | ~25% | ~60% | 只覆盖18种机制模式，缺少催化循环/活性位点描述 |
| 应用提取 | ~45% | ~70% | LOD/analyte模式不够，多应用场景漏检 |
| 全文回退 | ~20% | ~55% | 只回退pH/温度/合成/形貌，不回退动力学/应用/机制 |

---

### Task 1: 扩展酶类型检测模式

**Files:**
- Modify: `single_main_nanozyme_extractor.py:268-347` (_ENZYME_TYPE_PATTERNS)

当前系统只覆盖23种酶类型模式，缺少大量文献中出现的变体：

- [ ] **Step 1: 添加缺失的酶类型模式**

在 `_ENZYME_TYPE_PATTERNS` 末尾添加：

```python
(re.compile(r'\bmulti[-\s]?enzyme[-\s]?like\b', re.I), "multi-enzyme-like"),
(re.compile(r'\bdual[-\s]?enzyme[-\s]?like\b', re.I), "multi-enzyme-like"),
(re.compile(r'\btriple[-\s]?enzyme[-\s]?like\b', re.I), "multi-enzyme-like"),
(re.compile(r'\bperoxidase\s+and\s+oxidase[-\s]?like\b', re.I), "multi-enzyme-like"),
(re.compile(r'\bperoxidase[-\s]?oxidase[-\s]?like\b', re.I), "multi-enzyme-like"),
(re.compile(r'\bPOD[-\s]?like\s+and\s+OXD[-\s]?like\b', re.I), "multi-enzyme-like"),
(re.compile(r'\bcatalase\s+and\s+peroxidase[-\s]?like\b', re.I), "multi-enzyme-like"),
(re.compile(r'\btyrosinase[-\s]?like\b', re.I), "tyrosinase-like"),
(re.compile(r'\bribozyme[-\s]?like\b', re.I), "ribozyme-like"),
(re.compile(r'\bcellulase[-\s]?like\b', re.I), "cellulase-like"),
(re.compile(r'\bamylase[-\s]?like\b', re.I), "amylase-like"),
(re.compile(r'\bprotease[-\s]?like\b', re.I), "protease-like"),
(re.compile(r'\blipase[-\s]?like\b', re.I), "lipase-like"),
(re.compile(r'\burease[-\s]?like\b', re.I), "urease-like"),
(re.compile(r'\bascorbate\s+oxidase[-\s]?like\b', re.I), "ascorbate-oxidase-like"),
(re.compile(r'\bAAO[-\s]?like\b', re.I), "ascorbate-oxidase-like"),
(re.compile(r'\bchloroperoxidase[-\s]?like\b', re.I), "haloperoxidase-like"),
(re.compile(r'\bcytochrome\s+c\s+oxidase[-\s]?like\b', re.I), "oxidase-like"),
(re.compile(r'\bformate\s+dehydrogenase[-\s]?like\b', re.I), "dehydrogenase-like"),
(re.compile(r'\balcohol\s+dehydrogenase[-\s]?like\b', re.I), "dehydrogenase-like"),
(re.compile(r'\bglucose\s+dehydrogenase[-\s]?like\b', re.I), "dehydrogenase-like"),
(re.compile(r'\bDNAse[-\s]?like\b', re.I), "nuclease-like"),
(re.compile(r'\bDNase[-\s]?like\b', re.I), "nuclease-like"),
(re.compile(r'\bRNase[-\s]?like\b', re.I), "nuclease-like"),
(re.compile(r'\binvertase[-\s]?like\b', re.I), "invertase-like"),
(re.compile(r'\bchitinase[-\s]?like\b', re.I), "chitinase-like"),
(re.compile(r'\bxylanase[-\s]?like\b', re.I), "xylanase-like"),
```

- [ ] **Step 2: 增强RuleExtractor中的酶类型搜索策略**

当前酶类型搜索只搜activity+mechanism桶。修改 `RuleExtractor.extract_from_evidence` 中的酶类型检测逻辑，增加搜索范围：

在现有搜索 `buckets.get("activity", []) + buckets.get("mechanism", [])` 之后，增加回退搜索 `buckets.get("kinetics", [])[:5] + buckets.get("application", [])[:3]`。

- [ ] **Step 3: 验证语法**

Run: `python -m py_compile single_main_nanozyme_extractor.py`
Expected: 无错误

---

### Task 2: 深度增强合成条件提取

**Files:**
- Modify: `single_main_nanozyme_extractor.py` (_SYNTHESIS_CONDITION_PATTERNS, _SYNTHESIS_METHODS)

当前合成条件提取只覆盖温度/时间/前驱体，且模式太少。大量文献中的pH条件、溶剂、反应时间变体、煅烧温度等均未提取。

- [ ] **Step 1: 扩展合成温度模式**

在 `_SYNTHESIS_CONDITION_PATTERNS["temperature"]` 中添加：

```python
re.compile(r'\b(?:calcined|annealed|heated|sintered)\s+at\s*([\d.]+)\s*[°º˚]?\s*C', re.I),
re.compile(r'\b(?:calcination|annealing|sintering)\s+(?:temperature|temp)\s*(?:of|was|=|:|≈|~)\s*([\d.]+)\s*[°º˚]?\s*C', re.I),
re.compile(r'\b(?:dried|dry)\s+at\s*([\d.]+)\s*[°º˚]?\s*C', re.I),
re.compile(r'\b(?:maintained|kept|held)\s+at\s*([\d.]+)\s*[°º˚]?\s*C\s+for\b', re.I),
re.compile(r'\b(?:reaction|synthesis)\s+(?:temperature|temp)\s*(?:of|was|=|:)\s*([\d.]+)\s*[°º˚]?\s*C', re.I),
re.compile(r'\b(\d{2,4})\s*[°º˚]?\s*C\s+(?:for|under)\s+\d+\s*h\b', re.I),
```

- [ ] **Step 2: 扩展合成时间模式**

在 `_SYNTHESIS_CONDITION_PATTERNS["time"]` 中添加：

```python
re.compile(r'\bfor\s*([\d.]+)\s*[-–—~to]+\s*([\d.]+)\s*(h|hour|hours|min|minutes|days?)\b', re.I),
re.compile(r'\b(?:aged|stirred|incubated|refluxed)\s+for\s*([\d.]+)\s*(h|hour|hours|min|minutes|days?)\b', re.I),
re.compile(r'\b(?:overnight|for\s+12\s*h|for\s+24\s*h)\b', re.I),
```

- [ ] **Step 3: 添加合成pH条件提取**

在 `_SYNTHESIS_CONDITION_PATTERNS` 中添加新键 `"pH"`：

```python
"pH": [
    re.compile(r'\bpH\s*(?:of|was|=|:|≈|~)\s*([\d.]+)\s*(?:was|in|under|at)\s+the\s+synthesis', re.I),
    re.compile(r'\bsynthesis\s+(?:was\s+)?(?:carried\s+out|performed|conducted)\s+(?:at|under)\s+pH\s*([\d.]+)', re.I),
    re.compile(r'\bpH\s*([\d.]+)\s+(?:was|is)\s+(?:adjusted|maintained)\s+(?:to|at)\s+(?:during|in|for)\s+(?:the\s+)?synthesis', re.I),
    re.compile(r'\b(?:reaction|synthesis)\s+pH\s*(?:of|was|=|:)\s*([\d.]+)', re.I),
],
```

- [ ] **Step 4: 添加合成溶剂提取**

在 `_SYNTHESIS_CONDITION_PATTERNS` 中添加新键 `"solvent"`：

```python
"solvent": [
    re.compile(r'\b(?:dissolved|dispersed)\s+in\s+([\w\-]+(?:\s[\w\-]+){0,2})\b', re.I),
    re.compile(r'\b(?:using|with|in)\s+([\w\-]+(?:\s[\w\-]+){0,2})\s+as\s+(?:the\s+)?solvent\b', re.I),
    re.compile(r'\bsolvent\s*(?:was|:|=)\s*([\w\-]+(?:\s[\w\-]+){0,2})\b', re.I),
],
```

- [ ] **Step 5: 在_extract_synthesis_method中集成新条件提取**

在 `_extract_synthesis_method` 方法中，在现有温度/时间/前驱体提取之后，添加pH和溶剂提取逻辑：

```python
if synth_cond.get("pH") is None:
    for text in synthesis_texts:
        for pat in _SYNTHESIS_CONDITION_PATTERNS.get("pH", []):
            m = pat.search(text)
            if m:
                synth_cond["pH"] = m.group(1)
                break
        if synth_cond.get("pH"):
            break

if not synth_cond.get("solvent"):
    for text in synthesis_texts:
        for pat in _SYNTHESIS_CONDITION_PATTERNS.get("solvent", []):
            m = pat.search(text)
            if m:
                raw = m.group(1).strip()
                if raw.lower() not in ("the", "a", "an", "this"):
                    synth_cond["solvent"] = raw
                break
        if synth_cond.get("solvent"):
            break
```

- [ ] **Step 6: 验证语法**

Run: `python -m py_compile single_main_nanozyme_extractor.py`
Expected: 无错误

---

### Task 3: 大幅扩展机制提取模式

**Files:**
- Modify: `single_main_nanozyme_extractor.py:4245-4269` (_MECHANISM_PATTERNS)

当前只覆盖18种机制模式，大量文献中的催化机制描述无法提取。

- [ ] **Step 1: 添加缺失的机制模式**

在 `_MECHANISM_PATTERNS` 末尾添加：

```python
(re.compile(r'\bFenton\b', re.I), "Fenton-like"),
(re.compile(r'\bphoto[-\s]?Fenton\b', re.I), "photo-Fenton"),
(re.compile(r'\bsono[-\s]?Fenton\b', re.I), "sono-Fenton"),
(re.compile(r'\belectro[-\s]?Fenton\b', re.I), "electro-Fenton"),
(re.compile(r'\b\*O2[-\^]?\b|\bsuperoxide\s+radical', re.I), "superoxide generation"),
(re.compile(r'\b1O2\b', re.I), "singlet oxygen generation"),
(re.compile(r'\b\*OH\b|\bhydroxyl\s+radical', re.I), "hydroxyl radical generation"),
(re.compile(r'\bradical\s+scaveng', re.I), "radical scavenging"),
(re.compile(r'\bROS[-\s]mediated\b', re.I), "ROS-mediated"),
(re.compile(r'\bROS[-\s]induced\b', re.I), "ROS-induced"),
(re.compile(r'\bcatalytic\s+cycle\b', re.I), "catalytic cycle"),
(re.compile(r'\bactive\s+site\b', re.I), "active site catalysis"),
(re.compile(r'\bM[-\s]N[xc]\d?\s+(?:site|center|coordination|moiety)\b', re.I), "M-Nx site catalysis"),
(re.compile(r'\bsingle[-\s]?atom\s+(?:site|center|catalyst)', re.I), "single-atom catalysis"),
(re.compile(r'\bSA[-\s]?C\b', re.I), "single-atom catalysis"),
(re.compile(r'\bdefect[-\s]?mediated\b', re.I), "defect-mediated"),
(re.compile(r'\boxygen\s+vacancy\b', re.I), "oxygen vacancy mediated"),
(re.compile(r'\bsulfur\s+vacancy\b', re.I), "sulfur vacancy mediated"),
(re.compile(r'\bnitrogen\s+vacancy\b', re.I), "nitrogen vacancy mediated"),
(re.compile(r'\bsurface[-\s]?mediated\b', re.I), "surface-mediated"),
(re.compile(r'\badsorption[-\s]?mediated\b', re.I), "adsorption-mediated"),
(re.compile(r'\binterfacial\s+catalys', re.I), "interfacial catalysis"),
(re.compile(r'\benzyme[-\s]?mimick', re.I), "enzyme-mimicking"),
(re.compile(r'\bbiomimetic\s+catalys', re.I), "biomimetic catalysis"),
(re.compile(r'\bchemodynamic\s+therap', re.I), "chemodynamic"),
(re.compile(r'\bphotodynamic\s+therap', re.I), "photodynamic"),
(re.compile(r'\bsonodynamic\s+therap', re.I), "sonodynamic"),
(re.compile(r'\bGSH\s+deplet', re.I), "GSH depletion"),
(re.compile(r'\bglutathione\s+deplet', re.I), "GSH depletion"),
(re.compile(r'\b\*OOH\b', re.I), "hydroperoxyl radical generation"),
(re.compile(r'\bH2O2\s+generat', re.I), "H2O2 generation"),
(re.compile(r'\bwater\s+oxidation\b', re.I), "water oxidation"),
(re.compile(r'\boxygen\s+evolution\b', re.I), "oxygen evolution"),
(re.compile(r'\boxygen\s+reduction\b', re.I), "oxygen reduction"),
(re.compile(r'\bhydrogen\s+evolution\b', re.I), "hydrogen evolution"),
(re.compile(r'\bCO2\s+reduction\b', re.I), "CO2 reduction"),
(re.compile(r'\bN2\s+fixation\b', re.I), "N2 fixation"),
```

- [ ] **Step 2: 扩展机制搜索范围**

当前 `_extract_mechanism` 只搜 `mechanism + activity` 桶。修改搜索范围为 `mechanism + activity + kinetics[:5] + application[:3]`：

在 `RuleExtractor.extract_from_evidence` 中修改：
```python
self._extract_mechanism(record, buckets.get("mechanism", []) + buckets.get("activity", []) + buckets.get("kinetics", [])[:5] + buckets.get("application", [])[:3])
```

- [ ] **Step 3: 验证语法**

Run: `python -m py_compile single_main_nanozyme_extractor.py`
Expected: 无错误

---

### Task 4: 增强应用提取的多场景覆盖

**Files:**
- Modify: `single_main_nanozyme_extractor.py:4047-4096` (_APP_TYPE_KEYWORDS)
- Modify: `single_main_nanozyme_extractor.py:4091-4143` (_extract_applications_from_text)

当前应用提取只覆盖6种应用类型，且LOD/analyte模式不够灵活。

- [ ] **Step 1: 扩展应用类型关键词**

在 `_APP_TYPE_KEYWORDS` 中添加：

```python
"food_safety": ["food saf", "food analy", "milk", "juice", "wine", "beer", "honey",
                "meat", "fish", "fruit", "vegetable", "beverage", "food-borne"],
"cytoprotection": ["cytoprotect", "cell protect", "neuroprotect", "cardioprotect",
                    "hepatoprotect", "renoprotect", "radioprotect"],
"immunoassay": ["immunoassay", "ELISA", "lateral flow", "paper-based", "point-of-care",
                "POC", "rapid test", "strip test"],
"drug_delivery": ["drug delivery", "drug release", "controlled release", "nanocarrier",
                  "nanovehicle", "cargo delivery"],
```

- [ ] **Step 2: 增强LOD提取的宽松回退**

在 `_extract_applications_from_text` 中，当所有 `_LOD_PATTERNS` 都未匹配时，添加宽松回退：

```python
if not app.get("detection_limit"):
    lod_fallback = re.search(
        r'([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm|pM|fM)\b[^.]{0,20}?\b(?:LOD|detection\s+limit|limit\s+of\s+detection)\b',
        text, re.I,
    )
    if not lod_fallback:
        lod_fallback = re.search(
            r'(?:LOD|detection\s+limit)\b[^.]{0,30}?([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm)',
            text, re.I,
        )
    if lod_fallback:
        app["detection_limit"] = f"{lod_fallback.group(1)} {lod_fallback.group(2)}"
```

- [ ] **Step 3: 增强analyte提取的宽松回退**

在 `_extract_applications_from_text` 中，当所有 `_ANALYTE_PATTERNS` 都未匹配时，添加宽松回退：

```python
if not app.get("target_analyte"):
    analyte_fallback = re.search(
        r'\b(?:of|for)\s+([\w\-]+(?:\s[\w\-]+){0,2})\s+(?:was|is|has|with)\s+(?:detected|sensed|determined|measured)',
        text, re.I,
    )
    if analyte_fallback:
        candidate = analyte_fallback.group(1).strip()
        if len(candidate) > 2 and candidate.lower() not in ("the", "this", "that", "it"):
            app["target_analyte"] = candidate
```

- [ ] **Step 4: 验证语法**

Run: `python -m py_compile single_main_nanozyme_extractor.py`
Expected: 无错误

---

### Task 5: 大幅增强全文回退提取策略

**Files:**
- Modify: `single_main_nanozyme_extractor.py:3931-4046` (_fulltext_fallback_extract)

当前全文回退只覆盖pH/温度/合成/形貌/晶型/尺寸，不回退动力学/应用/机制等关键字段。

- [ ] **Step 1: 添加动力学全文回退**

在 `_fulltext_fallback_extract` 中，在现有回退逻辑之后添加：

```python
kin = act.get("kinetics", {})
if kin.get("Km") is None:
    for pat in _KM_PATTERNS:
        m = pat.search(all_text)
        if not m:
            m = pat.search(norm_text)
        if m:
            groups = m.groups()
            try:
                if len(groups) >= 2:
                    km_val = _parse_scientific_notation(str(groups[-2] if len(groups) >= 3 else groups[0]))
                    km_unit = groups[-1] if groups[-1] else None
                    if isinstance(km_val, (int, float)):
                        kin["Km"] = km_val
                        if km_unit:
                            nu = _normalize_unit_fn(km_unit)
                            kin["Km_unit"] = nu if nu else km_unit
                        kin["source"] = "fulltext_fallback"
                        logger.info(f"[SMN] Fulltext fallback: Km={km_val} {km_unit}")
                        break
            except (ValueError, TypeError, IndexError):
                pass

if kin.get("Vmax") is None:
    for pat in _VMAX_PATTERNS:
        m = pat.search(all_text)
        if not m:
            m = pat.search(norm_text)
        if m:
            groups = m.groups()
            try:
                if len(groups) >= 2:
                    g0, g1 = groups[-2], groups[-1]
                    vmax_val = _parse_scientific_notation(str(g0))
                    if isinstance(vmax_val, (int, float)):
                        kin["Vmax"] = vmax_val
                        nu = _normalize_unit_fn(g1) if g1 else None
                        kin["Vmax_unit"] = nu if nu else g1
                        kin["source"] = "fulltext_fallback"
                        logger.info(f"[SMN] Fulltext fallback: Vmax={vmax_val} {g1}")
                        break
            except (ValueError, TypeError, IndexError):
                pass

if kin.get("kcat") is None:
    for pat in _KCAT_PATTERNS:
        m = pat.search(all_text)
        if not m:
            m = pat.search(norm_text)
        if m:
            groups = m.groups()
            try:
                if len(groups) >= 2:
                    kcat_val = _parse_scientific_notation(str(groups[-2] if len(groups) >= 3 else groups[0]))
                    kcat_unit = groups[-1] if groups[-1] else "s^-1"
                    if isinstance(kcat_val, (int, float)):
                        kin["kcat"] = kcat_val
                        nu = _normalize_unit_fn(kcat_unit)
                        kin["kcat_unit"] = nu if nu else kcat_unit
                        kin["source"] = "fulltext_fallback"
                        logger.info(f"[SMN] Fulltext fallback: kcat={kcat_val} {kcat_unit}")
                        break
            except (ValueError, TypeError, IndexError):
                pass
```

- [ ] **Step 2: 添加应用全文回退**

```python
if not record.get("applications"):
    app = {}
    for pat in _LOD_PATTERNS:
        lod_m = pat.search(all_text)
        if not lod_m:
            lod_m = pat.search(norm_text)
        if lod_m:
            app["detection_limit"] = f"{lod_m.group(1)} {lod_m.group(2)}"
            break
    for pat in _LINEAR_RANGE_PATTERNS:
        lr_m = pat.search(all_text)
        if not lr_m:
            lr_m = pat.search(norm_text)
        if lr_m:
            app["linear_range"] = f"{lr_m.group(1)} {lr_m.group(2)}"
            break
    tl = all_text.lower()
    for app_type, keywords in self._APP_TYPE_KEYWORDS.items():
        if any(kw in tl for kw in keywords):
            app["application_type"] = app_type
            break
    for pat in self._ANALYTE_PATTERNS:
        m = pat.search(all_text)
        if m:
            analyte = m.group(1).strip() if m.lastindex else m.group(0).strip()
            if len(analyte) > 2:
                app["target_analyte"] = analyte
            break
    if any(v is not None for v in app.values()):
        for key in ("application_type", "target_analyte", "method", "linear_range",
                    "detection_limit", "sample_type", "notes"):
            app.setdefault(key, None)
        app["_evidence"] = "fulltext_fallback"
        record["applications"].append(app)
        logger.info(f"[SMN] Fulltext fallback: application={app}")
```

- [ ] **Step 3: 添加机制全文回退**

```python
if not act.get("mechanism"):
    for pat, mech in self._MECHANISM_PATTERNS:
        if pat.search(all_text):
            act["mechanism"] = mech
            logger.info(f"[SMN] Fulltext fallback: mechanism={mech}")
            break
```

- [ ] **Step 4: 验证语法**

Run: `python -m py_compile single_main_nanozyme_extractor.py`
Expected: 无错误

---

### Task 6: 综合验证与提交

- [ ] **Step 1: 运行全部单元测试**

Run: `python -m pytest tests/ -v --tb=short`
Expected: 110 passed, 0 failed

- [ ] **Step 2: 提交到GitHub**

```bash
git add single_main_nanozyme_extractor.py
git commit -m "feat(extraction): 大幅增强规则提取能力 - 酶类型/合成条件/机制/应用/全文回退"
git push
```

- [ ] **Step 3: 写迭代记录**

在 `docs/iteration_logs/` 中创建 `2026-05-06_extraction-quality-boost.md`
