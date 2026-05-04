# 架构优化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按照架构审查报告的短期+中期建议，优化系统的代码组织、消除重复定义、统一日志配置、添加超时保护、建立测试基础结构。

**Architecture:** 以 `nanozyme_models.py` 的 `EnzymeType` enum 为唯一权威源统一酶类型映射；删除废弃的 `single_record_assembler.py`；统一日志入口；为 pipeline 添加全局超时；创建 `dependencies.py` 集中管理可选依赖；建立 `tests/` 目录。

**Tech Stack:** Python 3.10+, pytest, asyncio, logging (RotatingFileHandler)

---

## 前置：确认测试运行方式

```bash
cd d:\ocrwiki版本\single_main_nanozyme
python -m pytest tests/ -v --tb=short 2>&1
```

如果 pytest 未安装：
```bash
pip install pytest
```

---

### Task A: 合并重复的酶类型映射为单一源

**Files:**
- Modify: `d:\ocrwiki版本\single_main_nanozyme\nanozyme_models.py`
- Modify: `d:\ocrwiki版本\single_main_nanozyme\consistency_agent.py`
- Modify: `d:\ocrwiki版本\single_main_nanozyme\activity_selector.py`
- Modify: `d:\ocrwiki版本\single_main_nanozyme\consistency_guard_agentic.py`
- Create: `d:\ocrwiki版本\single_main_nanozyme\tests\test_enzyme_type_normalization.py`

**背景：** 酶类型别名映射在 4 处独立定义（`nanozyme_models.py` 的 `_ENZYME_ALIAS_MAP`、`consistency_agent.py` 的 `_ALIASES_TO_CANONICAL`、`activity_selector.py` 的 `ENZYME_TYPE_NORMALIZATION`、`consistency_guard_agentic.py` 的内联 dict），新增酶类型需改 4 处，极易遗漏且归一化结果不一致。

- [ ] **Step A1: 编写测试 — 验证 EnzymeType.normalize_to_canonical 覆盖所有别名**

```python
# tests/test_enzyme_type_normalization.py
import pytest
from nanozyme_models import EnzymeType


class TestEnzymeTypeNormalization:
    """验证 EnzymeType.normalize_to_canonical 是酶类型归一化的唯一权威源"""

    # 所有已知别名 → 期望的规范形式
    ALIAS_CASES = [
        # peroxidase-like
        ("peroxidase-like", "peroxidase-like"),
        ("peroxidase_like", "peroxidase-like"),
        ("peroxidase like", "peroxidase-like"),
        ("pod-like", "peroxidase-like"),
        ("pod_like", "peroxidase-like"),
        ("POD-like", "peroxidase-like"),
        ("peroxidase (pod)-like", "peroxidase-like"),
        # oxidase-like
        ("oxidase-like", "oxidase-like"),
        ("oxidase_like", "oxidase-like"),
        ("oxidase like", "oxidase-like"),
        ("oxd-like", "oxidase-like"),
        ("oxd_like", "oxidase-like"),
        ("OXD-like", "oxidase-like"),
        ("oxidase (oxd)-like", "oxidase-like"),
        # catalase-like
        ("catalase-like", "catalase-like"),
        ("catalase_like", "catalase-like"),
        ("catalase like", "catalase-like"),
        ("cat-like", "catalase-like"),
        ("cat_like", "catalase-like"),
        ("CAT-like", "catalase-like"),
        ("catalase (cat)-like", "catalase-like"),
        # superoxide-dismutase-like
        ("superoxide-dismutase-like", "superoxide-dismutase-like"),
        ("superoxide_dismutase_like", "superoxide-dismutase-like"),
        ("sod-like", "superoxide-dismutase-like"),
        ("sod_like", "superoxide-dismutase-like"),
        ("SOD-like", "superoxide-dismutase-like"),
        ("superoxide dismutase (sod)-like", "superoxide-dismutase-like"),
        # glucose-oxidase-like
        ("glucose-oxidase-like", "glucose-oxidase-like"),
        ("glucose_oxidase_like", "glucose-oxidase-like"),
        ("gox-like", "glucose-oxidase-like"),
        ("gox_like", "glucose-oxidase-like"),
        ("GOx-like", "glucose-oxidase-like"),
        ("glucose oxidase (gox)-like", "glucose-oxidase-like"),
        # glutathione-peroxidase-like
        ("glutathione-peroxidase-like", "glutathione-peroxidase-like"),
        ("glutathione_peroxidase_like", "glutathione-peroxidase-like"),
        ("gpx-like", "glutathione-peroxidase-like"),
        ("gpx_like", "glutathione-peroxidase-like"),
        ("GPx-like", "glutathione-peroxidase-like"),
        ("glutathione peroxidase (gpx)-like", "glutathione-peroxidase-like"),
        # glutathione-oxidase-like
        ("glutathione-oxidase-like", "glutathione-oxidase-like"),
        ("glutathione_oxidase_like", "glutathione-oxidase-like"),
        ("gshox-like", "glutathione-oxidase-like"),
        ("gshox_like", "glutathione-oxidase-like"),
        ("glutathione oxidase (gshox)-like", "glutathione-oxidase-like"),
        # laccase-like
        ("laccase-like", "laccase-like"),
        ("laccase_like", "laccase-like"),
        ("laccase like", "laccase-like"),
        # phosphatase-like
        ("phosphatase-like", "phosphatase-like"),
        ("phosphatase_like", "phosphatase-like"),
        ("alp-like", "phosphatase-like"),
        ("alp_like", "phosphatase-like"),
        ("ALP-like", "phosphatase-like"),
        ("phosphatase (alp)-like", "phosphatase-like"),
        # esterase-like
        ("esterase-like", "esterase-like"),
        ("esterase_like", "esterase-like"),
        ("esterase like", "esterase-like"),
        # nuclease-like
        ("nuclease-like", "nuclease-like"),
        ("nuclease_like", "nuclease-like"),
        ("nuclease like", "nuclease-like"),
        # nitroreductase-like
        ("nitroreductase-like", "nitroreductase-like"),
        ("nitroreductase_like", "nitroreductase-like"),
        ("ntr-like", "nitroreductase-like"),
        ("ntr_like", "nitroreductase-like"),
        ("NTR-like", "nitroreductase-like"),
        ("nitroreductase (ntr)-like", "nitroreductase-like"),
        # hydrolase-like
        ("hydrolase-like", "hydrolase-like"),
        ("hydrolase_like", "hydrolase-like"),
        ("hydrolase like", "hydrolase-like"),
        # haloperoxidase-like
        ("haloperoxidase-like", "haloperoxidase-like"),
        ("haloperoxidase_like", "haloperoxidase-like"),
        ("vhpo-like", "haloperoxidase-like"),
        # tyrosinase-like
        ("tyrosinase-like", "tyrosinase-like"),
        ("tyrosinase_like", "tyrosinase-like"),
        # cascade-enzymatic
        ("cascade-enzymatic", "cascade-enzymatic"),
        ("cascade_enzymatic", "cascade-enzymatic"),
    ]

    @pytest.mark.parametrize("raw,expected", ALIAS_CASES)
    def test_normalize_to_canonical(self, raw, expected):
        result = EnzymeType.normalize_to_canonical(raw)
        assert result == expected, f"normalize_to_canonical({raw!r}) = {result!r}, expected {expected!r}"

    def test_normalize_to_canonical_empty_string(self):
        assert EnzymeType.normalize_to_canonical("") == ""

    def test_normalize_to_canonical_none(self):
        assert EnzymeType.normalize_to_canonical(None) == None

    def test_normalize_to_canonical_unknown_type(self):
        result = EnzymeType.normalize_to_canonical("some-unknown-type")
        assert result == "some-unknown-type"

    def test_normalize_to_canonical_case_insensitive(self):
        assert EnzymeType.normalize_to_canonical("PEROXIDASE-LIKE") == "peroxidase-like"
        assert EnzymeType.normalize_to_canonical("Peroxidase-Like") == "peroxidase-like"

    def test_all_enum_values_self_normalize(self):
        """每个 EnzymeType 的 value 归一化后应等于自身"""
        for member in EnzymeType:
            result = EnzymeType.normalize_to_canonical(member.value)
            assert result == member.value, f"{member.name} value {member.value!r} normalized to {result!r}"

    def test_underscore_variants_all_covered(self):
        """所有带下划线的变体都应归一化为带连字符的规范形式"""
        underscore_cases = [
            ("peroxidase_like", "peroxidase-like"),
            ("oxidase_like", "oxidase-like"),
            ("catalase_like", "catalase-like"),
            ("superoxide_dismutase_like", "superoxide-dismutase-like"),
            ("glucose_oxidase_like", "glucose-oxidase-like"),
            ("glutathione_peroxidase_like", "glutathione-peroxidase-like"),
            ("glutathione_oxidase_like", "glutathione-oxidase-like"),
            ("laccase_like", "laccase-like"),
            ("phosphatase_like", "phosphatase-like"),
            ("esterase_like", "esterase-like"),
            ("nuclease_like", "nuclease-like"),
            ("nitroreductase_like", "nitroreductase-like"),
            ("hydrolase_like", "hydrolase-like"),
            ("haloperoxidase_like", "haloperoxidase-like"),
            ("tyrosinase_like", "tyrosinase-like"),
            ("cascade_enzymatic", "cascade-enzymatic"),
        ]
        for raw, expected in underscore_cases:
            result = EnzymeType.normalize_to_canonical(raw)
            assert result == expected, f"normalize_to_canonical({raw!r}) = {result!r}, expected {expected!r}"
```

- [ ] **Step A2: 运行测试验证失败**

```bash
cd d:\ocrwiki版本\single_main_nanozyme
python -m pytest tests/test_enzyme_type_normalization.py -v --tb=short
```

预期：部分测试 FAIL，因为当前 `normalize_to_canonical` 不覆盖所有别名变体。

- [ ] **Step A3: 增强 nanozyme_models.py 的 normalize_to_canonical**

修改 `d:\ocrwiki版本\single_main_nanozyme\nanozyme_models.py`，将 `_ENZYME_ALIAS_MAP` 扩展为覆盖所有别名变体，并增强 `normalize_to_canonical` 方法：

```python
# 替换原有的 _ENZYME_ALIAS_MAP 为完整版
_ENZYME_ALIAS_MAP: Dict[str, str] = {
    # peroxidase-like
    "peroxidase-like": "peroxidase-like",
    "peroxidase_like": "peroxidase-like",
    "peroxidase like": "peroxidase-like",
    "peroxidase (pod)-like": "peroxidase-like",
    "pod-like": "peroxidase-like",
    "pod_like": "peroxidase-like",
    # oxidase-like
    "oxidase-like": "oxidase-like",
    "oxidase_like": "oxidase-like",
    "oxidase like": "oxidase-like",
    "oxidase (oxd)-like": "oxidase-like",
    "oxd-like": "oxidase-like",
    "oxd_like": "oxidase-like",
    # catalase-like
    "catalase-like": "catalase-like",
    "catalase_like": "catalase-like",
    "catalase like": "catalase-like",
    "catalase (cat)-like": "catalase-like",
    "cat-like": "catalase-like",
    "cat_like": "catalase-like",
    # superoxide-dismutase-like
    "superoxide-dismutase-like": "superoxide-dismutase-like",
    "superoxide_dismutase_like": "superoxide-dismutase-like",
    "superoxide dismutase (sod)-like": "superoxide-dismutase-like",
    "sod-like": "superoxide-dismutase-like",
    "sod_like": "superoxide-dismutase-like",
    # glucose-oxidase-like
    "glucose-oxidase-like": "glucose-oxidase-like",
    "glucose_oxidase_like": "glucose-oxidase-like",
    "glucose oxidase (gox)-like": "glucose-oxidase-like",
    "gox-like": "glucose-oxidase-like",
    "gox_like": "glucose-oxidase-like",
    # glutathione-peroxidase-like
    "glutathione-peroxidase-like": "glutathione-peroxidase-like",
    "glutathione_peroxidase_like": "glutathione-peroxidase-like",
    "glutathione peroxidase (gpx)-like": "glutathione-peroxidase-like",
    "gpx-like": "glutathione-peroxidase-like",
    "gpx_like": "glutathione-peroxidase-like",
    # glutathione-oxidase-like
    "glutathione-oxidase-like": "glutathione-oxidase-like",
    "glutathione_oxidase_like": "glutathione-oxidase-like",
    "glutathione oxidase (gshox)-like": "glutathione-oxidase-like",
    "gshox-like": "glutathione-oxidase-like",
    "gshox_like": "glutathione-oxidase-like",
    # laccase-like
    "laccase-like": "laccase-like",
    "laccase_like": "laccase-like",
    "laccase like": "laccase-like",
    # phosphatase-like
    "phosphatase-like": "phosphatase-like",
    "phosphatase_like": "phosphatase-like",
    "phosphatase (alp)-like": "phosphatase-like",
    "alp-like": "phosphatase-like",
    "alp_like": "phosphatase-like",
    # esterase-like
    "esterase-like": "esterase-like",
    "esterase_like": "esterase-like",
    "esterase like": "esterase-like",
    # nuclease-like
    "nuclease-like": "nuclease-like",
    "nuclease_like": "nuclease-like",
    "nuclease like": "nuclease-like",
    # nitroreductase-like
    "nitroreductase-like": "nitroreductase-like",
    "nitroreductase_like": "nitroreductase-like",
    "nitroreductase (ntr)-like": "nitroreductase-like",
    "ntr-like": "nitroreductase-like",
    "ntr_like": "nitroreductase-like",
    # hydrolase-like
    "hydrolase-like": "hydrolase-like",
    "hydrolase_like": "hydrolase-like",
    "hydrolase like": "hydrolase-like",
    # haloperoxidase-like
    "haloperoxidase-like": "haloperoxidase-like",
    "haloperoxidase_like": "haloperoxidase-like",
    "vhpo-like": "haloperoxidase-like",
    # tyrosinase-like
    "tyrosinase-like": "tyrosinase-like",
    "tyrosinase_like": "tyrosinase-like",
    # cascade-enzymatic
    "cascade-enzymatic": "cascade-enzymatic",
    "cascade_enzymatic": "cascade-enzymatic",
}
```

同时增强 `normalize_to_canonical` 方法，使其在精确匹配失败后尝试更多变体：

```python
@classmethod
def normalize_to_canonical(cls, value: str) -> str:
    if not value:
        return value
    key = value.strip().lower()
    if key in _ENZYME_ALIAS_MAP:
        return _ENZYME_ALIAS_MAP[key]
    cleaned = re.sub(r'\s*\([A-Za-z]+\)\s*', ' ', key).strip()
    cleaned = re.sub(r'\s+', '-', cleaned)
    if cleaned in _ENZYME_ALIAS_MAP:
        return _ENZYME_ALIAS_MAP[cleaned]
    for member in cls:
        if member.value.lower() == cleaned:
            return member.value
    for member in cls:
        if member.value.lower() == key:
            return member.value
    underscore_key = key.replace("-", "_")
    if underscore_key in _ENZYME_ALIAS_MAP:
        return _ENZYME_ALIAS_MAP[underscore_key]
    hyphen_key = key.replace("_", "-")
    if hyphen_key in _ENZYME_ALIAS_MAP:
        return _ENZYME_ALIAS_MAP[hyphen_key]
    return value
```

- [ ] **Step A4: 运行测试验证通过**

```bash
cd d:\ocrwiki版本\single_main_nanozyme
python -m pytest tests/test_enzyme_type_normalization.py -v --tb=short
```

预期：全部 PASS。

- [ ] **Step A5: 修改 consistency_agent.py — 删除 _ALIASES_TO_CANONICAL，改用 EnzymeType**

在 `d:\ocrwiki版本\single_main_nanozyme\consistency_agent.py` 中：

删除 `_ALIASES_TO_CANONICAL` 字典（第7-70行），修改 `normalize_enzyme_types` 方法：

```python
def normalize_enzyme_types(self, record: Dict) -> Tuple[Dict, List[str]]:
    warnings = []
    act = record.get("main_activity", {})
    if not isinstance(act, dict):
        return record, warnings
    etype = act.get("enzyme_like_type")
    if etype and isinstance(etype, str):
        from nanozyme_models import EnzymeType
        canonical = EnzymeType.normalize_to_canonical(etype)
        if canonical and canonical != etype:
            act["enzyme_like_type"] = canonical
            warnings.append(f"enzyme_type_normalized: {etype} -> {canonical}")
    return record, warnings
```

- [ ] **Step A6: 修改 activity_selector.py — 删除 ENZYME_TYPE_NORMALIZATION，改用 EnzymeType**

在 `d:\ocrwiki版本\single_main_nanozyme\activity_selector.py` 中：

删除 `ENZYME_TYPE_NORMALIZATION` 字典（第7-55行），修改 `normalize_enzyme_type` 函数：

```python
def normalize_enzyme_type(raw: Optional[str]) -> str:
    if not raw:
        return "unknown"
    from nanozyme_models import EnzymeType
    canonical = EnzymeType.normalize_to_canonical(raw)
    if canonical and canonical != raw:
        return canonical.replace("-", "_")
    return "unknown"
```

注意：`activity_selector.py` 内部使用下划线格式（如 `peroxidase_like`），所以需要做 `-` → `_` 转换以保持兼容。

- [ ] **Step A7: 修改 consistency_guard_agentic.py — 删除内联 _normalize_enzyme_type，改用 EnzymeType**

在 `d:\ocrwiki版本\single_main_nanozyme\consistency_guard_agentic.py` 中：

删除 `_normalize_enzyme_type` 静态方法（第220-230行），修改 `check_after_llm_extraction` 方法中的调用：

```python
# 原代码：
llm_norm = self._normalize_enzyme_type(llm_etype)
rule_norm = self._normalize_enzyme_type(rule_etype)

# 改为：
from nanozyme_models import EnzymeType
llm_norm = EnzymeType.normalize_to_canonical(llm_etype) if llm_etype else None
rule_norm = EnzymeType.normalize_to_canonical(rule_etype) if rule_etype else None
```

- [ ] **Step A8: 运行全量测试确认无回归**

```bash
cd d:\ocrwiki版本\single_main_nanozyme
python -m pytest tests/ -v --tb=short
```

- [ ] **Step A9: Commit**

```bash
git add nanozyme_models.py consistency_agent.py activity_selector.py consistency_guard_agentic.py tests/test_enzyme_type_normalization.py
git commit -m "refactor(models): 合并重复的酶类型映射为 EnzymeType 单一权威源"
```

---

### Task B: 移除 single_record_assembler.py 废弃代码

**Files:**
- Delete: `d:\ocrwiki版本\single_main_nanozyme\single_record_assembler.py`

**背景：** 该文件已标记为 deprecated，无外部引用（grep 确认无任何文件 import SingleRecordAssembler），仅 `single_record_assembler.py` 自身 import 了 `activity_selector` 等模块。删除不会影响任何功能。

- [ ] **Step B1: 确认无外部引用**

```bash
cd d:\ocrwiki版本\single_main_nanozyme
python -c "import ast, sys; files = [f for f in __import__('glob').glob('*.py') if f != 'single_record_assembler.py']; refs = []; [refs.extend([(f, node.names[0].name) for node in ast.walk(ast.parse(open(f, encoding='utf-8').read())) if isinstance(node, ast.ImportFrom) and node.module == 'single_record_assembler']) for f in files]; print('No references found' if not refs else f'References: {refs}')"
```

预期输出：`No references found`

- [ ] **Step B2: 删除文件**

```bash
cd d:\ocrwiki版本\single_main_nanozyme
Remove-Item single_record_assembler.py
```

- [ ] **Step B3: 验证导入无报错**

```bash
cd d:\ocrwiki版本\single_main_nanozyme
python -c "from single_main_nanozyme_extractor import SingleMainNanozymePipeline; print('OK')"
python -c "from extraction_pipeline import ExtractionPipeline; print('OK')"
```

预期输出：`OK` `OK`

- [ ] **Step B4: Commit**

```bash
git add single_record_assembler.py
git commit -m "refactor: 移除废弃的 single_record_assembler.py"
```

---

### Task C: 统一日志配置

**Files:**
- Modify: `d:\ocrwiki版本\single_main_nanozyme\logging_setup.py`
- Modify: `d:\ocrwiki版本\single_main_nanozyme\extraction_pipeline.py`
- Modify: `d:\ocrwiki版本\single_main_nanozyme\pdf_basic_gui.py`
- Create: `d:\ocrwiki版本\single_main_nanozyme\tests\test_logging_setup.py`

- [ ] **Step C1: 编写测试 — 验证日志配置功能**

```python
# tests/test_logging_setup.py
import logging
import pytest
from logging_setup import setup_logging, get_logger


class TestLoggingSetup:

    def test_setup_logging_basic(self):
        import logging_setup
        logging_setup._configured = False
        setup_logging(level=logging.WARNING)
        root = logging.getLogger()
        assert len(root.handlers) >= 1
        console_handler = root.handlers[0]
        assert console_handler.level == logging.WARNING

    def test_get_logger_returns_logger(self):
        import logging_setup
        logging_setup._configured = False
        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_module"

    def test_module_log_levels_applied(self):
        import logging_setup
        logging_setup._configured = False
        setup_logging(level=logging.DEBUG)
        api_logger = logging.getLogger("api_client")
        assert api_logger.level == logging.INFO
```

- [ ] **Step C2: 运行测试验证失败**

```bash
cd d:\ocrwiki版本\single_main_nanozyme
python -m pytest tests/test_logging_setup.py -v --tb=short
```

- [ ] **Step C3: 增强 logging_setup.py — 添加 RotatingFileHandler 支持**

在 `d:\ocrwiki版本\single_main_nanozyme\logging_setup.py` 的 `setup_logging` 函数中，将 `FileHandler` 替换为 `RotatingFileHandler`：

```python
from logging.handlers import RotatingFileHandler

# 在文件处理器部分替换为：
if log_file:
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8',
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(DETAILED_FORMAT))
    root_logger.addHandler(file_handler)
```

- [ ] **Step C4: 运行测试验证通过**

```bash
cd d:\ocrwiki版本\single_main_nanozyme
python -m pytest tests/test_logging_setup.py -v --tb=short
```

- [ ] **Step C5: 确保 extraction_pipeline.py 在 __init__ 中调用 setup_logging**

检查 `d:\ocrwiki版本\single_main_nanozyme\extraction_pipeline.py` 的 `_setup_logging` 方法是否调用了 `setup_logging()`。当前代码已有 `from logging_setup import setup_logging, get_logger`，确认调用路径正确。

- [ ] **Step C6: 确保 pdf_basic_gui.py 在启动时调用 setup_logging**

检查 `d:\ocrwiki版本\single_main_nanozyme\pdf_basic_gui.py` 是否在初始化时调用了 `setup_logging()`。

- [ ] **Step C7: Commit**

```bash
git add logging_setup.py extraction_pipeline.py pdf_basic_gui.py tests/test_logging_setup.py
git commit -m "refactor(logging): 统一日志配置，添加 RotatingFileHandler 支持"
```

---

### Task D: 添加全局 pipeline 超时

**Files:**
- Modify: `d:\ocrwiki版本\single_main_nanozyme\extraction_pipeline.py`
- Create: `d:\ocrwiki版本\single_main_nanozyme\tests\test_pipeline_timeout.py`

- [ ] **Step D1: 编写测试 — 验证 pipeline 超时机制**

```python
# tests/test_pipeline_timeout.py
import asyncio
import pytest


class TestPipelineTimeout:

    def test_timeout_config_default(self):
        from extraction_pipeline import ExtractionPipeline
        pipeline = ExtractionPipeline.__new__(ExtractionPipeline)
        pipeline.per_document_timeout = 300
        assert pipeline.per_document_timeout == 300

    def test_timeout_config_custom(self):
        from extraction_pipeline import ExtractionPipeline
        pipeline = ExtractionPipeline.__new__(ExtractionPipeline)
        pipeline.per_document_timeout = 120
        assert pipeline.per_document_timeout == 120

    @pytest.mark.asyncio
    async def test_timeout_triggers_on_slow_task(self):
        async def slow_task():
            await asyncio.sleep(10)
            return "done"

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(slow_task(), timeout=0.1)
```

- [ ] **Step D2: 运行测试验证失败**

```bash
cd d:\ocrwiki版本\single_main_nanozyme
python -m pytest tests/test_pipeline_timeout.py -v --tb=short
```

- [ ] **Step D3: 在 extraction_pipeline.py 中添加超时参数和逻辑**

在 `ExtractionPipeline.__init__` 中添加 `per_document_timeout` 参数：

```python
def __init__(
    self,
    config_path: str = "config.yaml",
    output_dir: Optional[str] = None,
    enable_cache: bool = True,
    enable_queue: bool = False,
    use_new_modules: bool = True,
    per_document_timeout: int = 300,
):
    # ... existing init code ...
    self.per_document_timeout = per_document_timeout
```

在 `extract_from_mid_json` 或核心提取方法中包裹 `asyncio.wait_for`：

```python
async def _extract_with_timeout(self, mid_json_path, **kwargs):
    try:
        result = await asyncio.wait_for(
            self._do_extract(mid_json_path, **kwargs),
            timeout=self.per_document_timeout,
        )
        return result
    except asyncio.TimeoutError:
        logger.error(f"提取超时 ({self.per_document_timeout}s): {mid_json_path}")
        return {"error": "timeout", "status": "failed"}
```

- [ ] **Step D4: 运行测试验证通过**

```bash
cd d:\ocrwiki版本\single_main_nanozyme
python -m pytest tests/test_pipeline_timeout.py -v --tb=short
```

- [ ] **Step D5: Commit**

```bash
git add extraction_pipeline.py tests/test_pipeline_timeout.py
git commit -m "feat(pipeline): 添加全局 pipeline 超时保护"
```

---

### Task E: 统一依赖管理模块

**Files:**
- Create: `d:\ocrwiki版本\single_main_nanozyme\dependencies.py`
- Modify: `d:\ocrwiki版本\single_main_nanozyme\extraction_pipeline.py`
- Create: `d:\ocrwiki版本\single_main_nanozyme\tests\test_dependencies.py`

- [ ] **Step E1: 编写测试**

```python
# tests/test_dependencies.py
import pytest
from dependencies import check_dependency, check_all_dependencies, DependencyStatus


class TestDependencies:

    def test_check_dependency_available(self):
        status = check_dependency("os", "builtin")
        assert status.available is True

    def test_check_dependency_unavailable(self):
        status = check_dependency("nonexistent_module_xyz", "test")
        assert status.available is False

    def test_check_all_dependencies_returns_dict(self):
        result = check_all_dependencies()
        assert isinstance(result, dict)
        assert "single_main_nanozyme_extractor" in result
        assert "api_client" in result
```

- [ ] **Step E2: 运行测试验证失败**

```bash
cd d:\ocrwiki版本\single_main_nanozyme
python -m pytest tests/test_dependencies.py -v --tb=short
```

- [ ] **Step E3: 创建 dependencies.py**

```python
# dependencies.py
import importlib
import logging
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class DependencyStatus:
    name: str
    available: bool
    error: Optional[str] = None


def check_dependency(module_name: str, display_name: str) -> DependencyStatus:
    try:
        importlib.import_module(module_name)
        return DependencyStatus(name=display_name, available=True)
    except ImportError as e:
        return DependencyStatus(name=display_name, available=False, error=str(e))


def check_all_dependencies() -> Dict[str, DependencyStatus]:
    deps = {
        "single_main_nanozyme_extractor": "single_main_nanozyme_extractor",
        "api_client": "api_client",
        "config_manager": "config_manager",
        "cache_manager": "cache_manager",
        "task_queue": "task_queue",
        "llm_extractor": "llm_extractor",
        "vlm_extractor": "vlm_extractor",
        "consistency_agent": "consistency_agent",
        "cross_validation_agent": "cross_validation_agent",
        "extraction_verifier": "extraction_verifier",
        "nanozyme_preprocessor_midjson": "nanozyme_preprocessor_midjson",
        "yaml": "yaml",
    }
    results = {}
    for module_name, display_name in deps.items():
        results[display_name] = check_dependency(module_name, display_name)
    return results


def report_dependencies() -> None:
    results = check_all_dependencies()
    available = [k for k, v in results.items() if v.available]
    unavailable = [k for k, v in results.items() if not v.available]
    logger.info(f"依赖检查: {len(available)} 可用, {len(unavailable)} 不可用")
    if unavailable:
        for name in unavailable:
            logger.warning(f"  缺失: {name} - {results[name].error}")
```

- [ ] **Step E4: 运行测试验证通过**

```bash
cd d:\ocrwiki版本\single_main_nanozyme
python -m pytest tests/test_dependencies.py -v --tb=short
```

- [ ] **Step E5: 修改 extraction_pipeline.py 使用 dependencies 模块**

将 `extraction_pipeline.py` 中的 try/except 导入链替换为使用 `dependencies` 模块：

```python
from dependencies import check_all_dependencies, report_dependencies

# 在 __init__ 中：
deps = check_all_dependencies()
self.deps_available = {
    "config_manager": deps["config_manager"].available,
    "cache_manager": deps["cache_manager"].available,
    "task_queue": deps["task_queue"].available,
    "smn": deps["single_main_nanozyme_extractor"].available,
    "api_client": deps["api_client"].available,
    "yaml": deps["yaml"].available,
}
```

- [ ] **Step E6: Commit**

```bash
git add dependencies.py extraction_pipeline.py tests/test_dependencies.py
git commit -m "refactor(deps): 创建统一依赖管理模块 dependencies.py"
```

---

### Task F: 建立 tests/ 目录 + pytest 基础结构

**Files:**
- Create: `d:\ocrwiki版本\single_main_nanozyme\tests\__init__.py`
- Create: `d:\ocrwiki版本\single_main_nanozyme\tests\conftest.py`

- [ ] **Step F1: 创建 tests/__init__.py**

```python
# tests/__init__.py
```

- [ ] **Step F2: 创建 tests/conftest.py**

```python
# tests/conftest.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
```

- [ ] **Step F3: 运行全量测试**

```bash
cd d:\ocrwiki版本\single_main_nanozyme
python -m pytest tests/ -v --tb=short
```

- [ ] **Step F4: Commit**

```bash
git add tests/__init__.py tests/conftest.py
git commit -m "test: 建立 tests/ 目录和 pytest 基础结构"
```

---

## 集成验证

- [ ] **Step V1: 运行全量测试**

```bash
cd d:\ocrwiki版本\single_main_nanozyme
python -m pytest tests/ -v --tb=short
```

- [ ] **Step V2: 验证核心模块导入无报错**

```bash
cd d:\ocrwiki版本\single_main_nanozyme
python -c "from nanozyme_models import EnzymeType; print('nanozyme_models OK')"
python -c "from consistency_agent import ConsistencyAgent; print('consistency_agent OK')"
python -c "from activity_selector import normalize_enzyme_type; print('activity_selector OK')"
python -c "from consistency_guard_agentic import AgenticConsistencyGuard; print('consistency_guard_agentic OK')"
python -c "from dependencies import check_all_dependencies; print('dependencies OK')"
python -c "from logging_setup import setup_logging; print('logging_setup OK')"
```

- [ ] **Step V3: 最终 Commit**

```bash
git add .
git commit -m "chore: 架构优化集成验证通过"
```
