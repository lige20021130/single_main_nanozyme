# 领域知识集中化 + Rule→Validator 升级 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将纳米酶领域知识从代码硬编码集中到 YAML 知识库，让 LLM 成为唯一提取通道，Rule 层降级为验证器+兜底器，消除关键词匹配的限制性提取。

**Architecture:** 创建 `domain_knowledge.yaml` 作为领域知识单一真相源，`domain_knowledge.py` 作为加载器提供统一接口。`nanozyme_models.py`、`schema_constraints.py`、`extraction_prompts.py` 从加载器读取数据，不再各自硬编码。`RuleExtractor` 和 `extraction_agents.py` 的正则提取逻辑降级为仅兜底+验证，LLM 提取结果优先。

**Tech Stack:** Python 3.10+, PyYAML, 现有 LLM API 基础设施

---

## 当前问题诊断

### 硬编码散布现状（3处重复维护）

| 领域知识 | nanozyme_models.py | schema_constraints.py | extraction_prompts.py | single_main_nanozyme_extractor.py |
|----------|:---:|:---:|:---:|:---:|
| 酶类型枚举 | `EnzymeType` 枚举 + `_ENZYME_ALIAS_MAP` | `_ENZYME_TYPE_ENUM` 列表 | SYSTEM_PROMPT 硬编码 | `_ENZYME_TYPE_PATTERNS` 正则 |
| 应用类型枚举 | `ApplicationType` 枚举 + `_APPLICATION_TYPE_ALIAS_MAP` | `_APPLICATION_TYPE_ENUM` 列表 | SYSTEM_PROMPT 硬编码 | 无 |
| 底物关键词 | `ENZYME_REGISTRY` substrates | 无 | SYSTEM_PROMPT 硬编码 | `_SUBSTRATE_KEYWORDS` 集合 |
| 探针分子 | 无 | 无 | SYSTEM_PROMPT 硬编码 | `PROBE_MOLECULES` 集合 |
| 数值范围 | 无 | 无 | SYSTEM_PROMPT 硬编码 | `_KM_RANGES` 等 |

**核心问题**：新增一种酶类型（如 `ferroxidase-like`）需要同时修改 4 个文件，且容易遗漏导致不一致。

### Rule 层过度提取

`RuleExtractor.extract_from_evidence()` 使用 800+ 行正则来提取：
- 酶类型（70+ 条正则）→ 应由 LLM 语义理解
- 底物（40+ 关键词匹配）→ 应由 LLM 语义理解
- Km/Vmax/LOD 值（100+ 条正则）→ LLM+Schema 约束更准确
- 应用信息（关键词匹配）→ LLM 语义理解更全面

---

## 文件结构

| 文件 | 职责 | 状态 |
|------|------|------|
| `domain_knowledge.yaml` | 领域知识单一真相源 | 新建 |
| `domain_knowledge.py` | 加载器，提供统一访问接口 | 新建 |
| `nanozyme_models.py` | 枚举+归一化，从加载器读取 | 修改 |
| `schema_constraints.py` | Schema约束，从加载器读取 | 修改 |
| `extraction_prompts.py` | Prompt生成，从加载器读取 | 修改 |
| `single_main_nanozyme_extractor.py` | Rule层降级为验证器+兜底器 | 修改 |
| `extraction_agents.py` | Agent正则降级为验证器 | 修改 |
| `material_identifier.py` | 移除PROBE_MOLECULES硬编码 | 修改 |
| `tests/test_domain_knowledge.py` | 领域知识加载器测试 | 新建 |

---

## Task 1: 创建 domain_knowledge.yaml

**Files:**
- Create: `domain_knowledge.yaml`

- [ ] **Step 1: 创建领域知识 YAML 文件**

```yaml
# domain_knowledge.yaml - 纳米酶领域知识单一真相源
# 所有酶类型、应用类型、底物、探针分子、数值范围等均在此维护
# 代码中不再硬编码这些信息

enzyme_types:
  - value: "peroxidase-like"
    aliases: ["POD-like", "peroxidase-mimicking", "peroxidase-mimic", "peroxidase (POD)-like"]
    substrates: ["TMB", "ABTS", "OPD", "guaiacol", "pyrogallol", "o-phenylenediamine"]
    assay_keywords: ["TMB assay", "ABTS assay", "colorimetric assay"]

  - value: "oxidase-like"
    aliases: ["OXD-like", "OX-like", "oxidase-mimicking", "oxidase-mimic", "oxidase (OXD)-like"]
    substrates: ["TMB", "ABTS", "OPD", "DHF", "catechol"]
    assay_keywords: ["oxidase assay", "TMB oxidation"]

  - value: "catalase-like"
    aliases: ["CAT-like", "catalase-mimicking", "catalase-mimic", "catalase (CAT)-like"]
    substrates: ["H2O2"]
    assay_keywords: ["H2O2 decomposition", "catalase assay", "O2 evolution"]

  - value: "superoxide-dismutase-like"
    aliases: ["SOD-like", "SOD-mimicking", "SOD-mimic", "superoxide dismutase (SOD)-like"]
    substrates: ["superoxide", "O2-"]
    assay_keywords: ["SOD assay", "NBT", "pyrogallol autoxidation"]

  - value: "glutathione-peroxidase-like"
    aliases: ["GPx-like", "GPx-mimicking", "GPx-mimic", "glutathione peroxidase (GPx)-like"]
    substrates: ["H2O2", "GSH"]
    assay_keywords: ["GPx assay", "NADPH consumption"]

  - value: "esterase-like"
    aliases: ["esterase-mimicking", "esterase-mimic"]
    substrates: ["p-NPA", "p-nitrophenyl acetate"]
    assay_keywords: ["esterase assay", "p-NPA hydrolysis"]

  - value: "nitroreductase-like"
    aliases: ["NTR-like", "NTR-mimicking", "NTR-mimic", "nitroreductase (NTR)-like"]
    substrates: ["nitrofurazone", "nitroaromatics", "4-nitrophenol"]
    assay_keywords: ["nitroreductase assay", "nitro reduction"]

  - value: "hydrolase-like"
    aliases: ["hydrolase-mimicking", "hydrolase-mimic"]
    substrates: ["p-NPA", "esters", "peptides"]
    assay_keywords: ["hydrolase assay", "hydrolysis"]

  - value: "phosphatase-like"
    aliases: ["ALP-like", "ACP-like", "phosphatase-mimicking", "phosphatase-mimic", "phosphatase (ALP)-like"]
    substrates: ["p-NPP", "BCIP", "pnpp"]
    assay_keywords: ["phosphatase assay", "p-NPP hydrolysis"]

  - value: "laccase-like"
    aliases: ["laccase-mimicking", "laccase-mimic"]
    substrates: ["ABTS", "syringaldazine", "guaiacol", "2,6-DMP"]
    assay_keywords: ["laccase assay", "ABTS oxidation"]

  - value: "haloperoxidase-like"
    aliases: ["VHPO-like", "haloperoxidase-mimicking", "haloperoxidase-mimic", "chloroperoxidase-like", "bromoperoxidase-like", "iodoperoxidase-like", "chloride peroxidase-like"]
    substrates: ["Br-", "I-", "Cl-"]
    assay_keywords: ["haloperoxidase assay", "halogenation"]

  - value: "glucose-oxidase-like"
    aliases: ["GOx-like", "GOx-mimicking", "GOx-mimic", "glucose oxidase (GOx)-like"]
    substrates: ["glucose", "O2"]
    assay_keywords: ["glucose oxidase assay", "glucose detection"]

  - value: "glutathione-oxidase-like"
    aliases: ["GSHOx-like", "glutathione oxidase-mimicking"]
    substrates: ["GSH", "O2"]
    assay_keywords: ["glutathione oxidase assay", "GSH oxidation"]

  - value: "nuclease-like"
    aliases: ["DNase-like", "RNase-like", "nuclease-mimicking", "nuclease-mimic", "DNAse-like"]
    substrates: ["DNA", "RNA", "oligonucleotides", "plasmid DNA"]
    assay_keywords: ["nuclease assay", "DNA cleavage assay", "gel electrophoresis"]

  - value: "tyrosinase-like"
    aliases: ["tyrosinase-mimicking", "tyrosinase-mimic", "polyphenol oxidase-like"]
    substrates: ["L-DOPA", "tyrosine", "phenol", "catechol"]
    assay_keywords: ["tyrosinase assay", "L-DOPA oxidation"]

  - value: "cascade-enzymatic"
    aliases: ["cascade enzymatic", "enzyme cascade"]
    substrates: []
    assay_keywords: ["cascade assay", "sequential reaction"]

  - value: "multi-enzyme-like"
    aliases: ["dual-enzyme-like", "triple-enzyme-like", "multi-enzyme-mimicking"]
    substrates: ["TMB", "H2O2", "ABTS", "OPD"]
    assay_keywords: ["multi-enzyme assay", "dual-enzyme activity"]

  - value: "ribozyme-like"
    aliases: ["ribozyme-mimicking", "ribozyme-mimic"]
    substrates: ["RNA", "DNA", "oligonucleotides"]
    assay_keywords: ["ribozyme assay", "RNA cleavage"]

  - value: "cellulase-like"
    aliases: ["cellulase-mimicking", "cellulase-mimic"]
    substrates: ["CMC", "carboxymethyl cellulose", "cellulose", "filter paper"]
    assay_keywords: ["cellulase assay", "CMC hydrolysis", "DNS assay"]

  - value: "amylase-like"
    aliases: ["amylase-mimicking", "amylase-mimic", "α-amylase-like"]
    substrates: ["starch", "amylose", "amylopectin", "soluble starch"]
    assay_keywords: ["amylase assay", "starch hydrolysis", "DNS method"]

  - value: "protease-like"
    aliases: ["protease-mimicking", "protease-mimic"]
    substrates: ["casein", "BSA", "gelatin", "peptide"]
    assay_keywords: ["protease assay", "casein hydrolysis"]

  - value: "lipase-like"
    aliases: ["lipase-mimicking", "lipase-mimic"]
    substrates: ["p-NPB", "p-nitrophenyl butyrate", "triolein", "olive oil"]
    assay_keywords: ["lipase assay", "p-NPB hydrolysis", "ester hydrolysis"]

  - value: "urease-like"
    aliases: ["urease-mimicking", "urease-mimic"]
    substrates: ["urea"]
    assay_keywords: ["urease assay", "urea hydrolysis", "phenol red method"]

  - value: "ascorbate-oxidase-like"
    aliases: ["AAO-like", "ascorbate oxidase-mimicking"]
    substrates: ["ascorbic acid", "AA", "vitamin C"]
    assay_keywords: ["ascorbate oxidase assay", "AA oxidation"]

  - value: "dehydrogenase-like"
    aliases: ["dehydrogenase-mimicking", "formate dehydrogenase-like", "alcohol dehydrogenase-like", "glucose dehydrogenase-like"]
    substrates: ["NADH", "NAD+", "formate", "ethanol", "glucose"]
    assay_keywords: ["dehydrogenase assay", "NADH oxidation"]

  - value: "invertase-like"
    aliases: ["invertase-mimicking", "sucrase-like"]
    substrates: ["sucrose", "saccharose"]
    assay_keywords: ["invertase assay", "sucrose hydrolysis", "DNS method"]

  - value: "chitinase-like"
    aliases: ["chitinase-mimicking", "chitinase-mimic"]
    substrates: ["chitin", "colloidal chitin", "CM-chitin"]
    assay_keywords: ["chitinase assay", "chitin hydrolysis"]

  - value: "xylanase-like"
    aliases: ["xylanase-mimicking", "xylanase-mimic"]
    substrates: ["xylan", "beechwood xylan", "birchwood xylan"]
    assay_keywords: ["xylanase assay", "xylan hydrolysis", "DNS method"]

  - value: "ferroxidase-like"
    aliases: ["ferroxidase-mimicking"]
    substrates: ["Fe2+", "iron"]
    assay_keywords: ["ferroxidase assay", "iron oxidation"]

  - value: "glutathione-reductase-like"
    aliases: ["GR-like", "glutathione reductase-mimicking"]
    substrates: ["GSSG", "NADPH"]
    assay_keywords: ["glutathione reductase assay", "NADPH consumption"]

  - value: "superoxide-oxidase-like"
    aliases: ["SOO-like", "superoxide oxidase-mimicking"]
    substrates: ["superoxide", "O2-"]
    assay_keywords: ["superoxide oxidase assay"]

  - value: "peroxynitritase-like"
    aliases: ["peroxynitritase-mimicking"]
    substrates: ["ONOO-"]
    assay_keywords: ["peroxynitritase assay"]

  - value: "NADH-peroxidase-like"
    aliases: ["NADH peroxidase-mimicking"]
    substrates: ["NADH", "H2O2"]
    assay_keywords: ["NADH peroxidase assay"]

  - value: "thioredoxin-reductase-like"
    aliases: ["TrxR-like", "thioredoxin reductase-mimicking"]
    substrates: ["thioredoxin", "NADPH"]
    assay_keywords: ["thioredoxin reductase assay"]

  - value: "glutathione-transferase-like"
    aliases: ["GST-like", "glutathione S-transferase-like", "glutathione transferase-mimicking"]
    substrates: ["GSH", "CDNB"]
    assay_keywords: ["GST assay", "CDNB conjugation"]

  - value: "monooxygenase-like"
    aliases: ["monooxygenase-mimicking"]
    substrates: []
    assay_keywords: ["monooxygenase assay"]

  - value: "dioxygenase-like"
    aliases: ["dioxygenase-mimicking"]
    substrates: []
    assay_keywords: ["dioxygenase assay"]

  - value: "sulfite-oxidase-like"
    aliases: ["sulfite oxidase-mimicking"]
    substrates: ["sulfite", "SO3 2-"]
    assay_keywords: ["sulfite oxidase assay"]

application_types:
  - value: "sensing"
    aliases: ["detection", "colorimetric detection", "colorimetric sensing", "biosensing", "biosensor", "determination", "monitoring", "assay", "diagnostic", "diagnosis", "sensor"]

  - value: "therapeutic"
    aliases: ["therapy", "antitumor", "tumor therapy", "wound healing", "phototherapy", "photothermal therapy", "chemodynamic therapy", "sonodynamic therapy", "photodynamic therapy", "starvation therapy", "gas therapy"]

  - value: "antibacterial"
    aliases: ["anti-infection", "antibacterial activity", "sterilization", "bacteriostatic", "biocidal"]

  - value: "environmental"
    aliases: ["degradation", "water treatment", "pollutant removal", "organic pollutant degradation", "waste water", "heavy metal detection"]

  - value: "antioxidant"
    aliases: ["anti-inflammation", "ROS scavenging", "free radical scavenging", "oxidative stress protection", "radioprotection"]

  - value: "biofilm_inhibition"
    aliases: ["anti-biofilm"]

  - value: "cytoprotection"
    aliases: ["cytoprotection", "cell protection", "neuroprotection", "cardioprotection"]

  - value: "bioimaging"
    aliases: ["imaging", "cell imaging", "fluorescence imaging", "MR imaging", "photoacoustic imaging"]

  - value: "other"
    aliases: []

probe_molecules:
  description: "Signal indicator molecules used in assays, NOT target analytes. These generate the measurable signal but are not the substance being detected."
  examples:
    - name: "crystal violet"
      aliases: ["CV+", "CV"]
    - name: "methylene blue"
      aliases: ["MB"]
    - name: "rhodamine B"
      aliases: ["RhB"]
    - name: "rhodamine 6G"
      aliases: ["R6G"]
    - name: "4-nitrophenol"
      aliases: ["4-NP"]
    - name: "congo red"
      aliases: []
    - name: "methyl orange"
      aliases: []
    - name: "methyl red"
      aliases: []
    - name: "eosin Y"
      aliases: []
    - name: "fluorescein"
      aliases: []
    - name: "janus green B"
      aliases: []
    - name: "nile blue"
      aliases: []
    - name: "nile red"
      aliases: []
    - name: "acridine orange"
      aliases: []
    - name: "proflavine"
      aliases: []
    - name: "safranin"
      aliases: []
    - name: "neutral red"
      aliases: []

numeric_ranges:
  Km:
    typical_min: 0.001
    typical_max: 500
    unit: "mM"
    warning_if_above: 1000
    description: "Michaelis constant, typically 0.001-500 mM for nanozymes"
  Vmax:
    typical_min: 0.001
    typical_max: 10000
    unit: "μM/s"
    description: "Maximum velocity"
  kcat:
    typical_min: 0.001
    typical_max: 10000
    unit: "s⁻¹"
    description: "Turnover number"
  LOD:
    typical_min: 0.0001
    typical_max: 1000
    unit: "μM"
    description: "Limit of detection"

unit_conversion:
  M_to_mM: 1000
  M_to_uM: 1000000
  mM_to_uM: 1000
  M_per_s_to_uM_per_s: 1000000
  M_per_s_to_mM_per_s: 1000
  per_min_to_per_s: 0.01667

common_substrate_enzyme_mapping:
  TMB: ["peroxidase-like", "oxidase-like"]
  ABTS: ["peroxidase-like", "oxidase-like", "laccase-like"]
  OPD: ["peroxidase-like", "oxidase-like"]
  H2O2: ["peroxidase-like", "catalase-like", "glutathione-peroxidase-like"]
  glucose: ["glucose-oxidase-like"]
  GSH: ["glutathione-peroxidase-like", "glutathione-oxidase-like", "glutathione-transferase-like"]
  NADH: ["dehydrogenase-like", "NADH-peroxidase-like"]
  ascorbic_acid: ["ascorbate-oxidase-like"]
  urea: ["urease-like"]
  L_DOPA: ["tyrosinase-like"]
```

- [ ] **Step 2: 验证 YAML 语法正确**

Run: `python -c "import yaml; data=yaml.safe_load(open('domain_knowledge.yaml','r',encoding='utf-8')); print(f'enzyme_types: {len(data[\"enzyme_types\"])}'); print(f'application_types: {len(data[\"application_types\"])}'); print(f'probe_molecules: {len(data[\"probe_molecules\"][\"examples\"])}')"`

Expected: 输出各类别数量，无报错

---

## Task 2: 创建 domain_knowledge.py 加载器

**Files:**
- Create: `domain_knowledge.py`
- Test: `tests/test_domain_knowledge.py`

- [ ] **Step 1: 写加载器测试**

```python
# tests/test_domain_knowledge.py
import pytest


def test_load_domain_knowledge():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    assert dk.enzyme_types is not None
    assert len(dk.enzyme_types) > 20


def test_get_enzyme_type_values():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    values = dk.get_enzyme_type_values()
    assert "peroxidase-like" in values
    assert "oxidase-like" in values
    assert isinstance(values, list)


def test_get_enzyme_alias_map():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    alias_map = dk.get_enzyme_alias_map()
    assert alias_map["POD-like"] == "peroxidase-like"
    assert alias_map["peroxidase-mimicking"] == "peroxidase-like"
    assert alias_map["CAT-like"] == "catalase-like"


def test_get_application_alias_map():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    alias_map = dk.get_application_alias_map()
    assert alias_map["detection"] == "sensing"
    assert alias_map["biosensor"] == "sensing"


def test_get_application_type_values():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    values = dk.get_application_type_values()
    assert "sensing" in values
    assert "therapeutic" in values


def test_get_probe_molecule_names():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    names = dk.get_probe_molecule_names()
    assert "crystal violet" in names
    assert "methylene blue" in names


def test_get_substrate_enzyme_mapping():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    mapping = dk.get_substrate_enzyme_mapping()
    assert "TMB" in mapping
    assert "peroxidase-like" in mapping["TMB"]


def test_get_numeric_ranges():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    km_range = dk.get_numeric_range("Km")
    assert km_range["typical_min"] == 0.001
    assert km_range["typical_max"] == 500


def test_generate_enzyme_type_prompt_snippet():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    snippet = dk.generate_enzyme_type_prompt_snippet()
    assert "peroxidase-like" in snippet
    assert "oxidase-like" in snippet


def test_generate_substrate_prompt_snippet():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    snippet = dk.generate_substrate_prompt_snippet()
    assert "TMB" in snippet


def test_singleton_pattern():
    from domain_knowledge import get_domain_knowledge
    dk1 = get_domain_knowledge()
    dk2 = get_domain_knowledge()
    assert dk1 is dk2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_domain_knowledge.py -v`
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: 实现 DomainKnowledge 加载器**

```python
# domain_knowledge.py
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

import yaml

logger = logging.getLogger(__name__)

_YAML_PATH = Path(__file__).parent / "domain_knowledge.yaml"

_instance = None


class DomainKnowledge:
    def __init__(self, yaml_path: Optional[Path] = None):
        path = yaml_path or _YAML_PATH
        if not path.exists():
            raise FileNotFoundError(f"Domain knowledge YAML not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f)
        self._enzyme_alias_map: Optional[Dict[str, str]] = None
        self._application_alias_map: Optional[Dict[str, str]] = None
        logger.info(f"[DomainKnowledge] Loaded from {path}: "
                     f"{len(self._data.get('enzyme_types', []))} enzyme types, "
                     f"{len(self._data.get('application_types', []))} application types")

    @property
    def enzyme_types(self) -> List[Dict[str, Any]]:
        return self._data.get("enzyme_types", [])

    @property
    def application_types(self) -> List[Dict[str, Any]]:
        return self._data.get("application_types", [])

    @property
    def probe_molecules(self) -> Dict[str, Any]:
        return self._data.get("probe_molecules", {})

    @property
    def numeric_ranges(self) -> Dict[str, Any]:
        return self._data.get("numeric_ranges", {})

    @property
    def unit_conversion(self) -> Dict[str, Any]:
        return self._data.get("unit_conversion", {})

    def get_enzyme_type_values(self) -> List[str]:
        return [et["value"] for et in self.enzyme_types]

    def get_enzyme_alias_map(self) -> Dict[str, str]:
        if self._enzyme_alias_map is not None:
            return self._enzyme_alias_map
        alias_map: Dict[str, str] = {}
        for et in self.enzyme_types:
            canonical = et["value"]
            alias_map[canonical] = canonical
            for alias in et.get("aliases", []):
                alias_map[alias.lower()] = canonical
        self._enzyme_alias_map = alias_map
        return alias_map

    def get_application_type_values(self) -> List[str]:
        return [at["value"] for at in self.application_types]

    def get_application_alias_map(self) -> Dict[str, str]:
        if self._application_alias_map is not None:
            return self._application_alias_map
        alias_map: Dict[str, str] = {}
        for at in self.application_types:
            canonical = at["value"]
            alias_map[canonical] = canonical
            for alias in at.get("aliases", []):
                alias_map[alias.lower()] = canonical
        self._application_alias_map = alias_map
        return alias_map

    def get_probe_molecule_names(self) -> set:
        names = set()
        for pm in self.probe_molecules.get("examples", []):
            names.add(pm["name"].lower())
            for alias in pm.get("aliases", []):
                names.add(alias.lower())
        return names

    def get_substrate_enzyme_mapping(self) -> Dict[str, List[str]]:
        return self._data.get("common_substrate_enzyme_mapping", {})

    def get_numeric_range(self, param: str) -> Dict[str, Any]:
        return self.numeric_ranges.get(param, {})

    def get_all_substrates(self) -> List[str]:
        seen = set()
        result = []
        for et in self.enzyme_types:
            for sub in et.get("substrates", []):
                if sub not in seen:
                    seen.add(sub)
                    result.append(sub)
        return result

    def get_enzyme_registry(self) -> Dict[str, Dict[str, Any]]:
        registry = {}
        for et in self.enzyme_types:
            registry[et["value"]] = {
                "keywords": et.get("aliases", []) + [et["value"]],
                "substrates": et.get("substrates", []),
                "assay_keywords": et.get("assay_keywords", []),
            }
        return registry

    def generate_enzyme_type_prompt_snippet(self) -> str:
        values = self.get_enzyme_type_values()
        return " | ".join(f'"{v}"' for v in values)

    def generate_application_type_prompt_snippet(self) -> str:
        values = self.get_application_type_values()
        return " | ".join(f'"{v}"' for v in values)

    def generate_substrate_prompt_snippet(self) -> str:
        substrates = self.get_all_substrates()
        return ", ".join(substrates)

    def generate_probe_molecule_prompt_snippet(self) -> str:
        names = [pm["name"] for pm in self.probe_molecules.get("examples", [])]
        return ", ".join(names)


def get_domain_knowledge() -> DomainKnowledge:
    global _instance
    if _instance is None:
        _instance = DomainKnowledge()
    return _instance
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_domain_knowledge.py -v`
Expected: 全部 PASS

---

## Task 3: 重构 nanozyme_models.py 使用加载器

**Files:**
- Modify: `nanozyme_models.py`

**原则**: 保持 `EnzymeType` 枚举和 `ApplicationType` 枚举的公共 API 不变，内部数据从 `domain_knowledge.py` 加载。`_ENZYME_ALIAS_MAP` 和 `_APPLICATION_TYPE_ALIAS_MAP` 从加载器生成。`ENZYME_REGISTRY` 从加载器生成。

- [ ] **Step 1: 修改 nanozyme_models.py 顶部导入和枚举生成**

在文件顶部添加：
```python
from domain_knowledge import get_domain_knowledge
_dk = get_domain_knowledge()
```

将 `EnzymeType` 枚举改为从 `_dk.get_enzyme_type_values()` 动态生成：
```python
EnzymeType = Enum(
    "EnzymeType",
    {v.upper().replace("-", "_").replace(" ", "_"): v for v in _dk.get_enzyme_type_values()},
)
```

将 `_ENZYME_ALIAS_MAP` 改为：
```python
_ENZYME_ALIAS_MAP = _dk.get_enzyme_alias_map()
```

将 `_APPLICATION_TYPE_ALIAS_MAP` 改为：
```python
_APPLICATION_TYPE_ALIAS_MAP = _dk.get_application_alias_map()
```

将 `ApplicationType` 枚举改为从 `_dk.get_application_type_values()` 动态生成。

将 `ENZYME_REGISTRY` 改为从 `_dk.get_enzyme_registry()` 生成。

- [ ] **Step 2: 运行现有酶类型归一化测试**

Run: `python -m pytest tests/test_enzyme_type_normalization.py -v`
Expected: 全部 PASS（公共 API 未变）

- [ ] **Step 3: 验证枚举值完整性**

Run: `python -c "from nanozyme_models import EnzymeType, ApplicationType; print(f'EnzymeType: {len(EnzymeType)} members'); print(f'ApplicationType: {len(ApplicationType)} members'); print([e.value for e in EnzymeType][:5])"`
Expected: 输出枚举数量和前5个值

---

## Task 4: 重构 schema_constraints.py 使用加载器

**Files:**
- Modify: `schema_constraints.py`

- [ ] **Step 1: 替换硬编码枚举列表**

将 `_ENZYME_TYPE_ENUM` 改为从加载器读取：
```python
from domain_knowledge import get_domain_knowledge
_dk = get_domain_knowledge()
_ENZYME_TYPE_ENUM = _dk.get_enzyme_type_values()
_APPLICATION_TYPE_ENUM = _dk.get_application_type_values()
```

- [ ] **Step 2: 验证 Schema 约束正确**

Run: `python -c "from schema_constraints import _ENZYME_TYPE_ENUM, _APPLICATION_TYPE_ENUM; print(f'enzyme types: {len(_ENZYME_TYPE_ENUM)}'); print(f'app types: {len(_APPLICATION_TYPE_ENUM)}'); assert 'peroxidase-like' in _ENZYME_TYPE_ENUM; assert 'sensing' in _APPLICATION_TYPE_ENUM; print('OK')"`
Expected: 输出数量，OK

---

## Task 5: 重构 extraction_prompts.py 使用加载器

**Files:**
- Modify: `extraction_prompts.py`

- [ ] **Step 1: 替换 SYSTEM_PROMPT 中的硬编码枚举**

将 `SYSTEM_PROMPT` 中的 `{enzyme_types}` 和 `{app_types}` 占位符改为从加载器生成：

```python
from domain_knowledge import get_domain_knowledge
_dk = get_domain_knowledge()

SYSTEM_PROMPT = """...{enzyme_types}...{app_types}...""".format(
    enzyme_types=_dk.generate_enzyme_type_prompt_snippet(),
    app_types=_dk.generate_application_type_prompt_snippet(),
)
```

同时将硬编码的底物列表、探针分子列表替换为加载器生成的内容。

- [ ] **Step 2: 验证 Prompt 生成正确**

Run: `python -c "from extraction_prompts import SYSTEM_PROMPT; assert 'peroxidase-like' in SYSTEM_PROMPT; assert 'sensing' in SYSTEM_PROMPT; print('Prompt OK, length:', len(SYSTEM_PROMPT))"`
Expected: Prompt 包含所有枚举值

---

## Task 6: RuleExtractor 从提取器转为验证器+兜底器

**Files:**
- Modify: `single_main_nanozyme_extractor.py`

**核心变更**: `RuleExtractor.extract_from_evidence()` 的行为从"主动提取"改为"仅兜底+验证"。

- [ ] **Step 1: 修改 RuleExtractor.extract_from_evidence 逻辑**

当前逻辑：遍历正则，找到就填入。
新逻辑：
1. 如果 LLM 已经填入了 `enzyme_like_type`，用正则**验证**是否匹配（不一致时标记 needs_review）
2. 如果 LLM 没有填入，才用正则**兜底**提取
3. `_SUBSTRATE_KEYWORDS` 匹配完全移除，底物提取由 LLM 负责
4. `_ENZYME_TYPE_PATTERNS` 保留但仅用于验证和兜底

具体修改 `RuleExtractor.extract_from_evidence`：

```python
def extract_from_evidence(self, record, buckets, table_values, selected_name, doc=None):
    # --- 验证 LLM 结果 ---
    ma = record["main_activity"]
    
    # 验证酶类型：如果 LLM 已填入，检查是否与正则一致
    if ma["enzyme_like_type"]:
        self._validate_enzyme_type(record, buckets, doc)
    else:
        # 兜底：LLM 未填入时才用正则
        self._fallback_enzyme_type(record, buckets, doc)
    
    # 底物：完全由 LLM 负责，不再用关键词匹配
    # (移除原来的 _SUBSTRATE_KEYWORDS 匹配逻辑)
    
    # 动力学：如果 LLM 已填入 Km/Vmax，跳过正则提取
    # 仅在 LLM 未填入时用正则兜底
    self._fallback_kinetics(record, buckets, table_values, selected_name)
    
    # 以下字段仍由 Rule 兜底提取（LLM 可能遗漏）
    self._extract_kcat_from_text(record, buckets.get("kinetics", []))
    self._extract_pH_profile(record, buckets)
    self._extract_temperature_profile(record, buckets)
    self._extract_synthesis_method(record, ...)
    self._extract_size_properties(record, ...)
    self._extract_physical_properties(record, ...)
    self._extract_morphology_from_text(record, ...)
    self._extract_applications_from_text(record, ...)
    self._extract_mechanism(record, ...)
    
    if doc:
        self._fulltext_fallback_extract(record, doc, selected_name)
    self._verifier_assisted_extract(record, doc, selected_name)
    
    return record

def _validate_enzyme_type(self, record, buckets, doc):
    """验证 LLM 提取的酶类型是否与正则匹配一致"""
    current_type = record["main_activity"]["enzyme_like_type"]
    search_texts = (buckets.get("activity", []) + buckets.get("mechanism", [])
                    + buckets.get("kinetics", [])[:5])
    if doc:
        title = doc.metadata.get("title", "")
        if title:
            search_texts.insert(0, title)
    
    for text in search_texts:
        for pattern, etype in _ENZYME_TYPE_PATTERNS:
            if pattern.search(text):
                if etype != current_type:
                    record["main_activity"]["kinetics"]["needs_review"] = True
                    logger.info(f"[RuleValidator] Enzyme type mismatch: "
                                f"LLM={current_type}, Rule={etype}")
                return

def _fallback_enzyme_type(self, record, buckets, doc):
    """兜底：LLM 未提取酶类型时用正则"""
    # (原 extract_from_evidence 中酶类型提取逻辑移到这里)
    ...
```

- [ ] **Step 2: 移除 _SUBSTRATE_KEYWORDS 提取逻辑**

在 `RuleExtractor.extract_from_evidence` 中，删除以下代码块：
```python
# 删除这段
if not record["main_activity"]["substrates"]:
    found = set()
    search_buckets = (...)
    for text in search_buckets:
        for sub in _SUBSTRATE_KEYWORDS:
            if sub.lower() in text.lower():
                found.add(sub)
    if found:
        record["main_activity"]["substrates"] = sorted(found)
```

底物提取完全由 LLM 的 `LLMStructuredExtractor` 负责。

- [ ] **Step 3: 修改动力学正则提取为兜底模式**

在 `_extract_kinetics_from_text` 等方法中，添加前置检查：
```python
def _extract_kinetics_from_text(self, record, texts):
    kin = record["main_activity"]["kinetics"]
    # 如果 LLM 已填入 Km 和 Vmax，跳过正则提取
    if kin.get("Km") is not None and kin.get("Vmax") is not None:
        return
    # 原有正则逻辑...
```

- [ ] **Step 4: 运行核心提取器测试**

Run: `python -m pytest test_single_main_nanozyme.py -v -k "test_" 2>&1 | head -50`
Expected: 测试通过（行为兼容，只是优先级变了）

---

## Task 7: 移除 PROBE_MOLECULES 硬编码

**Files:**
- Modify: `material_identifier.py`

- [ ] **Step 1: 替换 PROBE_MOLECULES 为领域知识加载器**

将 `material_identifier.py` 中的：
```python
PROBE_MOLECULES = {
    "crystal violet", "cv+", "cv",
    ...
}
```

替换为：
```python
from domain_knowledge import get_domain_knowledge
_dk = get_domain_knowledge()
PROBE_MOLECULES = _dk.get_probe_molecule_names()
```

- [ ] **Step 2: 增强 Prompt 中的探针分子语义描述**

在 `material_identifier.py` 的 Prompt 中，将硬编码的探针分子列表替换为语义描述：
```python
# 在 _build_messages 中添加
probe_desc = (
    "Probe molecules are signal indicators (e.g., chromogenic/fluorogenic dyes like TMB, ABTS, "
    "crystal violet, methylene blue, rhodamine dyes) used to monitor reactions. "
    "They are NOT the target analyte being detected. "
    "Common probe molecules include: " + _dk.generate_probe_molecule_prompt_snippet()
)
```

- [ ] **Step 3: 验证探针分子集合完整**

Run: `python -c "from material_identifier import PROBE_MOLECULES; print(f'Probe molecules: {len(PROBE_MOLECULES)}'); assert 'crystal violet' in PROBE_MOLECULES; print('OK')"`
Expected: 输出数量，OK

---

## Task 8: 验证全流程

- [ ] **Step 1: 运行所有测试**

Run: `python -m pytest tests/ -v --tb=short 2>&1 | tail -30`
Expected: 全部 PASS

- [ ] **Step 2: 验证导入链无循环依赖**

Run: `python -c "from nanozyme_models import EnzymeType; from schema_constraints import _ENZYME_TYPE_ENUM; from extraction_prompts import SYSTEM_PROMPT; from material_identifier import PROBE_MOLECULES; from domain_knowledge import get_domain_knowledge; print('All imports OK')"`
Expected: All imports OK

- [ ] **Step 3: 验证枚举一致性**

Run: `python -c "from nanozyme_models import EnzymeType; from schema_constraints import _ENZYME_TYPE_ENUM; from domain_knowledge import get_domain_knowledge; dk = get_domain_knowledge(); model_values = {e.value for e in EnzymeType}; schema_values = set(_ENZYME_TYPE_ENUM); dk_values = set(dk.get_enzyme_type_values()); assert model_values == schema_values == dk_values, f'Mismatch: model={model_values - dk_values}, schema={schema_values - dk_values}'; print('Enum consistency OK')"`
Expected: Enum consistency OK

---

## Task 9: 更新文档

- [ ] **Step 1: 更新 MODULE_MAP.md**

在"数据模型层"中添加 `domain_knowledge.yaml` 和 `domain_knowledge.py` 条目。

- [ ] **Step 2: 创建迭代记录**

在 `docs/iteration_logs/` 创建 `2026-05-21_domain-knowledge-centralization.md`。

- [ ] **Step 3: Commit**

```bash
git add domain_knowledge.yaml domain_knowledge.py tests/test_domain_knowledge.py nanozyme_models.py schema_constraints.py extraction_prompts.py single_main_nanozyme_extractor.py material_identifier.py docs/
git commit -m "refactor(extraction): 领域知识集中化+Rule层降级为验证器

- 创建 domain_knowledge.yaml 作为领域知识单一真相源
- 创建 domain_knowledge.py 加载器提供统一接口
- nanozyme_models.py/schema_constraints.py/extraction_prompts.py 从加载器读取数据
- RuleExtractor 从提取器降级为验证器+兜底器
- 移除 _SUBSTRATE_KEYWORDS 提取逻辑，底物由 LLM 负责
- PROBE_MOLECULES 从硬编码改为从领域知识库加载"
```
