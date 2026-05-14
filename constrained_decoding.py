import json
import logging
import re
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
            logger.warning("[CDE] No client available for %s", task_name)
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
            if response_format is None:
                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": task_name,
                        "strict": True,
                        "schema": schema,
                    }
                }
            extra_params = {"response_format": response_format}

            content = await self.client.chat_completion_text(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_params=extra_params,
            )

            if not content:
                logger.warning("[CDE] Empty response for %s (json_schema mode)", task_name)
                return await self._call_with_json_object(messages, task_name, temperature, max_tokens)

            parsed = self._parse_json(content)
            if parsed is not None:
                logger.info("[CDE] %s succeeded (json_schema mode)", task_name)
                return parsed

            logger.warning("[CDE] JSON parse failed for %s (json_schema mode), falling back", task_name)
            return await self._call_with_json_object(messages, task_name, temperature, max_tokens)

        except Exception as e:
            logger.warning("[CDE] json_schema mode failed for %s: %s, falling back to json_object", task_name, e)
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
                logger.warning("[CDE] Empty response for %s (json_object mode)", task_name)
                return None

            parsed = self._parse_json(content)
            if parsed is not None:
                logger.info("[CDE] %s succeeded (json_object mode)", task_name)
                return parsed

            logger.warning("[CDE] JSON parse failed for %s: %s", task_name, content[:200])
            return None

        except Exception as e:
            logger.error("[CDE] %s failed: %s", task_name, e)
            return None

    def _validate_and_fix(self, data: Dict[str, Any], task_name: str) -> Optional[Dict[str, Any]]:
        from schema_constraints import _fix_numeric_strings, _fix_enum_values, _remove_unknown_fields

        data = _fix_numeric_strings(data)

        task_schema = TASK_SCHEMAS.get(task_name)

        if task_schema is not None:
            data = _fix_enum_values(data, task_schema)
            data = _remove_unknown_fields(data, task_schema)
        else:
            data = _remove_unknown_fields(data, NANOZYME_EXTRACTION_SCHEMA)
            data = _fix_enum_values(data, NANOZYME_EXTRACTION_SCHEMA)

            errors = validate_against_schema(data)
            if errors:
                logger.warning("[CDE] Schema validation errors for %s: %s", task_name, errors)
                data = auto_fix_schema_errors(data, errors)

                remaining = validate_against_schema(data)
                if remaining:
                    logger.warning("[CDE] Unfixable schema errors for %s: %s", task_name, remaining)

        return data

    @staticmethod
    def _parse_json(content: str) -> Optional[Dict[str, Any]]:
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
