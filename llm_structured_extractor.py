import json
import logging
import re
from typing import Dict, List, Any, Optional

from extraction_prompts import (
    build_kinetics_prompt,
    build_morphology_prompt,
    build_application_prompt,
    build_enzyme_type_prompt,
    build_self_augmentation_prompt,
    build_table_kinetics_prompt,
    build_verification_prompt,
    build_synthesis_prompt,
    build_ph_temp_prompt,
)
from schema_constraints import validate_against_schema, auto_fix_schema_errors
from dependencies import is_available as _dep_available

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
        self.enable_verification = getattr(config, "enable_verification", True) if config else True
        self.max_verification_rounds = getattr(config, "max_verification_rounds", 1) if config else 1

    async def extract_kinetics(
        self,
        nanozyme_name: str,
        text_chunks: List[str],
        table_texts: List[str] = None,
    ) -> Dict[str, Any]:
        combined_text = self._prepare_text(text_chunks, max_chars=6000)
        if table_texts:
            table_combined = "\n\n[Table data]:\n" + "\n".join(table_texts[:5])
            combined_text += table_combined[:3000]

        messages = build_kinetics_prompt(nanozyme_name, combined_text)
        result = await self._call_llm_structured(messages, "kinetics", response_model=self._get_kinetics_model())

        if self.enable_self_augmentation and result:
            augmented = await self._self_augment(result, combined_text, "kinetics")
            if augmented:
                result = augmented

        if result:
            result = self._post_process_kinetics(result)

        if result and self.enable_verification:
            result = await self._verify_and_correct(nanozyme_name, combined_text, result, "kinetics")

        if table_texts:
            table_result = await self.extract_from_table(nanozyme_name, table_texts)
            if table_result:
                result = self._merge_kinetics_results(result if result else {}, table_result)

        return result if result else {}

    async def extract_from_table(
        self,
        nanozyme_name: str,
        table_texts: List[str],
    ) -> Dict[str, Any]:
        if not table_texts:
            return {}

        prepared_tables = self._prepare_table_text(table_texts, max_chars=8000)
        messages = build_table_kinetics_prompt(nanozyme_name, prepared_tables)
        result = await self._call_llm_structured(messages, "table_kinetics")

        if result:
            result = self._post_process_kinetics(result)

        return result if result else {}

    def _prepare_table_text(self, tables: List[str], max_chars: int = 8000) -> str:
        if not tables:
            return ""
        combined = "\n\n".join(tables)
        if len(combined) <= max_chars:
            return combined

        lines = combined.split("\n")
        header_lines = []
        keyword_lines = []
        other_lines = []

        km_vmax_keywords = ["km", "vmax", "kcat", "michaelis", "turnover", "kinetic"]

        for i, line in enumerate(lines):
            lower = line.lower()
            if i < 3 or lower.startswith("|") and i < 5:
                header_lines.append(line)
            elif any(kw in lower for kw in km_vmax_keywords):
                keyword_lines.append(line)
            else:
                other_lines.append(line)

        result_lines = header_lines + keyword_lines
        current_len = sum(len(l) + 1 for l in result_lines)

        for line in other_lines:
            if current_len + len(line) + 1 > max_chars:
                break
            result_lines.append(line)
            current_len += len(line) + 1

        return "\n".join(result_lines)

    def _merge_kinetics_results(self, text_result: Dict[str, Any], table_result: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(text_result)

        text_kin = merged.get("kinetics", {})
        table_kin = table_result.get("kinetics", {})

        for key in ["Km", "Km_unit", "Vmax", "Vmax_unit", "kcat", "kcat_unit", "kcat_Km", "kcat_Km_unit", "substrate", "detection_method", "material_variant"]:
            if text_kin.get(key) is None and table_kin.get(key) is not None:
                if "kinetics" not in merged or not isinstance(merged["kinetics"], dict):
                    merged["kinetics"] = {}
                merged["kinetics"][key] = table_kin[key]

        text_list = merged.get("kinetics_list", [])
        table_list = table_result.get("kinetics_list", [])

        existing_substrate_material = set()
        for kl in text_list:
            if isinstance(kl, dict):
                key = (kl.get("substrate", ""), kl.get("material_variant", ""))
                existing_substrate_material.add(key)

        for kl in table_list:
            if isinstance(kl, dict):
                key = (kl.get("substrate", ""), kl.get("material_variant", ""))
                if key not in existing_substrate_material:
                    text_list.append(kl)
                    existing_substrate_material.add(key)

        merged["kinetics_list"] = text_list
        return merged

    async def extract_morphology(
        self,
        nanozyme_name: str,
        text_chunks: List[str],
    ) -> Dict[str, Any]:
        combined_text = self._prepare_text(text_chunks, max_chars=4000)
        messages = build_morphology_prompt(nanozyme_name, combined_text)
        result = await self._call_llm_structured(messages, "morphology")
        return result if result else {}

    async def extract_applications(
        self,
        nanozyme_name: str,
        text_chunks: List[str],
    ) -> Dict[str, Any]:
        combined_text = self._prepare_text(text_chunks, max_chars=4000)
        messages = build_application_prompt(nanozyme_name, combined_text)
        result = await self._call_llm_structured(messages, "applications")
        return result if result else {}

    async def extract_enzyme_type(
        self,
        nanozyme_name: str,
        text_chunks: List[str],
    ) -> Optional[str]:
        combined_text = self._prepare_text(text_chunks, max_chars=3000)
        messages = build_enzyme_type_prompt(nanozyme_name, combined_text)
        result = await self._call_llm_structured(messages, "enzyme_type")
        if result and isinstance(result, dict):
            return result.get("enzyme_like_type")
        return None

    async def extract_synthesis(
        self,
        nanozyme_name: str,
        text_chunks: List[str],
    ) -> Dict[str, Any]:
        combined_text = self._prepare_text(text_chunks, max_chars=4000)
        messages = build_synthesis_prompt(nanozyme_name, combined_text)
        result = await self._call_llm_structured(messages, "synthesis")
        return result if result else {}

    async def extract_ph_temp(
        self,
        nanozyme_name: str,
        text_chunks: List[str],
    ) -> Dict[str, Any]:
        combined_text = self._prepare_text(text_chunks, max_chars=3000)
        messages = build_ph_temp_prompt(nanozyme_name, combined_text)
        result = await self._call_llm_structured(messages, "ph_temp")
        return result if result else {}

    async def extract_all(
        self,
        nanozyme_name: str,
        buckets: Dict[str, List[str]],
        table_texts: List[str] = None,
    ) -> Dict[str, Any]:
        result = {}

        etype = await self.extract_enzyme_type(
            nanozyme_name,
            buckets.get("activity", []) + buckets.get("mechanism", []) + buckets.get("abstract", [])
        )
        result["enzyme_like_type"] = etype

        kinetics = await self.extract_kinetics(
            nanozyme_name,
            buckets.get("kinetics", []) + buckets.get("activity", []),
            table_texts,
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

        synthesis = await self.extract_synthesis(
            nanozyme_name,
            buckets.get("material", []) + buckets.get("synthesis", [])
        )
        if synthesis:
            if "synthesis_method" in synthesis and not result.get("synthesis_method"):
                result["synthesis_method"] = synthesis["synthesis_method"]
            if "synthesis_conditions" in synthesis and not result.get("synthesis_conditions"):
                result["synthesis_conditions"] = synthesis["synthesis_conditions"]
            if "characterization" in synthesis and not result.get("characterization"):
                result["characterization"] = synthesis["characterization"]

        ph_temp = await self.extract_ph_temp(
            nanozyme_name,
            buckets.get("activity", []) + buckets.get("kinetics", [])
        )
        if ph_temp:
            if "pH_profile" in ph_temp and not result.get("pH_profile"):
                result["pH_profile"] = ph_temp["pH_profile"]
            if "temperature_profile" in ph_temp and not result.get("temperature_profile"):
                result["temperature_profile"] = ph_temp["temperature_profile"]

        errors = validate_against_schema(result)
        if errors:
            logger.warning(f"[LLM-Ext] Schema validation errors: {errors}")
            result = auto_fix_schema_errors(result, errors)

        return result

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
            extra_params = {}
            if self.enable_constrained_output:
                extra_params["response_format"] = {"type": "json_object"}

            content = await self.client.chat_completion_text(
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                extra_params=extra_params if extra_params else None,
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

    def _get_engine(self):
        if not hasattr(self, '_engine') or self._engine is None:
            from constrained_decoding import ConstrainedDecodingEngine
            self._engine = ConstrainedDecodingEngine(self.client, self.config)
        return self._engine

    async def _call_with_instructor(
        self,
        messages: List[Dict[str, str]],
        task_name: str,
        response_model,
    ) -> Optional[Dict[str, Any]]:
        try:
            import instructor
            from openai import AsyncOpenAI

            openai_client = AsyncOpenAI(
                api_key=self.client.llm_api_key,
                base_url=self.client.llm_base_url,
            )
            inst_client = instructor.from_openai(openai_client)

            result = await inst_client.chat.completions.create(
                model=self.client.llm_model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_model=response_model,
            )

            logger.info(f"[LLM-Ext] {task_name} extraction succeeded (instructor mode)")
            return result.model_dump() if hasattr(result, "model_dump") else result

        except Exception as e:
            logger.warning(f"[LLM-Ext] Instructor mode failed for {task_name}: {e}, falling back to JSON mode")
            return None

    def _get_kinetics_model(self):
        from schema_constraints import NanozymeExtractionModel, PYDANTIC_AVAILABLE
        if PYDANTIC_AVAILABLE:
            return NanozymeExtractionModel
        return None

    async def _verify_and_correct(
        self,
        nanozyme_name: str,
        text: str,
        result: Dict[str, Any],
        task_name: str,
    ) -> Dict[str, Any]:
        if not self.enable_verification or not self.client:
            return result

        for round_num in range(self.max_verification_rounds):
            result_str = json.dumps(result, ensure_ascii=False, indent=2)
            messages = build_verification_prompt(nanozyme_name, text, result_str)
            verification = await self._call_llm_structured(messages, f"{task_name}_verify_r{round_num+1}")

            if not verification:
                logger.info(f"[LLM-Ext] Verification round {round_num+1} returned no result, keeping original")
                break

            if not verification.get("has_errors", False):
                logger.info(f"[LLM-Ext] Verification round {round_num+1}: no errors found")
                break

            errors = verification.get("errors_found", [])
            logger.info(f"[LLM-Ext] Verification round {round_num+1}: found {len(errors)} errors: {errors}")

            corrected = verification.get("corrected_result")
            if corrected and isinstance(corrected, dict):
                result = corrected
                logger.info(f"[LLM-Ext] Applied corrections from verification round {round_num+1}")
            else:
                logger.warning(f"[LLM-Ext] Verification found errors but no corrected_result provided")
                break

        return result

    async def _self_augment(
        self,
        previous_result: Dict[str, Any],
        text: str,
        task_name: str,
    ) -> Optional[Dict[str, Any]]:
        messages = build_self_augmentation_prompt(
            json.dumps(previous_result, ensure_ascii=False, indent=2),
            text,
        )
        augmented = await self._call_llm_structured(messages, f"{task_name}_augmented")
        if augmented:
            logger.info(f"[LLM-Ext] Self-augmentation improved {task_name}")
        return augmented

    def _post_process_kinetics(self, result: Dict[str, Any]) -> Dict[str, Any]:
        kin = result.get("kinetics", {})
        if isinstance(kin, dict):
            self._fix_vmax_unit(kin)
            self._fix_km_magnitude(kin)

        for kl in result.get("kinetics_list", []):
            if not isinstance(kl, dict):
                continue
            self._fix_vmax_unit(kl)
            self._fix_km_magnitude(kl)

        return result

    def _fix_vmax_unit(self, kin_dict: Dict[str, Any]) -> None:
        vmax_val = kin_dict.get("Vmax")
        vmax_u = kin_dict.get("Vmax_unit", "")
        if not isinstance(vmax_val, (int, float)):
            return

        if vmax_u in ("M/s", "M·s-1", "M s^-1") and abs(vmax_val) < 1.0:
            kin_dict["Vmax"] = vmax_val * 1e6
            kin_dict["Vmax_unit"] = "μM/s"
            logger.info(f"[LLM-Ext] Auto-converted Vmax {vmax_val} M/s -> {vmax_val*1e6} μM/s")
        elif vmax_u in ("mM/s", "mM·s-1") and abs(vmax_val) < 1.0:
            kin_dict["Vmax"] = vmax_val * 1e3
            kin_dict["Vmax_unit"] = "μM/s"
            logger.info(f"[LLM-Ext] Auto-converted Vmax {vmax_val} mM/s -> {vmax_val*1e3} μM/s")

    def _fix_km_magnitude(self, kin_dict: Dict[str, Any]) -> None:
        km_val = kin_dict.get("Km")
        km_u = kin_dict.get("Km_unit", "")
        if isinstance(km_val, (int, float)) and km_u == "M" and km_val > 1.0:
            kin_dict["Km"] = None
            kin_dict["Km_unit"] = None
            logger.warning(f"[LLM-Ext] Cleared unrealistic Km={km_val} M")
        elif isinstance(km_val, (int, float)) and km_u == "mM" and km_val > 1000:
            kin_dict["Km"] = None
            kin_dict["Km_unit"] = None
            logger.warning(f"[LLM-Ext] Cleared unrealistic Km={km_val} mM")

    def _prepare_text(self, chunks: List[str], max_chars: int = 6000) -> str:
        if not chunks:
            return ""
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

        content = self._pre_clean_json(content)

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                cleaned = self._fix_json_string(json_match.group())
                if cleaned:
                    try:
                        return json.loads(cleaned)
                    except json.JSONDecodeError:
                        pass

        return None

    @staticmethod
    def _pre_clean_json(text: str) -> str:
        t = text
        t = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', t)
        t = t.replace('\u00b5', '\u03bc')
        t = re.sub(r',\s*([}\]])', r'\1', t)
        t = re.sub(r'"\s*\n\s*"', '" "', t)
        return t

    @staticmethod
    def _fix_json_string(s: str) -> Optional[str]:
        try:
            fixed = s
            fixed = re.sub(r'(?<=[\w\s])\s*"\s*:\s*(?![\s{\["\d\-tnf])', '": "', fixed)
            fixed = re.sub(r'(?<=[\]}])\s*,\s*([}\]])', r'\1', fixed)
            fixed = re.sub(r'\\(?!["\\/bfnrtu])', '', fixed)
            if not fixed.endswith('}'):
                open_braces = fixed.count('{') - fixed.count('}')
                if open_braces > 0:
                    fixed += '}' * open_braces
            return fixed
        except Exception:
            return None
