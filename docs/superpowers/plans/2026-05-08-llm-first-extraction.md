# LLM-First提取架构替代规则提取 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用LLM-First架构替代当前规则提取（RuleExtractor），借鉴三篇文献的方法论，提升纳米酶数据提取的准确率和鲁棒性

**Architecture:** 采用"LLM结构化提取 + Constrained Decoding + 化学知识验证"三层架构。第一层用LLM（few-shot prompt + JSON schema约束）替代正则规则提取动力学/形态/应用等字段；第二层用constrained decoding确保输出符合schema；第三层用化学知识一致性检查替代当前的后处理校验。保留VLM提取图表数据的能力不变。

**Tech Stack:** Python 3.9+, OpenAI API (GPT-4o/structured output), outlines/instructor (constrained decoding), 现有extraction_pipeline基础设施

---

## 文献方法总结

### Paper A (CMPB 2025): LLM-RawDMeth
- **核心方法**: 模糊逻辑(Fuzzy Logic)专家知识建模 + Prompt Engineering + Fine-tuning
- **关键创新**: 
  1. 用专家知识将原始数据建模为结构化特征（模糊集定义），再喂给LLM
  2. 定义了多维度评估框架（而非单一BLEU/ROUGE）
  3. Fine-tuned GPT-4o在领域任务上达到96%准确率
- **对本系统的启示**: 用纳米酶领域知识（酶类型映射、单位体系、量级范围）构建结构化prompt，而非让LLM从原始文本自由提取

### Paper B (Chem Soc Rev 2025): From Text to Insight
- **核心方法**: LLM化学数据提取全流程综述
- **关键创新**:
  1. **Constrained Decoding**: 用formal grammar/JSON schema约束LLM输出，确保结构化数据语法正确（outlines/instructor库）
  2. **Few-shot + Self-augmentation**: 两步提取——先提取，再用第一次结果增强第二次prompt
  3. **化学知识验证**: 用cheminformatics工具验证提取结果一致性（如NMR与分子式匹配）
  4. **Human-in-the-loop annotation**: 模型先标注，人修正，修正数据再fine-tune
  5. **RAG + 分类预筛选**: 先分类文本块是否包含目标信息，再提取
- **对本系统的启示**: 
  - 用constrained decoding替代当前的正则+后处理校验
  - 用化学知识验证（Km量级、Vmax单位、酶类型兼容性）替代NumericValidator
  - Self-augmentation两步提取可提高准确率

### Paper C (Nature Communications 2025): LEADS
- **核心方法**: 领域专用基础模型 + Instruction Tuning
- **关键创新**:
  1. **Instruction Tuning**: 在633K样本上fine-tune Mistral-7B，超越GPT-4o
  2. **任务分解**: 将文献挖掘分解为6个子任务，每个子任务独立instruction
  3. **Expert+AI协作**: AI先提取，专家审阅，节省26.9%时间
  4. **PICO框架**: 用结构化框架（Population/Intervention/Comparison/Outcome）指导提取
- **对本系统的启示**: 
  - 将提取任务分解为独立子任务（材料识别/动力学/形态/应用），每个子任务有独立prompt
  - Instruction tuning在领域数据上可超越通用大模型
  - Expert+AI协作模式适合当前系统的GUI审阅流程

---

## 当前系统架构分析

### 规则提取的瓶颈

当前提取流程: `RuleExtractor → LLM精炼 → VLM图表 → CrossValidation → ConsistencyAgent → NumericValidator → Schema验证`

**规则提取（RuleExtractor）的核心问题**:
1. **正则模式爆炸**: `_KM_PATTERNS`等已有50+个正则，但仍无法覆盖所有表述变体
2. **上下文丢失**: 正则逐行匹配，无法理解"上述值"等指代关系
3. **多底物处理弱**: 只提取第一个匹配的Km/Vmax，多底物动力学数据大量丢失
4. **材料名识别差**: 基于频率+后缀的候选评分无法识别单原子催化剂等新型命名
5. **酶类型混淆**: peroxidase/catalase/oxidase在多酶活性论文中常误判
6. **维护成本高**: 每发现新表述格式就要加正则，不可扩展

### LLM提取的现状

当前系统已有LLM提取（`_call_llm_with_refinement`），但存在以下问题:
1. LLM提取是"精炼"角色，只在规则提取后补充，而非主导
2. LLM prompt没有schema约束，输出格式不稳定
3. 没有利用few-shot examples
4. 没有constrained decoding，JSON解析经常失败
5. LLM提取和规则提取的冲突解决逻辑（CrossValidationAgent）过于复杂

---

## 文件结构

```
d:\ocrwiki版本\single_main_nanozyme\
├── llm_structured_extractor.py     [新建] LLM结构化提取核心模块
├── extraction_prompts.py           [新建] 提取prompt模板库
├── schema_constraints.py           [新建] JSON schema约束定义
├── extraction_agents.py            [修改] 保留Agent类但改用LLM提取
├── single_main_nanozyme_extractor.py [修改] 调整提取流程顺序
├── extraction_pipeline.py          [修改] 适配新提取器
├── numeric_validator.py            [修改] 增强化学知识验证
├── consistency_agent.py            [不变] 一致性修正逻辑保留
├── cross_validation_agent.py       [修改] 简化合并逻辑
└── tests/
    ├── test_llm_structured_extractor.py  [新建]
    └── test_schema_constraints.py        [新建]
```

---

### Task 1: 创建schema约束模块

**Files:**
- Create: `d:\ocrwiki版本\single_main_nanozyme\schema_constraints.py`
- Test: `d:\ocrwiki版本\single_main_nanozyme\tests\test_schema_constraints.py`

借鉴Paper B的constrained decoding思想，定义JSON schema用于约束LLM输出格式。当前系统的`EMPTY_RECORD`和`validate_schema`定义了输出结构，但没有用于约束LLM生成。

- [ ] **Step 1: 编写schema_constraints.py**

```python
import json
from typing import Dict, Any, List, Optional

NANOZYME_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "selected_nanozyme": {
            "type": "object",
            "properties": {
                "name": {"type": ["string", "null"]},
                "morphology": {"type": ["string", "null"]},
                "size": {"type": ["number", "string", "null"]},
                "size_unit": {"type": ["string", "null"], "enum": ["nm", "μm", "mm", None]},
                "crystal_structure": {"type": ["string", "null"]},
                "surface_area": {"type": ["string", "null"]},
                "synthesis_method": {"type": ["string", "null"]},
                "characterization": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["name"]
        },
        "main_activity": {
            "type": "object",
            "properties": {
                "enzyme_like_type": {
                    "type": ["string", "null"],
                    "enum": [
                        "peroxidase-like", "oxidase-like", "catalase-like",
                        "superoxide-dismutase-like", "glucose-oxidase-like",
                        "haloperoxidase-like", "nanozyme-like", None
                    ]
                },
                "substrates": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "kinetics": {
                    "type": "object",
                    "properties": {
                        "Km": {"type": ["number", "null"]},
                        "Km_unit": {"type": ["string", "null"]},
                        "Vmax": {"type": ["number", "null"]},
                        "Vmax_unit": {"type": ["string", "null"]},
                        "kcat": {"type": ["number", "null"]},
                        "kcat_unit": {"type": ["string", "null"]},
                        "substrate": {"type": ["string", "null"]}
                    }
                },
                "kinetics_list": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "Km": {"type": ["number", "null"]},
                            "Km_unit": {"type": ["string", "null"]},
                            "Vmax": {"type": ["number", "null"]},
                            "Vmax_unit": {"type": ["string", "null"]},
                            "kcat": {"type": ["number", "null"]},
                            "kcat_unit": {"type": ["string", "null"]},
                            "substrate": {"type": ["string", "null"]}
                        }
                    }
                },
                "pH_profile": {
                    "type": "object",
                    "properties": {
                        "optimal_pH": {"type": ["number", "null"]},
                        "pH_range": {"type": ["string", "null"]}
                    }
                },
                "temperature_profile": {
                    "type": "object",
                    "properties": {
                        "optimal_temperature": {"type": ["number", "null"]},
                        "temperature_range": {"type": ["string", "null"]}
                    }
                }
            }
        },
        "applications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "application_type": {"type": ["string", "null"]},
                    "target_analyte": {"type": ["string", "null"]},
                    "detection_limit": {"type": ["number", "null"]},
                    "detection_limit_unit": {"type": ["string", "null"]},
                    "method": {"type": ["string", "null"]},
                    "sample_type": {"type": ["string", "null"]}
                }
            }
        }
    },
    "required": ["selected_nanozyme", "main_activity"]
}


def get_schema_for_openai() -> Dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "nanozyme_extraction",
            "strict": True,
            "schema": NANOZYME_EXTRACTION_SCHEMA
        }
    }


def validate_against_schema(data: Dict[str, Any]) -> List[str]:
    errors = []
    sel = data.get("selected_nanozyme", {})
    if not isinstance(sel, dict) or not sel.get("name"):
        errors.append("selected_nanozyme.name is required")

    ma = data.get("main_activity", {})
    etype = ma.get("enzyme_like_type")
    if etype and etype not in [e for e in NANOZYME_EXTRACTION_SCHEMA["properties"]["main_activity"]["properties"]["enzyme_like_type"]["enum"] if e is not None]:
        errors.append(f"enzyme_like_type '{etype}' not in allowed enum")

    kin = ma.get("kinetics", {})
    if isinstance(kin, dict):
        km = kin.get("Km")
        km_u = kin.get("Km_unit")
        if isinstance(km, (int, float)) and km_u == "M" and km > 1.0:
            errors.append(f"Km={km} M is unrealistically large")
        vmax = kin.get("Vmax")
        vmax_u = kin.get("Vmax_unit")
        if isinstance(vmax, (int, float)) and vmax_u in ("M/s", "M·s-1", "M s^-1") and abs(vmax) < 1.0:
            errors.append(f"Vmax={vmax} {vmax_u} should be converted to μM/s")

    return errors
```

- [ ] **Step 2: 编写test_schema_constraints.py**

```python
import pytest
from schema_constraints import validate_against_schema, NANOZYME_EXTRACTION_SCHEMA


def test_valid_data_passes():
    data = {
        "selected_nanozyme": {"name": "Fe3O4"},
        "main_activity": {"enzyme_like_type": "peroxidase-like"}
    }
    errors = validate_against_schema(data)
    assert len(errors) == 0


def test_missing_name_fails():
    data = {"selected_nanozyme": {}, "main_activity": {}}
    errors = validate_against_schema(data)
    assert any("name is required" in e for e in errors)


def test_invalid_enzyme_type():
    data = {
        "selected_nanozyme": {"name": "Fe3O4"},
        "main_activity": {"enzyme_like_type": "invalid-type"}
    }
    errors = validate_against_schema(data)
    assert any("not in allowed enum" in e for e in errors)


def test_unrealistic_km():
    data = {
        "selected_nanozyme": {"name": "Fe3O4"},
        "main_activity": {
            "kinetics": {"Km": 8.0, "Km_unit": "M"}
        }
    }
    errors = validate_against_schema(data)
    assert any("unrealistically large" in e for e in errors)


def test_vmax_m_per_s_conversion_needed():
    data = {
        "selected_nanozyme": {"name": "Fe3O4"},
        "main_activity": {
            "kinetics": {"Vmax": 4.41e-05, "Vmax_unit": "M/s"}
        }
    }
    errors = validate_against_schema(data)
    assert any("converted" in e for e in errors)
```

- [ ] **Step 3: 运行测试确认通过**

Run: `cd d:\ocrwiki版本\single_main_nanozyme && python -m pytest tests/test_schema_constraints.py -v`
Expected: 5 passed

- [ ] **Step 4: Commit**

```bash
git add schema_constraints.py tests/test_schema_constraints.py
git commit -m "feat(extraction): 添加JSON schema约束模块用于LLM结构化输出"
```

---

### Task 2: 创建提取prompt模板库

**Files:**
- Create: `d:\ocrwiki版本\single_main_nanozyme\extraction_prompts.py`

借鉴Paper B的few-shot prompting和Paper A的专家知识建模思想，为每个提取子任务设计结构化prompt。

- [ ] **Step 1: 编写extraction_prompts.py**

```python
from typing import Dict, List, Optional

SYSTEM_PROMPT = """You are an expert nanozyme data extractor. Your task is to extract structured data from scientific literature about nanozymes.

Key domain knowledge:
- A nanozyme is a nanomaterial with enzyme-like catalytic activity
- Enzyme-like types include: peroxidase-like, oxidase-like, catalase-like, superoxide-dismutase-like, glucose-oxidase-like, haloperoxidase-like
- Km (Michaelis constant) is typically in range 0.001-100 mM; values >1 M are likely errors
- Vmax is typically reported in μM/s, mM/s, or M/s; M/s values <1.0 should be converted to μM/s (multiply by 1e6)
- Common substrates: TMB, ABTS, DAB, OPD, H2O2 for peroxidase-like; glucose for glucose-oxidase-like
- When multiple substrates are tested, extract kinetics for EACH substrate separately into kinetics_list
- Material names with @ or / (e.g., Fe3O4@C, Co-N-C) indicate composite or doped materials, which are MORE specific than simple oxide names (e.g., Fe3O4)

Rules:
1. Extract ONLY information explicitly stated in the text
2. If a value is not found, use null (not 0 or empty string)
3. Include units exactly as reported, then we will normalize later
4. For multi-substrate kinetics, put the PRIMARY substrate in kinetics and ALL substrates in kinetics_list
5. Prefer specific morphology descriptions (e.g., "uniform hollow polyhedral") over generic terms (e.g., "nanoparticle")
"""

KINETICS_EXTRACTION_PROMPT = """Extract kinetic parameters from the following text about a nanozyme named "{nanozyme_name}".

Focus on:
- Km (Michaelis constant) with unit
- Vmax (maximum velocity) with unit  
- kcat (turnover number) with unit
- Substrate name for each kinetic parameter
- If multiple substrates are tested, extract kinetics for EACH substrate

Text:
{text}

Respond in JSON format:
{schema_hint}"""

KINETICS_FEW_SHOT_EXAMPLES = [
    {
        "input": "The Michaelis-Menten constant (Km) of Fe3O4@C for TMB was 0.35 mM, and the maximum velocity (Vmax) was 4.41 × 10⁻⁵ M/s. For H2O2, Km was 0.89 mM and Vmax was 7.9 × 10⁻⁸ M/s.",
        "output": {
            "kinetics": {
                "Km": 0.35, "Km_unit": "mM",
                "Vmax": 44.1, "Vmax_unit": "μM/s",
                "kcat": None, "kcat_unit": None,
                "substrate": "TMB"
            },
            "kinetics_list": [
                {"Km": 0.35, "Km_unit": "mM", "Vmax": 44.1, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "substrate": "TMB"},
                {"Km": 0.89, "Km_unit": "mM", "Vmax": 0.079, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "substrate": "H2O2"}
            ]
        }
    },
    {
        "input": "The apparent Km value was determined to be 18.1 mM and Vmax was 8.32 × 10⁻² μM/s for the oxidation of TMB catalyzed by Co-N3PS.",
        "output": {
            "kinetics": {
                "Km": 18.1, "Km_unit": "mM",
                "Vmax": 0.0832, "Vmax_unit": "μM/s",
                "kcat": None, "kcat_unit": None,
                "substrate": "TMB"
            },
            "kinetics_list": [
                {"Km": 18.1, "Km_unit": "mM", "Vmax": 0.0832, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "substrate": "TMB"}
            ]
        }
    },
    {
        "input": "The kcat/Km of Au@Pd nanozyme for TMB substrate was 2.5 × 10⁵ M⁻¹s⁻¹, with kcat = 85200 s⁻¹ and Km = 0.3496 mM.",
        "output": {
            "kinetics": {
                "Km": 0.3496, "Km_unit": "mM",
                "Vmax": None, "Vmax_unit": None,
                "kcat": 85200.0, "kcat_unit": "s⁻¹",
                "substrate": "TMB"
            },
            "kinetics_list": [
                {"Km": 0.3496, "Km_unit": "mM", "Vmax": None, "Vmax_unit": None, "kcat": 85200.0, "kcat_unit": "s⁻¹", "substrate": "TMB"}
            ]
        }
    }
]

MORPHOLOGY_EXTRACTION_PROMPT = """Extract morphology and physical properties of the nanozyme "{nanozyme_name}" from the following text.

Focus on:
- Morphology: specific shape description (e.g., "uniform hollow polyhedral", "core-shell spherical", NOT just "nanoparticle")
- Size with unit (nm, μm, etc.)
- Crystal structure (e.g., "cubic", "spinel")
- Surface area with unit
- Synthesis method

Text:
{text}

Respond in JSON format:
{schema_hint}"""

MORPHOLOGY_FEW_SHOT_EXAMPLES = [
    {
        "input": "The Fe3O4@C nanoparticles exhibited a core-shell structure with an average diameter of 200 nm. TEM images revealed uniform spherical morphology. The BET surface area was 120.5 m²/g. The nanoparticles were synthesized via a hydrothermal method at 180°C for 12 h.",
        "output": {
            "morphology": "core-shell spherical",
            "size": 200.0,
            "size_unit": "nm",
            "crystal_structure": None,
            "surface_area": "120.5 m²/g",
            "synthesis_method": "hydrothermal"
        }
    }
]

APPLICATION_EXTRACTION_PROMPT = """Extract application information of the nanozyme "{nanozyme_name}" from the following text.

Focus on:
- Application type (e.g., "biosensing", "therapeutic", "antibacterial", "environmental remediation")
- Target analyte (what is being detected)
- Detection limit (LOD) with unit
- Detection method (e.g., "colorimetric", "fluorescent", "electrochemical")
- Sample type (e.g., "serum", "water", "cell")

Text:
{text}

Respond in JSON format:
{schema_hint}"""

APPLICATION_FEW_SHOT_EXAMPLES = [
    {
        "input": "The colorimetric detection of glucose was achieved using Fe3O4@C nanozyme with a detection limit of 0.15 μM in human serum samples.",
        "output": {
            "applications": [
                {
                    "application_type": "biosensing",
                    "target_analyte": "glucose",
                    "detection_limit": 0.15,
                    "detection_limit_unit": "μM",
                    "method": "colorimetric",
                    "sample_type": "serum"
                }
            ]
        }
    }
]

ENZYME_TYPE_EXTRACTION_PROMPT = """Identify the PRIMARY enzyme-like activity type of the nanozyme "{nanozyme_name}" from the following text.

Important: If the text mentions MULTIPLE enzyme-like activities, identify the one that is:
1. Most extensively studied (most kinetic data provided)
2. Mentioned first in the abstract or results
3. The focus of the application section

Allowed types: peroxidase-like, oxidase-like, catalase-like, superoxide-dismutase-like, glucose-oxidase-like, haloperoxidase-like

Text:
{text}

Respond with a single JSON object:
{{"enzyme_like_type": "<type or null>"}}"""

SELF_AUGMENTATION_PROMPT = """You previously extracted the following data from a nanozyme paper:

{previous_extraction}

Now review your extraction against the original text and check for:
1. Any missed values (especially in tables or figure captions)
2. Unit conversion errors (M/s → μM/s, etc.)
3. Incorrect enzyme type assignment
4. Missing multi-substrate kinetics data

Original text:
{text}

Provide a CORRECTED extraction in the same JSON format. Only change values you are confident are wrong."""


def build_kinetics_prompt(nanozyme_name: str, text: str, include_examples: bool = True) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if include_examples:
        for ex in KINETICS_FEW_SHOT_EXAMPLES:
            messages.append({"role": "user", "content": KINETICS_EXTRACTION_PROMPT.format(
                nanozyme_name=nanozyme_name, text=ex["input"],
                schema_hint="Extract kinetics data as JSON"
            )})
            messages.append({"role": "assistant", "content": json.dumps(ex["output"], ensure_ascii=False)})
    messages.append({"role": "user", "content": KINETICS_EXTRACTION_PROMPT.format(
        nanozyme_name=nanozyme_name, text=text,
        schema_hint="Extract kinetics data as JSON"
    )})
    return messages


def build_morphology_prompt(nanozyme_name: str, text: str, include_examples: bool = True) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if include_examples:
        for ex in MORPHOLOGY_FEW_SHOT_EXAMPLES:
            messages.append({"role": "user", "content": MORPHOLOGY_EXTRACTION_PROMPT.format(
                nanozyme_name=nanozyme_name, text=ex["input"],
                schema_hint="Extract morphology data as JSON"
            )})
            messages.append({"role": "assistant", "content": json.dumps(ex["output"], ensure_ascii=False)})
    messages.append({"role": "user", "content": MORPHOLOGY_EXTRACTION_PROMPT.format(
        nanozyme_name=nanozyme_name, text=text,
        schema_hint="Extract morphology data as JSON"
    )})
    return messages


def build_application_prompt(nanozyme_name: str, text: str, include_examples: bool = True) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if include_examples:
        for ex in APPLICATION_FEW_SHOT_EXAMPLES:
            messages.append({"role": "user", "content": APPLICATION_EXTRACTION_PROMPT.format(
                nanozyme_name=nanozyme_name, text=ex["input"],
                schema_hint="Extract application data as JSON"
            )})
            messages.append({"role": "assistant", "content": json.dumps(ex["output"], ensure_ascii=False)})
    messages.append({"role": "user", "content": APPLICATION_EXTRACTION_PROMPT.format(
        nanozyme_name=nanozyme_name, text=text,
        schema_hint="Extract application data as JSON"
    )})
    return messages


def build_enzyme_type_prompt(nanozyme_name: str, text: str) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.append({"role": "user", "content": ENZYME_TYPE_EXTRACTION_PROMPT.format(
        nanozyme_name=nanozyme_name, text=text
    )})
    return messages


def build_self_augmentation_prompt(previous_extraction: str, text: str) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.append({"role": "user", "content": SELF_AUGMENTATION_PROMPT.format(
        previous_extraction=previous_extraction, text=text
    )})
    return messages
```

注意: 需要在文件顶部添加 `import json`

- [ ] **Step 2: 语法检查**

Run: `cd d:\ocrwiki版本\single_main_nanozyme && python -m py_compile extraction_prompts.py`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add extraction_prompts.py
git commit -m "feat(extraction): 添加LLM提取prompt模板库（few-shot + self-augmentation）"
```

---

### Task 3: 创建LLM结构化提取核心模块

**Files:**
- Create: `d:\ocrwiki版本\single_main_nanozyme\llm_structured_extractor.py`
- Test: `d:\ocrwiki版本\single_main_nanozyme\tests\test_llm_structured_extractor.py`

这是核心模块，实现LLM-First提取逻辑，替代RuleExtractor。借鉴Paper B的constrained decoding和Paper C的任务分解思想。

- [ ] **Step 1: 编写llm_structured_extractor.py**

```python
import json
import logging
import re
from typing import Dict, List, Any, Optional, Tuple

from extraction_prompts import (
    build_kinetics_prompt, build_morphology_prompt,
    build_application_prompt, build_enzyme_type_prompt,
    build_self_augmentation_prompt,
)
from schema_constraints import validate_against_schema

logger = logging.getLogger(__name__)


class LLMStructuredExtractor:
    def __init__(self, client, config=None):
        self.client = client
        self.config = config
        self.model = getattr(config, "llm_model", "gpt-4o") if config else "gpt-4o"
        self.temperature = 0.0
        self.max_tokens = 4096
        self.enable_self_augmentation = getattr(config, "enable_self_augmentation", True) if config else True
        self.enable_constrained_output = getattr(config, "enable_constrained_output", True) if config else True

    async def extract_kinetics(self, nanozyme_name: str, text_chunks: List[str],
                                table_texts: List[str] = None) -> Dict[str, Any]:
        combined_text = self._prepare_text(text_chunks, max_chars=6000)
        if table_texts:
            table_combined = "\n\n[Table data]:\n" + "\n".join(table_texts[:5])
            combined_text += table_combined[:3000]

        messages = build_kinetics_prompt(nanozyme_name, combined_text)
        result = await self._call_llm_structured(messages, "kinetics")

        if self.enable_self_augmentation and result:
            augmented = await self._self_augment(result, combined_text, "kinetics")
            if augmented:
                result = augmented

        if result:
            result = self._post_process_kinetics(result)

        return result

    async def extract_morphology(self, nanozyme_name: str, text_chunks: List[str]) -> Dict[str, Any]:
        combined_text = self._prepare_text(text_chunks, max_chars=4000)
        messages = build_morphology_prompt(nanozyme_name, combined_text)
        result = await self._call_llm_structured(messages, "morphology")
        return result if result else {}

    async def extract_applications(self, nanozyme_name: str, text_chunks: List[str]) -> Dict[str, Any]:
        combined_text = self._prepare_text(text_chunks, max_chars=4000)
        messages = build_application_prompt(nanozyme_name, combined_text)
        result = await self._call_llm_structured(messages, "applications")
        return result if result else {}

    async def extract_enzyme_type(self, nanozyme_name: str, text_chunks: List[str]) -> Optional[str]:
        combined_text = self._prepare_text(text_chunks, max_chars=3000)
        messages = build_enzyme_type_prompt(nanozyme_name, combined_text)
        result = await self._call_llm_structured(messages, "enzyme_type")
        if result and isinstance(result, dict):
            return result.get("enzyme_like_type")
        return None

    async def extract_all(self, nanozyme_name: str, buckets: Dict[str, List[str]],
                           table_texts: List[str] = None) -> Dict[str, Any]:
        result = {}

        etype = await self.extract_enzyme_type(
            nanozyme_name,
            buckets.get("activity", []) + buckets.get("mechanism", []) + buckets.get("abstract", [])
        )
        result["enzyme_like_type"] = etype

        kinetics = await self.extract_kinetics(
            nanozyme_name,
            buckets.get("kinetics", []) + buckets.get("activity", []),
            table_texts
        )
        result.update(kinetics)

        morphology = await self.extract_morphology(
            nanozyme_name,
            buckets.get("material", []) + buckets.get("characterization", [])
        )
        result.update(morphology)

        applications = await self.extract_applications(
            nanozyme_name,
            buckets.get("application", []) + buckets.get("sensing", [])
        )
        result.update(applications)

        errors = validate_against_schema(result)
        if errors:
            logger.warning(f"[LLM-Ext] Schema validation errors: {errors}")
            result = self._auto_fix(result, errors)

        return result

    async def _call_llm_structured(self, messages: List[Dict[str, str]],
                                     task_name: str) -> Optional[Dict[str, Any]]:
        if not self.client:
            logger.warning(f"[LLM-Ext] No client available for {task_name}")
            return None

        try:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }

            if self.enable_constrained_output:
                kwargs["response_format"] = {"type": "json_object"}

            response = await self.client.chat_completion(**kwargs)
            content = response.get("content", "") if isinstance(response, dict) else str(response)

            parsed = self._parse_json_response(content)
            if parsed is None:
                logger.warning(f"[LLM-Ext] Failed to parse JSON for {task_name}")
                return None

            logger.info(f"[LLM-Ext] {task_name} extraction succeeded")
            return parsed

        except Exception as e:
            logger.error(f"[LLM-Ext] {task_name} extraction failed: {e}")
            return None

    async def _self_augment(self, previous_result: Dict[str, Any],
                             text: str, task_name: str) -> Optional[Dict[str, Any]]:
        messages = build_self_augmentation_prompt(
            json.dumps(previous_result, ensure_ascii=False, indent=2),
            text
        )
        augmented = await self._call_llm_structured(messages, f"{task_name}_augmented")
        if augmented:
            logger.info(f"[LLM-Ext] Self-augmentation improved {task_name}")
        return augmented

    def _post_process_kinetics(self, result: Dict[str, Any]) -> Dict[str, Any]:
        kin = result.get("kinetics", {})
        if isinstance(kin, dict):
            vmax_val = kin.get("Vmax")
            vmax_u = kin.get("Vmax_unit", "")
            if isinstance(vmax_val, (int, float)) and vmax_u in ("M/s", "M·s-1", "M s^-1"):
                if abs(vmax_val) < 1.0:
                    kin["Vmax"] = vmax_val * 1e6
                    kin["Vmax_unit"] = "μM/s"
                    logger.info(f"[LLM-Ext] Auto-converted Vmax {vmax_val} M/s -> {vmax_val*1e6} μM/s")
            elif isinstance(vmax_val, (int, float)) and vmax_u in ("mM/s", "mM·s-1"):
                if abs(vmax_val) < 1.0:
                    kin["Vmax"] = vmax_val * 1e3
                    kin["Vmax_unit"] = "μM/s"

            km_val = kin.get("Km")
            km_u = kin.get("Km_unit", "")
            if isinstance(km_val, (int, float)) and km_u == "M" and km_val > 1.0:
                kin["Km"] = None
                kin["Km_unit"] = None
                logger.warning(f"[LLM-Ext] Cleared unrealistic Km={km_val} M")

        for kl in result.get("kinetics_list", []):
            if not isinstance(kl, dict):
                continue
            kl_vmax = kl.get("Vmax")
            kl_vmax_u = kl.get("Vmax_unit", "")
            if isinstance(kl_vmax, (int, float)) and kl_vmax_u in ("M/s", "M·s-1", "M s^-1"):
                if abs(kl_vmax) < 1.0:
                    kl["Vmax"] = kl_vmax * 1e6
                    kl["Vmax_unit"] = "μM/s"
            kl_km = kl.get("Km")
            kl_km_u = kl.get("Km_unit", "")
            if isinstance(kl_km, (int, float)) and kl_km_u == "M" and kl_km > 1.0:
                kl["Km"] = None
                kl["Km_unit"] = None

        return result

    def _auto_fix(self, result: Dict[str, Any], errors: List[str]) -> Dict[str, Any]:
        for err in errors:
            if "unrealistically large" in err:
                kin = result.get("kinetics", {})
                if isinstance(kin, dict):
                    kin["Km"] = None
                    kin["Km_unit"] = None
            elif "converted" in err and "Vmax" in err:
                kin = result.get("kinetics", {})
                if isinstance(kin, dict):
                    vmax = kin.get("Vmax")
                    if isinstance(vmax, (int, float)):
                        kin["Vmax"] = vmax * 1e6
                        kin["Vmax_unit"] = "μM/s"
        return result

    def _prepare_text(self, chunks: List[str], max_chars: int = 6000) -> str:
        combined = "\n".join(chunks)
        if len(combined) > max_chars:
            combined = combined[:max_chars]
        return combined

    def _parse_json_response(self, content: str) -> Optional[Dict[str, Any]]:
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r'^```\w*\n?', '', content)
            content = re.sub(r'\n?```$', '', content)
            content = content.strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        return None
```

- [ ] **Step 2: 编写test_llm_structured_extractor.py**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from llm_structured_extractor import LLMStructuredExtractor


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.chat_completion = AsyncMock()
    return client


@pytest.fixture
def extractor(mock_client):
    return LLMStructuredExtractor(mock_client)


@pytest.mark.asyncio
async def test_extract_kinetics_multi_substrate(mock_client):
    mock_client.chat_completion.return_value = {
        "content": '{"kinetics": {"Km": 0.35, "Km_unit": "mM", "Vmax": 44.1, "Vmax_unit": "μM/s", "kcat": null, "kcat_unit": null, "substrate": "TMB"}, "kinetics_list": [{"Km": 0.35, "Km_unit": "mM", "Vmax": 44.1, "Vmax_unit": "μM/s", "kcat": null, "kcat_unit": null, "substrate": "TMB"}, {"Km": 0.89, "Km_unit": "mM", "Vmax": 0.079, "Vmax_unit": "μM/s", "kcat": null, "kcat_unit": null, "substrate": "H2O2"}]}'
    }
    ext = LLMStructuredExtractor(mock_client)
    result = await ext.extract_kinetics("Fe3O4@C", ["Km for TMB was 0.35 mM, Vmax was 4.41e-5 M/s"])
    assert result is not None
    assert result["kinetics"]["substrate"] == "TMB"
    assert len(result["kinetics_list"]) == 2


@pytest.mark.asyncio
async def test_vmax_auto_conversion(mock_client):
    mock_client.chat_completion.return_value = {
        "content": '{"kinetics": {"Km": 0.5, "Km_unit": "mM", "Vmax": 4.41e-05, "Vmax_unit": "M/s", "kcat": null, "kcat_unit": null, "substrate": "TMB"}, "kinetics_list": []}'
    }
    ext = LLMStructuredExtractor(mock_client)
    ext.enable_self_augmentation = False
    result = await ext.extract_kinetics("Fe3O4@C", ["Vmax was 4.41e-05 M/s"])
    assert result["kinetics"]["Vmax_unit"] == "μM/s"
    assert abs(result["kinetics"]["Vmax"] - 44.1) < 0.1


@pytest.mark.asyncio
async def test_km_unrealistic_clears(mock_client):
    mock_client.chat_completion.return_value = {
        "content": '{"kinetics": {"Km": 8.0, "Km_unit": "M", "Vmax": null, "Vmax_unit": null, "kcat": null, "kcat_unit": null, "substrate": null}, "kinetics_list": []}'
    }
    ext = LLMStructuredExtractor(mock_client)
    ext.enable_self_augmentation = False
    result = await ext.extract_kinetics("Fe3O4", ["Km was 8.0 M"])
    assert result["kinetics"]["Km"] is None


@pytest.mark.asyncio
async def test_extract_enzyme_type(mock_client):
    mock_client.chat_completion.return_value = {
        "content": '{"enzyme_like_type": "peroxidase-like"}'
    }
    ext = LLMStructuredExtractor(mock_client)
    result = await ext.extract_enzyme_type("Fe3O4", ["Fe3O4 exhibited peroxidase-like activity"])
    assert result == "peroxidase-like"


def test_parse_json_with_markdown():
    ext = LLMStructuredExtractor(None)
    result = ext._parse_json_response('```json\n{"key": "value"}\n```')
    assert result == {"key": "value"}


def test_parse_json_plain():
    ext = LLMStructuredExtractor(None)
    result = ext._parse_json_response('{"key": "value"}')
    assert result == {"key": "value"}


def test_parse_json_embedded():
    ext = LLMStructuredExtractor(None)
    result = ext._parse_json_response('Here is the result: {"key": "value"} end')
    assert result == {"key": "value"}
```

- [ ] **Step 3: 运行测试**

Run: `cd d:\ocrwiki版本\single_main_nanozyme && python -m pytest tests/test_llm_structured_extractor.py -v`
Expected: 6 passed

- [ ] **Step 4: Commit**

```bash
git add llm_structured_extractor.py tests/test_llm_structured_extractor.py
git commit -m "feat(extraction): 添加LLM结构化提取核心模块（self-augmentation + auto-fix）"
```

---

### Task 4: 集成LLM提取器到现有管道

**Files:**
- Modify: `d:\ocrwiki版本\single_main_nanozyme\single_main_nanozyme_extractor.py`
- Modify: `d:\ocrwiki版本\single_main_nanozyme\extraction_agents.py`

在`SingleMainNanozymePipeline.extract()`中，将LLM结构化提取放在规则提取之前，作为主要提取源。规则提取降级为fallback。

- [ ] **Step 1: 在SingleMainNanozymePipeline.__init__中初始化LLMStructuredExtractor**

在 `single_main_nanozyme_extractor.py` 的 `SingleMainNanozymePipeline.__init__` 方法中，在现有 `self.rule_ext = RuleExtractorAdapter()` 之后添加：

```python
from llm_structured_extractor import LLMStructuredExtractor
self.llm_structured = LLMStructuredExtractor(client, config) if (client and config and config.enable_llm) else None
```

- [ ] **Step 2: 在extract()方法中添加LLM-First提取路径**

在 `extract()` 方法中，找到 `self.rule_ext.extract_from_evidence(record, buckets, ...)` 调用（约第5859行），在其之前添加LLM结构化提取：

```python
if self.llm_structured:
    try:
        llm_structured_result = await self.llm_structured.extract_all(
            selected_name, buckets,
            table_texts=[t.get("raw_text", "") for t in tables if isinstance(t, dict)][:5]
        )
        if llm_structured_result:
            self._apply_llm_structured_result(record, llm_structured_result)
            logger.info(f"[SMN] LLM-structured extraction: enzyme_type={llm_structured_result.get('enzyme_like_type')}, "
                         f"Km={llm_structured_result.get('kinetics', {}).get('Km')}")
    except Exception as e:
        logger.warning(f"[SMN] LLM-structured extraction failed, falling back to rules: {e}")

self.rule_ext.extract_from_evidence(record, buckets, table_kinetics_values, selected_name, doc=doc)
```

- [ ] **Step 3: 添加_apply_llm_structured_result方法**

在 `SingleMainNanozymePipeline` 类中添加：

```python
def _apply_llm_structured_result(self, record: Dict[str, Any], llm_result: Dict[str, Any]) -> None:
    ma = record.get("main_activity", {})
    if not isinstance(ma, dict):
        return

    if llm_result.get("enzyme_like_type") and not ma.get("enzyme_like_type"):
        ma["enzyme_like_type"] = llm_result["enzyme_like_type"]

    llm_kin = llm_result.get("kinetics", {})
    if isinstance(llm_kin, dict):
        kin = ma.get("kinetics", {})
        if not isinstance(kin, dict):
            kin = {}
            ma["kinetics"] = kin
        for key in ("Km", "Km_unit", "Vmax", "Vmax_unit", "kcat", "kcat_unit", "substrate"):
            if llm_kin.get(key) is not None and kin.get(key) is None:
                kin[key] = llm_kin[key]

    llm_kin_list = llm_result.get("kinetics_list", [])
    if llm_kin_list and not ma.get("kinetics_list"):
        ma["kinetics_list"] = llm_kin_list

    sel = record.get("selected_nanozyme", {})
    if isinstance(sel, dict):
        for key in ("morphology", "size", "size_unit", "crystal_structure", "surface_area", "synthesis_method"):
            if llm_result.get(key) is not None and not sel.get(key):
                sel[key] = llm_result[key]
        if llm_result.get("characterization") and not sel.get("characterization"):
            sel["characterization"] = llm_result["characterization"]

    llm_apps = llm_result.get("applications", [])
    if llm_apps and not record.get("applications"):
        record["applications"] = llm_apps
```

- [ ] **Step 4: 语法检查**

Run: `cd d:\ocrwiki版本\single_main_nanozyme && python -m py_compile single_main_nanozyme_extractor.py && python -m py_compile llm_structured_extractor.py`
Expected: 无错误

- [ ] **Step 5: Commit**

```bash
git add single_main_nanozyme_extractor.py
git commit -m "feat(extraction): 集成LLM-First提取到管道，规则提取降级为fallback"
```

---

### Task 5: 增强化学知识验证层

**Files:**
- Modify: `d:\ocrwiki版本\single_main_nanozyme\numeric_validator.py`

借鉴Paper B的"化学知识验证"思想，将当前NumericValidator从简单的量级检查升级为领域知识驱动的验证。

- [ ] **Step 1: 在numeric_validator.py中添加纳米酶领域验证规则**

在 `NumericValidator` 类中添加方法：

```python
_NANOZYME_KM_RANGES = {
    "peroxidase-like": (0.001, 500, "mM"),
    "oxidase-like": (0.01, 200, "mM"),
    "catalase-like": (0.1, 1000, "mM"),
    "superoxide-dismutase-like": (0.01, 100, "mM"),
    "glucose-oxidase-like": (0.1, 500, "mM"),
}

_NANOZYME_VMAX_RANGES = {
    "peroxidase-like": (1e-4, 1e6, "μM/s"),
    "oxidase-like": (1e-3, 1e5, "μM/s"),
    "catalase-like": (1e-2, 1e6, "μM/s"),
}

_ANALYTE_ENZYME_COMPATIBILITY = {
    "peroxidase-like": {"H2O2", "TMB", "ABTS", "OPD", "DAB"},
    "oxidase-like": {"glucose", "ascorbic acid", "uric acid", "cholesterol"},
    "catalase-like": {"H2O2"},
    "glucose-oxidase-like": {"glucose", "O2"},
}

def validate_nanozyme_kinetics(self, record: Dict[str, Any]) -> List[str]:
    warnings = []
    ma = record.get("main_activity", {})
    etype = ma.get("enzyme_like_type", "")
    kin = ma.get("kinetics", {})

    if not isinstance(kin, dict) or not etype:
        return warnings

    km_range = self._NANOZYME_KM_RANGES.get(etype)
    if km_range:
        km_val = kin.get("Km")
        km_u = kin.get("Km_unit", "")
        if isinstance(km_val, (int, float)):
            km_mM = self._to_mM(km_val, km_u)
            if km_mM is not None:
                lo, hi, _ = km_range
                if km_mM < lo or km_mM > hi:
                    warnings.append(f"Km={km_val} {km_u} ({km_mM:.4f} mM) outside typical range for {etype} ({lo}-{hi} mM)")

    vmax_range = self._NANOZYME_VMAX_RANGES.get(etype)
    if vmax_range:
        vmax_val = kin.get("Vmax")
        vmax_u = kin.get("Vmax_unit", "")
        if isinstance(vmax_val, (int, float)):
            vmax_uM = self._to_uM_per_s(vmax_val, vmax_u)
            if vmax_uM is not None:
                lo, hi, _ = vmax_range
                if vmax_uM < lo or vmax_uM > hi:
                    warnings.append(f"Vmax={vmax_val} {vmax_u} ({vmax_uM:.4f} μM/s) outside typical range for {etype}")

    for app in record.get("applications", []):
        analyte = app.get("target_analyte", "")
        if analyte and etype in self._ANALYTE_ENZYME_COMPATIBILITY:
            compat = self._ANALYTE_ENZYME_COMPATIBILITY[etype]
            if analyte.lower() not in {a.lower() for a in compat}:
                warnings.append(f"Analyte '{analyte}' may be incompatible with {etype}")

    return warnings

def _to_mM(self, val: float, unit: str) -> Optional[float]:
    conversions = {"M": 1e3, "mM": 1.0, "μM": 1e-3, "uM": 1e-3, "nM": 1e-6}
    factor = conversions.get(unit)
    return val * factor if factor else None

def _to_uM_per_s(self, val: float, unit: str) -> Optional[float]:
    conversions = {"M/s": 1e6, "mM/s": 1e3, "μM/s": 1.0, "uM/s": 1.0, "nM/s": 1e-3}
    factor = conversions.get(unit)
    return val * factor if factor else None
```

- [ ] **Step 2: 语法检查**

Run: `cd d:\ocrwiki版本\single_main_nanozyme && python -m py_compile numeric_validator.py`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add numeric_validator.py
git commit -m "feat(validation): 增强纳米酶领域知识验证（酶类型-量级范围-分析物兼容性）"
```

---

### Task 6: 端到端验证

**Files:**
- Modify: `d:\ocrwiki版本\single_main_nanozyme\test\validate_fixes.py` (复用验证脚本)

- [ ] **Step 1: 修改验证脚本支持LLM-First模式**

在 `validate_fixes.py` 中，确保 `ExtractionPipeline` 初始化时传入 `enable_cache=False`，并确认LLM配置已启用。

- [ ] **Step 2: 运行7篇验证集PDF提取**

Run: `cd d:\ocrwiki版本\single_main_nanozyme && python test\validate_fixes.py`
Expected: 所有7篇PDF提取成功，无报错

- [ ] **Step 3: 对比提取结果与金标准**

检查输出JSON中的关键字段（Km, Vmax, enzyme_type, morphology, applications），与Excel金标准对比

- [ ] **Step 4: 记录迭代日志**

创建 `docs/iteration_logs/2026-05-08_llm-first-extraction.md`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(extraction): LLM-First提取架构替代规则提取，端到端验证通过"
```

---

## Self-Review

### 1. Spec Coverage
- ✅ LLM结构化提取替代规则提取 → Task 3 + Task 4
- ✅ Constrained decoding → Task 1 (schema) + Task 3 (response_format)
- ✅ Few-shot prompting → Task 2 (prompt模板)
- ✅ Self-augmentation → Task 3 (_self_augment方法)
- ✅ 化学知识验证 → Task 5 (领域验证规则)
- ✅ 多底物动力学 → Task 2 (kinetics_list prompt设计)
- ✅ 酶类型识别 → Task 2 (enzyme_type prompt)
- ✅ Schema不修改 → 确认，所有改动在提取层

### 2. Placeholder Scan
- 无TBD/TODO/placeholder
- 所有代码步骤包含完整实现

### 3. Type Consistency
- `LLMStructuredExtractor.extract_all()` 返回 `Dict[str, Any]`
- `_apply_llm_structured_result()` 接收 `Dict[str, Any]`，与record格式一致
- schema_constraints.py中的enum值与nanozyme_models.py中的EnzymeType一致
