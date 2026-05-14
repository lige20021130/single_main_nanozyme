# 约束解码引擎实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现多层约束解码策略，将JSON输出结构合规率从~92%提升到>99%

**Architecture:** 新增 `ConstrainedDecodingEngine` 作为所有LLM调用的统一中间层，实现4层约束（API原生json_schema → json_object+Prompt注入 → Pydantic后验证+auto_fix → Schema感知Prompt增强），兼容DeepSeek/GLM/Qwen等国产模型

**Tech Stack:** Python 3.10+, aiohttp, pydantic, 现有api_client.py

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `constrained_decoding.py` | Create | ConstrainedDecodingEngine核心实现：模型能力检测、4层约束调用、Schema Prompt注入、后验证+auto_fix |
| `schema_constraints.py` | Modify | 完善主Schema（additionalProperties/required/enum）；新增6个子任务Schema；新增TASK_SCHEMAS注册表 |
| `api_client.py` | Modify | chat_completion_text增加response_format参数；新增supports_json_schema()检测 |
| `llm_structured_extractor.py` | Modify | 移除instructor依赖；使用ConstrainedDecodingEngine统一调用 |
| `llm_extractor.py` | Modify | 全文提取启用约束解码（json_object + Schema Prompt注入） |
| `extraction_agents.py` | Modify | 4个Agent的LLM调用接入ConstrainedDecodingEngine |
| `tests/test_constrained_decoding.py` | Create | 约束解码引擎单元测试 |

---

### Task 1: 完善Schema定义（schema_constraints.py）

**Files:**
- Modify: `schema_constraints.py`

- [ ] **Step 1: 完善NANOZYME_EXTRACTION_SCHEMA，补全additionalProperties、required、enum**

在 `schema_constraints.py` 中，将现有的 `NANOZYME_EXTRACTION_SCHEMA` 替换为完善版本。关键改动：
- 所有object节点添加 `"additionalProperties": False`
- `enzyme_like_type` 添加 `"enum": _ENZYME_TYPE_ENUM + [None]`
- `application_type` 添加 `"enum": _APPLICATION_TYPE_ENUM + [None]`
- 补全所有 `required` 字段

将现有的 `NANOZYME_EXTRACTION_SCHEMA` 和 `NANOZYME_KINETICS_SCHEMA` 定义替换为：

```python
_KINETICS_PROPERTIES = {
    "Km": {"type": ["number", "null"]},
    "Km_unit": {"type": ["string", "null"], "enum": _KM_UNIT_ENUM},
    "Vmax": {"type": ["number", "null"]},
    "Vmax_unit": {"type": ["string", "null"], "enum": _VMAX_UNIT_ENUM},
    "kcat": {"type": ["number", "null"]},
    "kcat_unit": {"type": ["string", "null"], "enum": _KCAT_UNIT_ENUM},
    "kcat_Km": {"type": ["number", "null"]},
    "kcat_Km_unit": {"type": ["string", "null"], "enum": _KCAT_KM_UNIT_ENUM},
    "substrate": {"type": ["string", "null"]},
    "detection_method": {"type": ["string", "null"]},
    "material_variant": {"type": ["string", "null"]},
}

NANOZYME_KINETICS_SCHEMA = {
    "type": "object",
    "properties": _KINETICS_PROPERTIES,
    "required": [],
    "additionalProperties": False,
}

_APPLICATION_ENTRY_PROPERTIES = {
    "application_type": {"type": ["string", "null"], "enum": _APPLICATION_TYPE_ENUM + [None]},
    "target_analyte": {"type": ["string", "null"]},
    "detection_limit": {"type": ["number", "null"]},
    "detection_limit_unit": {"type": ["string", "null"]},
    "method": {"type": ["string", "null"]},
    "sample_type": {"type": ["string", "null"]},
}

NANOZYME_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "selected_nanozyme": {
            "type": "object",
            "properties": {
                "name": {"type": ["string", "null"]},
                "morphology": {"type": ["string", "null"]},
                "size": {"type": ["number", "string", "null"]},
                "size_unit": {"type": ["string", "null"], "enum": _SIZE_UNIT_ENUM},
                "crystal_structure": {"type": ["string", "null"]},
                "surface_area": {"type": ["string", "null"]},
                "synthesis_method": {"type": ["string", "null"]},
                "synthesis_conditions": {
                    "type": "object",
                    "properties": {
                        "temperature": {"type": ["number", "string", "null"]},
                        "time": {"type": ["string", "null"]},
                        "precursors": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "solvent": {"type": ["string", "null"]},
                        "atmosphere": {"type": ["string", "null"]},
                        "post_treatment": {"type": ["string", "null"]},
                    },
                    "additionalProperties": False,
                },
                "characterization": {
                    "type": "array",
                    "items": {"type": "string"}
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        "main_activity": {
            "type": "object",
            "properties": {
                "enzyme_like_type": {
                    "type": ["string", "null"],
                    "enum": _ENZYME_TYPE_ENUM + [None],
                },
                "substrates": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "kinetics": NANOZYME_KINETICS_SCHEMA,
                "kinetics_list": {
                    "type": "array",
                    "items": NANOZYME_KINETICS_SCHEMA,
                },
                "pH_profile": {
                    "type": "object",
                    "properties": {
                        "optimal_pH": {"type": ["number", "null"]},
                        "pH_range": {"type": ["string", "null"]},
                    },
                    "additionalProperties": False,
                },
                "temperature_profile": {
                    "type": "object",
                    "properties": {
                        "optimal_temperature": {"type": ["number", "null"]},
                        "temperature_range": {"type": ["string", "null"]},
                    },
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
        "applications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": _APPLICATION_ENTRY_PROPERTIES,
                "additionalProperties": False,
            }
        },
    },
    "required": ["selected_nanozyme", "main_activity"],
    "additionalProperties": False,
}
```

- [ ] **Step 2: 新增6个子任务Schema和TASK_SCHEMAS注册表**

在 `schema_constraints.py` 末尾（`auto_fix_schema_errors` 函数之后）添加：

```python
KINETICS_SCHEMA = {
    "type": "object",
    "properties": {
        "kinetics": NANOZYME_KINETICS_SCHEMA,
        "kinetics_list": {
            "type": "array",
            "items": NANOZYME_KINETICS_SCHEMA,
        },
    },
    "additionalProperties": False,
}

MORPHOLOGY_SCHEMA = {
    "type": "object",
    "properties": {
        "morphology": {"type": ["string", "null"]},
        "size": {"type": ["number", "null"]},
        "size_unit": {"type": ["string", "null"], "enum": _SIZE_UNIT_ENUM},
        "crystal_structure": {"type": ["string", "null"]},
        "surface_area": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}

APPLICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "applications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": _APPLICATION_ENTRY_PROPERTIES,
                "additionalProperties": False,
            }
        }
    },
    "additionalProperties": False,
}

ENZYME_TYPE_SCHEMA = {
    "type": "object",
    "properties": {
        "enzyme_like_type": {
            "type": ["string", "null"],
            "enum": _ENZYME_TYPE_ENUM + [None],
        },
    },
    "additionalProperties": False,
}

SYNTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "synthesis_method": {"type": ["string", "null"]},
        "synthesis_conditions": {
            "type": "object",
            "properties": {
                "temperature": {"type": ["number", "string", "null"]},
                "time": {"type": ["string", "null"]},
                "precursors": {"type": "array", "items": {"type": "string"}},
                "solvent": {"type": ["string", "null"]},
                "atmosphere": {"type": ["string", "null"]},
                "post_treatment": {"type": ["string", "null"]},
            },
            "additionalProperties": False,
        },
        "characterization": {
            "type": "array",
            "items": {"type": "string"}
        },
    },
    "additionalProperties": False,
}

PH_TEMP_SCHEMA = {
    "type": "object",
    "properties": {
        "pH_profile": {
            "type": "object",
            "properties": {
                "optimal_pH": {"type": ["number", "null"]},
                "pH_range": {"type": ["string", "null"]},
            },
            "additionalProperties": False,
        },
        "temperature_profile": {
            "type": "object",
            "properties": {
                "optimal_temperature": {"type": ["number", "null"]},
                "temperature_range": {"type": ["string", "null"]},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}

TASK_SCHEMAS = {
    "kinetics": KINETICS_SCHEMA,
    "morphology": MORPHOLOGY_SCHEMA,
    "applications": APPLICATION_SCHEMA,
    "enzyme_type": ENZYME_TYPE_SCHEMA,
    "synthesis": SYNTHESIS_SCHEMA,
    "ph_temp": PH_TEMP_SCHEMA,
    "table_kinetics": KINETICS_SCHEMA,
    "full_extraction": NANOZYME_EXTRACTION_SCHEMA,
}
```

- [ ] **Step 3: 更新get_schema_for_openai使用完善后的Schema**

将现有的 `get_schema_for_openai` 函数替换为：

```python
def get_schema_for_openai() -> Dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "nanozyme_extraction",
            "strict": True,
            "schema": NANOZYME_EXTRACTION_SCHEMA,
        }
    }


def get_task_schema_for_openai(task_name: str) -> Dict[str, Any]:
    schema = TASK_SCHEMAS.get(task_name, NANOZYME_EXTRACTION_SCHEMA)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": task_name,
            "strict": True,
            "schema": schema,
        }
    }
```

- [ ] **Step 4: 增强auto_fix_schema_errors，添加更多修复规则**

将现有的 `auto_fix_schema_errors` 函数替换为：

```python
def auto_fix_schema_errors(data: Dict[str, Any], errors: List[str]) -> Dict[str, Any]:
    from nanozyme_models import EnzymeType, ApplicationType

    for err in errors:
        if "unrealistically large" in err and "Km" in err:
            kin = data.get("main_activity", {}).get("kinetics", {})
            if isinstance(kin, dict):
                kin["Km"] = None
                kin["Km_unit"] = None
        elif "should be converted to μM/s" in err and "Vmax" in err:
            kin = data.get("main_activity", {}).get("kinetics", {})
            if isinstance(kin, dict):
                vmax = kin.get("Vmax")
                vmax_u = kin.get("Vmax_unit", "")
                if isinstance(vmax, (int, float)):
                    if vmax_u in ("M/s", "M·s-1", "M s^-1"):
                        kin["Vmax"] = vmax * 1e6
                        kin["Vmax_unit"] = "μM/s"
                    elif vmax_u in ("mM/s", "mM·s-1"):
                        kin["Vmax"] = vmax * 1e3
                        kin["Vmax_unit"] = "μM/s"
        elif "enzyme_like_type" in err and "not in allowed enum" in err:
            ma = data.get("main_activity", {})
            etype = ma.get("enzyme_like_type")
            if etype and isinstance(etype, str):
                normalized = EnzymeType.normalize_canonical(etype)
                if normalized != etype:
                    ma["enzyme_like_type"] = normalized
                else:
                    ma["enzyme_like_type"] = None
        elif "application_type" in err and "not in allowed enum" in err:
            import re as _re
            idx_match = _re.search(r'applications\[(\d+)\]', err)
            if idx_match:
                idx = int(idx_match.group(1))
                apps = data.get("applications", [])
                if idx < len(apps) and isinstance(apps[idx], dict):
                    at = apps[idx].get("application_type")
                    if at and isinstance(at, str):
                        normalized = ApplicationType.normalize_canonical(at)
                        if normalized != at:
                            apps[idx]["application_type"] = normalized
                        else:
                            apps[idx]["application_type"] = "other"

    data = _fix_numeric_strings(data)
    data = _remove_unknown_fields(data)

    return data


def _fix_numeric_strings(data: Any) -> Any:
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            if k in ("Km", "Vmax", "kcat", "kcat_Km", "size", "detection_limit",
                      "optimal_pH", "optimal_temperature", "temperature") and isinstance(v, str):
                try:
                    result[k] = float(v)
                except (ValueError, TypeError):
                    result[k] = None
            else:
                result[k] = _fix_numeric_strings(v)
        return result
    elif isinstance(data, list):
        return [_fix_numeric_strings(item) for item in data]
    return data


def _remove_unknown_fields(data: Any) -> Any:
    _KNOWN_TOP_KEYS = {"selected_nanozyme", "main_activity", "applications", "paper", "nanozyme_systems", "catalytic_activities", "evidence"}
    _KNOWN_NANOZYME_KEYS = {"name", "morphology", "size", "size_unit", "crystal_structure", "surface_area", "synthesis_method", "synthesis_conditions", "characterization"}
    _KNOWN_ACTIVITY_KEYS = {"enzyme_like_type", "substrates", "kinetics", "kinetics_list", "pH_profile", "temperature_profile"}
    _KNOWN_KINETICS_KEYS = {"Km", "Km_unit", "Vmax", "Vmax_unit", "kcat", "kcat_unit", "kcat_Km", "kcat_Km_unit", "substrate", "detection_method", "material_variant"}
    _KNOWN_APP_KEYS = {"application_type", "target_analyte", "detection_limit", "detection_limit_unit", "method", "sample_type"}

    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            if k in _KNOWN_TOP_KEYS or k in _KNOWN_NANOZYME_KEYS or k in _KNOWN_ACTIVITY_KEYS or k in _KNOWN_KINETICS_KEYS or k in _KNOWN_APP_KEYS:
                result[k] = _remove_unknown_fields(v)
            else:
                logger.debug(f"Removing unknown field: {k}")
        return result
    elif isinstance(data, list):
        return [_remove_unknown_fields(item) for item in data]
    return data
```

- [ ] **Step 5: 运行现有测试确认不破坏**

Run: `python -m pytest tests/test_schema_constraints.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add schema_constraints.py
git commit -m "feat(schema): 完善JSON Schema定义，新增子任务Schema和增强auto_fix"
```

---

### Task 2: 创建ConstrainedDecodingEngine（constrained_decoding.py）

**Files:**
- Create: `constrained_decoding.py`
- Test: `tests/test_constrained_decoding.py`

- [ ] **Step 1: 编写ConstrainedDecodingEngine的失败测试**

创建 `tests/test_constrained_decoding.py`：

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from constrained_decoding import ConstrainedDecodingEngine, SUPPORTED_JSON_SCHEMA_PREFIXES


class TestModelDetection:
    def test_deepseek_chat_supports_json_schema(self):
        client = MagicMock()
        client.llm_model = "deepseek-chat"
        engine = ConstrainedDecodingEngine(client)
        assert engine.supports_json_schema is True

    def test_gpt4o_supports_json_schema(self):
        client = MagicMock()
        client.llm_model = "gpt-4o"
        engine = ConstrainedDecodingEngine(client)
        assert engine.supports_json_schema is True

    def test_glm4_supports_json_schema(self):
        client = MagicMock()
        client.llm_model = "glm-4"
        engine = ConstrainedDecodingEngine(client)
        assert engine.supports_json_schema is True

    def test_qwen_does_not_support_json_schema(self):
        client = MagicMock()
        client.llm_model = "Qwen/Qwen2.5-VL-72B-Instruct"
        engine = ConstrainedDecodingEngine(client)
        assert engine.supports_json_schema is False

    def test_unknown_model_no_json_schema(self):
        client = MagicMock()
        client.llm_model = "some-random-model"
        engine = ConstrainedDecodingEngine(client)
        assert engine.supports_json_schema is False


class TestSchemaPromptInjection:
    def test_inject_schema_prompt_adds_constraints(self):
        client = MagicMock()
        client.llm_model = "deepseek-chat"
        engine = ConstrainedDecodingEngine(client)
        messages = [{"role": "system", "content": "You are an extractor."}]
        enhanced = engine._inject_schema_prompt(messages, "kinetics", None)
        assert len(enhanced) == 1
        assert "enzyme_like_type" in enhanced[0]["content"]
        assert "application_type" in enhanced[0]["content"]

    def test_inject_schema_prompt_preserves_existing_content(self):
        client = MagicMock()
        client.llm_model = "deepseek-chat"
        engine = ConstrainedDecodingEngine(client)
        messages = [{"role": "system", "content": "Original prompt."}]
        enhanced = engine._inject_schema_prompt(messages, "kinetics", None)
        assert "Original prompt." in enhanced[0]["content"]

    def test_inject_schema_prompt_with_no_system_message(self):
        client = MagicMock()
        client.llm_model = "deepseek-chat"
        engine = ConstrainedDecodingEngine(client)
        messages = [{"role": "user", "content": "Extract data"}]
        enhanced = engine._inject_schema_prompt(messages, "kinetics", None)
        assert len(enhanced) == 2
        assert enhanced[0]["role"] == "system"


class TestValidateAndFix:
    def test_fix_enzyme_type_normalization(self):
        client = MagicMock()
        client.llm_model = "deepseek-chat"
        engine = ConstrainedDecodingEngine(client)
        data = {
            "selected_nanozyme": {"name": "Fe3O4"},
            "main_activity": {
                "enzyme_like_type": "POD-like",
                "kinetics": {},
                "kinetics_list": [],
            },
            "applications": [],
        }
        result = engine._validate_and_fix(data, "kinetics")
        assert result["main_activity"]["enzyme_like_type"] == "peroxidase-like"

    def test_fix_numeric_string_to_float(self):
        client = MagicMock()
        client.llm_model = "deepseek-chat"
        engine = ConstrainedDecodingEngine(client)
        data = {
            "selected_nanozyme": {"name": "Fe3O4"},
            "main_activity": {
                "enzyme_like_type": "peroxidase-like",
                "kinetics": {"Km": "0.5", "Km_unit": "mM"},
                "kinetics_list": [],
            },
            "applications": [],
        }
        result = engine._validate_and_fix(data, "kinetics")
        assert isinstance(result["main_activity"]["kinetics"]["Km"], float)
        assert result["main_activity"]["kinetics"]["Km"] == 0.5


class TestCallWithFallback:
    @pytest.mark.asyncio
    async def test_call_with_json_schema_mode(self):
        client = MagicMock()
        client.llm_model = "deepseek-chat"
        client.chat_completion_text = AsyncMock(return_value='{"enzyme_like_type": "peroxidase-like"}')
        engine = ConstrainedDecodingEngine(client)
        result = await engine.call(
            messages=[{"role": "user", "content": "test"}],
            task_name="enzyme_type",
        )
        assert result is not None
        call_kwargs = client.chat_completion_text.call_args
        assert call_kwargs is not None

    @pytest.mark.asyncio
    async def test_call_fallback_to_json_object(self):
        client = MagicMock()
        client.llm_model = "Qwen/Qwen2.5-VL-72B-Instruct"
        client.chat_completion_text = AsyncMock(return_value='{"enzyme_like_type": "peroxidase-like"}')
        engine = ConstrainedDecodingEngine(client)
        result = await engine.call(
            messages=[{"role": "user", "content": "test"}],
            task_name="enzyme_type",
        )
        assert result is not None
        assert engine.supports_json_schema is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_constrained_decoding.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'constrained_decoding')

- [ ] **Step 3: 实现ConstrainedDecodingEngine**

创建 `constrained_decoding.py`：

```python
import json
import logging
from typing import Dict, List, Any, Optional

from schema_constraints import (
    TASK_SCHEMAS,
    NANOZYME_EXTRACTION_SCHEMA,
    validate_against_schema,
    auto_fix_schema_errors,
    _ENZYME_TYPE_ENUM,
    _APPLICATION_TYPE_ENUM,
    get_task_schema_for_openai,
)
from dependencies import is_available as _dep_available

logger = logging.getLogger(__name__)

SUPPORTED_JSON_SCHEMA_PREFIXES = [
    "gpt-4o", "gpt-4-turbo",
    "deepseek-chat", "deepseek-reasoner",
    "glm-4", "glm-4-plus",
]

_SCHEMA_CONSTRAINT_TEMPLATE = """<schema_constraints>
Output a JSON object strictly conforming to this schema:
- enzyme_like_type: must be one of [{enzyme_enum}]
- application_type: must be one of [{app_enum}]
- All numeric fields (Km, Vmax, kcat, size, detection_limit, etc.) must be numbers or null, never strings
- size must be paired with size_unit; Km with Km_unit; Vmax with Vmax_unit
- Required top-level fields: selected_nanozyme (with name), main_activity
- Do NOT include any fields not in the schema
- Use null for missing values, do not omit fields
</schema_constraints>"""


class ConstrainedDecodingEngine:
    def __init__(self, client, config=None):
        self.client = client
        self.config = config
        self.model = getattr(client, "llm_model", "") if client else ""
        self.temperature = getattr(config, "temperature", 0.0) if config else 0.0
        self.max_tokens = getattr(config, "max_tokens", 4096) if config else 4096
        self.supports_json_schema = self._detect_json_schema_support()

    def _detect_json_schema_support(self) -> bool:
        model_lower = self.model.lower()
        return any(model_lower.startswith(prefix) for prefix in SUPPORTED_JSON_SCHEMA_PREFIXES)

    async def call(
        self,
        messages: List[Dict],
        task_name: str,
        schema: Optional[Dict] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.client:
            logger.warning(f"[CDE] No client available for {task_name}")
            return None

        task_schema = schema or TASK_SCHEMAS.get(task_name, NANOZYME_EXTRACTION_SCHEMA)
        enhanced_messages = self._inject_schema_prompt(messages, task_name, task_schema)

        temp = temperature if temperature is not None else self.temperature
        mtokens = max_tokens if max_tokens is not None else self.max_tokens

        if self.supports_json_schema and task_schema:
            result = await self._call_with_json_schema(enhanced_messages, task_name, task_schema, temp, mtokens)
        else:
            result = await self._call_with_json_object(enhanced_messages, task_name, temp, mtokens)

        if result and task_schema:
            result = self._validate_and_fix(result, task_name)

        return result

    def _inject_schema_prompt(
        self,
        messages: List[Dict],
        task_name: str,
        schema: Optional[Dict],
    ) -> List[Dict]:
        constraint_text = _SCHEMA_CONSTRAINT_TEMPLATE.format(
            enzyme_enum=" | ".join(_ENZYME_TYPE_ENUM[:10]) + " | ...",
            app_enum=" | ".join(_APPLICATION_TYPE_ENUM),
        )

        enhanced = list(messages)

        system_idx = None
        for i, msg in enumerate(enhanced):
            if msg.get("role") == "system":
                system_idx = i
                break

        if system_idx is not None:
            enhanced[system_idx] = {
                "role": "system",
                "content": enhanced[system_idx]["content"] + "\n\n" + constraint_text,
            }
        else:
            enhanced.insert(0, {
                "role": "system",
                "content": constraint_text,
            })

        return enhanced

    async def _call_with_json_schema(
        self,
        messages: List[Dict],
        task_name: str,
        schema: Dict,
        temperature: float,
        max_tokens: int,
    ) -> Optional[Dict[str, Any]]:
        try:
            response_format = get_task_schema_for_openai(task_name)
            extra_params = {"response_format": response_format}

            content = await self.client.chat_completion_text(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_params=extra_params,
            )

            if not content:
                logger.warning(f"[CDE] Empty response for {task_name} (json_schema mode)")
                return await self._call_with_json_object(messages, task_name, temperature, max_tokens)

            parsed = self._parse_json(content)
            if parsed is not None:
                logger.info(f"[CDE] {task_name} succeeded (json_schema mode)")
                return parsed

            logger.warning(f"[CDE] JSON parse failed for {task_name} (json_schema mode), falling back")
            return await self._call_with_json_object(messages, task_name, temperature, max_tokens)

        except Exception as e:
            logger.warning(f"[CDE] json_schema mode failed for {task_name}: {e}, falling back to json_object")
            return await self._call_with_json_object(messages, task_name, temperature, max_tokens)

    async def _call_with_json_object(
        self,
        messages: List[Dict],
        task_name: str,
        temperature: float,
        max_tokens: int,
    ) -> Optional[Dict[str, Any]]:
        try:
            extra_params = {"response_format": {"type": "json_object"}}

            content = await self.client.chat_completion_text(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_params=extra_params,
            )

            if not content:
                logger.warning(f"[CDE] Empty response for {task_name} (json_object mode)")
                return None

            parsed = self._parse_json(content)
            if parsed is not None:
                logger.info(f"[CDE] {task_name} succeeded (json_object mode)")
                return parsed

            logger.warning(f"[CDE] JSON parse failed for {task_name}: {content[:200]}")
            return None

        except Exception as e:
            logger.error(f"[CDE] {task_name} failed: {e}")
            return None

    def _validate_and_fix(self, data: Dict[str, Any], task_name: str) -> Dict[str, Any]:
        errors = validate_against_schema(data)
        if errors:
            logger.warning(f"[CDE] Schema validation errors for {task_name}: {errors}")
            data = auto_fix_schema_errors(data, errors)

            remaining = validate_against_schema(data)
            if remaining:
                logger.warning(f"[CDE] Unfixable schema errors for {task_name}: {remaining}")

        return data

    @staticmethod
    def _parse_json(content: str) -> Optional[Dict[str, Any]]:
        import re
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

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_constrained_decoding.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add constrained_decoding.py tests/test_constrained_decoding.py
git commit -m "feat(constrained-decoding): 新增ConstrainedDecodingEngine核心实现"
```

---

### Task 3: 修改api_client.py支持response_format透传

**Files:**
- Modify: `api_client.py`

- [ ] **Step 1: 在APIClient中新增supports_json_schema方法**

在 `api_client.py` 的 `APIClient` 类中，`chat_completion_text` 方法之前添加：

```python
    def supports_json_schema(self) -> bool:
        from constrained_decoding import SUPPORTED_JSON_SCHEMA_PREFIXES
        model_lower = self.llm_model.lower()
        return any(model_lower.startswith(prefix) for prefix in SUPPORTED_JSON_SCHEMA_PREFIXES)
```

- [ ] **Step 2: 确认chat_completion_text的extra_params已正确透传response_format**

当前 `chat_completion_text` 已支持 `extra_params` 透传到 `data.update(extra_params)`，其中 `response_format` 会被正确传入。无需额外修改，仅验证。

- [ ] **Step 3: 运行现有测试确认不破坏**

Run: `python -m pytest tests/ -v -k "not pipeline" --timeout=30`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add api_client.py
git commit -m "feat(api-client): 新增supports_json_schema检测方法"
```

---

### Task 4: 改造llm_structured_extractor.py使用ConstrainedDecodingEngine

**Files:**
- Modify: `llm_structured_extractor.py`

- [ ] **Step 1: 替换_call_llm_structured方法，使用ConstrainedDecodingEngine**

将 `llm_structured_extractor.py` 的 `__init__` 和 `_call_llm_structured` 方法替换为：

在 `__init__` 中，替换 `self.enable_constrained_output` 相关行为，新增 `self.engine`：

```python
    def __init__(self, client, config=None):
        self.client = client
        self.config = config
        self.model = getattr(config, "llm_model", "gpt-4o") if config else "gpt-4o"
        self.temperature = 0.0
        self.max_tokens = 4096
        self.enable_self_augmentation = getattr(config, "enable_self_augmentation", True) if config else True
        self.enable_constrained_output = getattr(config, "enable_constrained_output", True) if config else True
        self.enable_verification = getattr(config, "enable_verification", True) if config else True
        self.max_verification_rounds = getattr(config, "max_verification_rounds", 1) if config else 1
        self._engine = None
```

新增 `_get_engine` 方法：

```python
    def _get_engine(self):
        if self._engine is None:
            from constrained_decoding import ConstrainedDecodingEngine
            self._engine = ConstrainedDecodingEngine(self.client, self.config)
        return self._engine
```

替换 `_call_llm_structured` 方法：

```python
    async def _call_llm_structured(
        self,
        messages: List[Dict[str, str]],
        task_name: str,
        response_model=None,
    ) -> Optional[Dict[str, Any]]:
        if not self.client:
            logger.warning(f"[LLM-Ext] No client available for {task_name}")
            return None

        if self.enable_constrained_output:
            engine = self._get_engine()
            result = await engine.call(
                messages=messages,
                task_name=task_name,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            if result is not None:
                logger.info(f"[LLM-Ext] {task_name} extraction succeeded (constrained mode)")
                return result

        try:
            content = await self.client.chat_completion_text(
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            if not content:
                logger.warning(f"[LLM-Ext] Empty response for {task_name}")
                return None

            parsed = self._parse_json_response(content)
            if parsed is None:
                logger.warning(f"[LLM-Ext] Failed to parse JSON for {task_name}: {content[:200]}")
                return None

            logger.info(f"[LLM-Ext] {task_name} extraction succeeded")
            return parsed

        except Exception as e:
            logger.error(f"[LLM-Ext] {task_name} extraction failed: {e}")
            return None
```

- [ ] **Step 2: 移除_call_with_instructor方法和_get_kinetics_model方法**

删除 `_call_with_instructor` 方法（约30行）和 `_get_kinetics_model` 方法（约5行），因为约束解码引擎已替代其功能。

同时移除 `from dependencies import is_available as _dep_available` 导入（如果不再被其他地方使用）。

- [ ] **Step 3: 更新extract_kinetics调用，移除response_model参数**

将 `extract_kinetics` 中的：
```python
result = await self._call_llm_structured(messages, "kinetics", response_model=self._get_kinetics_model())
```
替换为：
```python
result = await self._call_llm_structured(messages, "kinetics")
```

- [ ] **Step 4: 运行现有测试确认不破坏**

Run: `python -m pytest tests/test_llm_structured_extractor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add llm_structured_extractor.py
git commit -m "refactor(llm-structured): 使用ConstrainedDecodingEngine替代instructor模式"
```

---

### Task 5: 改造llm_extractor.py启用约束解码

**Files:**
- Modify: `llm_extractor.py`

- [ ] **Step 1: 在LLMExtractor中集成ConstrainedDecodingEngine**

在 `LLMExtractor.__init__` 中添加引擎初始化：

```python
    def __init__(self, client: APIClient, batch_size: int = 5):
        self.client = client
        self.batch_size = batch_size
        self.json_fixer = JSONFixer()
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            from constrained_decoding import ConstrainedDecodingEngine
            self._engine = ConstrainedDecodingEngine(self.client)
        return self._engine
```

- [ ] **Step 2: 修改extract_single_chunk使用约束解码**

在 `extract_single_chunk` 方法中，将API调用部分替换为使用约束解码引擎。找到 `response = await self.client.chat_completion_text(...)` 调用，替换为：

```python
            engine = self._get_engine()
            response = await engine.call(
                messages=messages,
                task_name="full_extraction",
                temperature=0.1,
                max_tokens=8192,
            )

            if response is None:
                logger.warning(f"[LLM] {chunk_label}: API 返回空响应")
                return None

            logger.info(f"[LLM] {chunk_label} 约束解码提取成功")
            result = response
            result = self._ensure_candidate_structure(result)
            logger.info(
                f"[LLM] {chunk_label} 提取到字段: {list(result.keys())}"
            )
            return result
```

注意：由于 `engine.call` 已返回解析后的dict，不再需要 `_robust_json_parse` 步骤。但保留 `_robust_json_parse` 作为fallback路径。

- [ ] **Step 3: 保留原有JSON解析作为fallback**

在 `extract_single_chunk` 中，如果约束解码返回None，fallback到原有的纯文本+JSON解析路径：

```python
            engine = self._get_engine()
            constrained_result = await engine.call(
                messages=messages,
                task_name="full_extraction",
                temperature=0.1,
                max_tokens=8192,
            )

            if constrained_result is not None:
                constrained_result = self._ensure_candidate_structure(constrained_result)
                logger.info(f"[LLM] {chunk_label} 约束解码提取成功，字段: {list(constrained_result.keys())}")
                return constrained_result

            logger.info(f"[LLM] {chunk_label} 约束解码返回空，fallback到文本解析")
            response = await self.client.chat_completion_text(
                messages,
                temperature=0.1,
                max_tokens=8192
            )

            if not response:
                logger.warning(f"[LLM] {chunk_label}: API 返回空响应")
                return None

            logger.info(f"[LLM] API 响应长度: {len(response)} 字符")
            result = self._robust_json_parse(response)
            if result:
                result = self._ensure_candidate_structure(result)
                logger.info(
                    f"[LLM] {chunk_label} JSON 解析成功，"
                    f"提取到字段: {list(result.keys())}"
                )
                return result
```

- [ ] **Step 4: 运行现有测试确认不破坏**

Run: `python -m pytest tests/ -v -k "not pipeline" --timeout=30`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add llm_extractor.py
git commit -m "feat(llm-extractor): 全文提取启用约束解码引擎"
```

---

### Task 6: 改造extraction_agents.py接入ConstrainedDecodingEngine

**Files:**
- Modify: `extraction_agents.py`

- [ ] **Step 1: 在RuleExtractorAdapter中集成ConstrainedDecodingEngine**

`extraction_agents.py` 中的4个Agent（KineticsAgent、MorphologyAgent、SynthesisAgent、ApplicationAgent）主要是基于正则的规则提取器，不直接调用LLM。只有 `RuleExtractorAdapter` 可能间接使用LLM。

检查 `RuleExtractorAdapter` 是否有LLM调用。如果没有直接的LLM调用，则不需要修改此文件。

- [ ] **Step 2: 确认extraction_agents.py无直接LLM调用后跳过**

经分析，`extraction_agents.py` 中的4个Agent全部基于正则模式提取，不调用LLM API。`RuleExtractorAdapter` 也是编排正则Agent的适配器，无LLM调用。

因此此Task无需代码修改，仅确认即可。

- [ ] **Step 3: Commit（如有修改）**

无需commit。

---

### Task 7: 端到端集成测试

**Files:**
- Test: `tests/test_constrained_decoding.py`

- [ ] **Step 1: 编写集成测试——ConstrainedDecodingEngine与LLMStructuredExtractor协作**

在 `tests/test_constrained_decoding.py` 中追加：

```python
class TestIntegrationWithStructuredExtractor:
    @pytest.mark.asyncio
    async def test_extract_kinetics_uses_constrained_decoding(self):
        from unittest.mock import AsyncMock, MagicMock, patch
        from llm_structured_extractor import LLMStructuredExtractor

        client = MagicMock()
        client.llm_model = "deepseek-chat"
        client.chat_completion_text = AsyncMock(
            return_value='{"kinetics": {"Km": 0.5, "Km_unit": "mM", "Vmax": 12.3, "Vmax_unit": "μM/s"}, "kinetics_list": []}'
        )
        config = MagicMock()
        config.llm_model = "deepseek-chat"
        config.enable_constrained_output = True
        config.enable_self_augmentation = False
        config.enable_verification = False

        extractor = LLMStructuredExtractor(client, config)
        with patch('extraction_prompts.build_kinetics_prompt', return_value=[{"role": "user", "content": "test"}]):
            result = await extractor.extract_kinetics("Fe3O4", ["test text"])

        assert result is not None
        assert "kinetics" in result

    @pytest.mark.asyncio
    async def test_extract_enzyme_type_uses_constrained_decoding(self):
        from unittest.mock import AsyncMock, MagicMock, patch
        from llm_structured_extractor import LLMStructuredExtractor

        client = MagicMock()
        client.llm_model = "deepseek-chat"
        client.chat_completion_text = AsyncMock(
            return_value='{"enzyme_like_type": "peroxidase-like"}'
        )
        config = MagicMock()
        config.llm_model = "deepseek-chat"
        config.enable_constrained_output = True
        config.enable_self_augmentation = False
        config.enable_verification = False

        extractor = LLMStructuredExtractor(client, config)
        with patch('extraction_prompts.build_enzyme_type_prompt', return_value=[{"role": "user", "content": "test"}]):
            result = await extractor.extract_enzyme_type("Fe3O4", ["test text"])

        assert result == "peroxidase-like"
```

- [ ] **Step 2: 运行全部测试**

Run: `python -m pytest tests/test_constrained_decoding.py tests/test_llm_structured_extractor.py tests/test_schema_constraints.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_constrained_decoding.py
git commit -m "test(constrained-decoding): 新增集成测试"
```

---

### Task 8: 更新MODULE_MAP和迭代记录

**Files:**
- Modify: `.trae/rules/MODULE_MAP.md`
- Create: `docs/iteration_logs/2026-05-13_constrained-decoding-engine.md`

- [ ] **Step 1: 更新MODULE_MAP.md**

在提取引擎层表格中添加 `constrained_decoding.py` 条目：

```
| `constrained_decoding.py` | `ConstrainedDecodingEngine`, `SUPPORTED_JSON_SCHEMA_PREFIXES` | 多层约束解码引擎：API原生json_schema → json_object+Prompt注入 → Pydantic后验证+auto_fix | api_client, schema_constraints, nanozyme_models |
```

在 `llm_structured_extractor.py` 的关键依赖列中添加 `constrained_decoding`。

在 `llm_extractor.py` 的关键依赖列中添加 `constrained_decoding`。

- [ ] **Step 2: 创建迭代记录**

创建 `docs/iteration_logs/2026-05-13_constrained-decoding-engine.md`：

```markdown
# 约束解码引擎实现

## 更新时间
2026-05-13

## 更新类型
- 功能开发

## 背景
基于研究报告《AI/LLM驱动的科学文献提取前沿与系统演进》的核心差距分析，系统缺乏约束解码机制，当前依赖JSON mode + Pydantic后验证，结构合规率约92%。

## 改动内容
- 新增 `constrained_decoding.py`：ConstrainedDecodingEngine核心实现
  - 4层约束策略：API原生json_schema → json_object+Prompt注入 → Pydantic后验证 → Schema感知Prompt增强
  - 模型能力自动检测（DeepSeek/GLM/GPT-4o支持json_schema）
  - 自动降级fallback
- 修改 `schema_constraints.py`：
  - 完善主Schema（additionalProperties/required/enum）
  - 新增6个子任务Schema（kinetics/morphology/application/enzyme_type/synthesis/ph_temp）
  - 新增TASK_SCHEMAS注册表
  - 增强auto_fix_schema_errors（枚举归一化、数值字符串修复、未知字段移除）
- 修改 `api_client.py`：新增supports_json_schema()检测方法
- 修改 `llm_structured_extractor.py`：使用ConstrainedDecodingEngine替代instructor模式
- 修改 `llm_extractor.py`：全文提取启用约束解码

## 未改动内容
- extraction_prompts.py：现有prompt模板不变
- extraction_agents.py：基于正则的Agent无LLM调用，无需修改
- vlm_extractor.py：VLM提取暂不纳入约束解码
- cross_validation_agent.py / consistency_agent.py / numeric_validator.py：验证层不变

## 验证方式
- 单元测试：tests/test_constrained_decoding.py 全部通过
- 集成测试：LLMStructuredExtractor + ConstrainedDecodingEngine 协作测试通过
- 回归测试：现有测试全部通过

## 风险与后续
- 部分国产模型可能不支持json_schema，需要实际测试
- 后续可将VLM提取也纳入约束解码
- 后续可引入领域微调（报告阶段一原计划第二部分）
```

- [ ] **Step 3: Commit**

```bash
git add .trae/rules/MODULE_MAP.md docs/iteration_logs/2026-05-13_constrained-decoding-engine.md
git commit -m "docs: 更新MODULE_MAP和迭代记录（约束解码引擎）"
```
