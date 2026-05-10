import json
import logging
import re
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

MATERIAL_IDENTIFICATION_SYSTEM_PROMPT = """You are an expert at identifying the PRIMARY nanozyme material from scientific literature about nanozymes (nanomaterials with enzyme-like catalytic activity).

CRITICAL DISTINCTIONS:
1. The PRIMARY nanozyme is the material that the paper focuses on — usually mentioned in the title, and is the subject of the catalytic activity study.
2. A COUNTERPART/CONTROL material is a related but different material used for comparison (e.g., pristine vs. modified, undoped vs. doped, original vs. reduced).
3. A REFERENCED material is from other papers, used only for comparison in tables or text — it is NOT the subject of this paper.

KEY RULES:
- "R-" prefix means "reduced" (e.g., R-MnCo2O4 = reduced MnCo2O4 with oxygen vacancies). This is a DIFFERENT material from MnCo2O4.
- Materials with different prefixes, dopants, or surface modifications are DIFFERENT materials, not aliases.
- The title and abstract usually name the primary material explicitly.
- If the paper compares a modified material with its pristine form, the MODIFIED one is typically the primary (it's the novel contribution).
- Do NOT confuse section headers (ABSTRACT, INTRODUCTION, RESULTS) with material names.
- Do NOT confuse referenced materials from other papers with the primary nanozyme of THIS paper.

OUTPUT FORMAT — respond with strict JSON only (no markdown fences, no commentary):
{
    "primary_nanozyme": "<exact material name as written in the paper>",
    "primary_description": "<brief description of what this material is>",
    "related_systems": [
        {
            "name": "<material name>",
            "relationship": "<pristine_counterpart | doped_variant | control | reference_from_other_paper>",
            "description": "<brief description>"
        }
    ],
    "confidence": <0.0-1.0>,
    "reasoning": "<why you chose this as the primary nanozyme>"
}"""

MATERIAL_IDENTIFICATION_USER_TEMPLATE = """Identify the PRIMARY nanozyme material from this paper.

Title: {title}

Abstract and key text:
{text}

Respond with strict JSON only."""

PROBE_MOLECULES = {
    "crystal violet", "cv+", "cv",
    "methylene blue", "mb",
    "rhodamine b", "rhb",
    "rhodamine 6g", "r6g",
    "4-nitrophenol", "4-np",
    "congo red",
    "methyl orange",
    "methyl red",
    "eosin y",
    "fluorescein",
    "janus green b",
    "nile blue",
    "nile red",
    "acridine orange",
    "proflavine",
    "safranin",
    "neutral red",
}


class MaterialIdentifier:
    def __init__(self, client=None, config=None):
        self.client = client
        self.config = config
        self.model = getattr(config, "llm_model", "deepseek-chat") if config else "deepseek-chat"
        self.temperature = 0.0
        self.max_tokens = 1024

    async def identify(
        self,
        title: str,
        abstract_chunks: List[str],
        first_chunks: List[str],
    ) -> Dict[str, Any]:
        if not self.client:
            logger.debug("[MaterialIdentifier] No LLM client, returning empty result")
            return {}

        combined = self._prepare_text(title, abstract_chunks, first_chunks)
        if len(combined.strip()) < 50:
            logger.warning("[MaterialIdentifier] Text too short for identification")
            return {}

        messages = self._build_messages(title, combined)
        raw_result = await self._call_llm(messages)

        if not raw_result:
            return {}

        parsed = self._parse_result(raw_result)
        if parsed:
            logger.info(
                f"[MaterialIdentifier] Primary: {parsed.get('primary_nanozyme')}, "
                f"Related: {[r['name'] for r in parsed.get('related_systems', [])]}, "
                f"Confidence: {parsed.get('confidence')}"
            )
        return parsed

    def _prepare_text(
        self,
        title: str,
        abstract_chunks: List[str],
        first_chunks: List[str],
    ) -> str:
        parts = []
        for chunk in abstract_chunks[:3]:
            if chunk and len(chunk.strip()) > 20:
                parts.append(chunk.strip()[:2000])
        for chunk in first_chunks[:5]:
            if chunk and len(chunk.strip()) > 20:
                parts.append(chunk.strip()[:1500])
        combined = "\n\n".join(parts)
        if len(combined) > 8000:
            combined = combined[:8000]
        return combined

    def _build_messages(self, title: str, text: str) -> List[Dict[str, str]]:
        return [
            {"role": "system", "content": MATERIAL_IDENTIFICATION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": MATERIAL_IDENTIFICATION_USER_TEMPLATE.format(
                    title=title, text=text
                ),
            },
        ]

    async def _call_llm(self, messages: List[Dict[str, str]]) -> Optional[str]:
        try:
            response = await self.client.chat(
                messages=messages,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            if response and isinstance(response, dict):
                choices = response.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
            return None
        except Exception as e:
            logger.warning(f"[MaterialIdentifier] LLM call failed: {e}")
            return None

    def _parse_result(self, raw: str) -> Dict[str, Any]:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            json_match = re.search(r'\{[\s\S]*\}', cleaned)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                except json.JSONDecodeError:
                    logger.warning("[MaterialIdentifier] Failed to parse LLM response as JSON")
                    return {}
            else:
                return {}

        if not isinstance(result, dict):
            return {}

        primary = result.get("primary_nanozyme", "")
        if not primary or not isinstance(primary, str):
            return {}

        primary_stripped = primary.strip()
        if primary_stripped.upper() in {
            "ABSTRACT", "INTRODUCTION", "RESULTS", "DISCUSSION",
            "CONCLUSION", "METHODS", "EXPERIMENTAL", "SUPPLEMENTARY",
            "NANOPARTICLE", "NANOZYME", "MATERIAL", "CATALYST",
        }:
            logger.warning(f"[MaterialIdentifier] LLM returned section header as material: {primary_stripped}")
            return {}

        related = result.get("related_systems", [])
        if not isinstance(related, list):
            related = []

        validated_related = []
        for sys_info in related:
            if not isinstance(sys_info, dict):
                continue
            name = sys_info.get("name", "")
            if not name or not isinstance(name, str):
                continue
            validated_related.append({
                "name": name.strip(),
                "relationship": sys_info.get("relationship", "unknown"),
                "description": sys_info.get("description", ""),
            })

        return {
            "primary_nanozyme": primary_stripped,
            "primary_description": result.get("primary_description", ""),
            "related_systems": validated_related,
            "confidence": float(result.get("confidence", 0.5)),
            "reasoning": result.get("reasoning", ""),
        }

    def enhance_candidates(
        self,
        rule_candidates: List[Dict[str, Any]],
        llm_result: Dict[str, Any],
        doc,
    ) -> List[Dict[str, Any]]:
        if not llm_result or not llm_result.get("primary_nanozyme"):
            return rule_candidates

        primary = llm_result["primary_nanozyme"]
        primary_lower = primary.lower().strip()

        existing_names = {c["name"].lower().strip() for c in rule_candidates if c.get("name")}

        if primary_lower not in existing_names:
            new_candidate = {
                "name": primary,
                "sources": {"llm_identification"},
                "evidence": [f"[LLM] Primary nanozyme: {primary}"],
                "score": 0,
                "llm_identified": True,
                "llm_confidence": llm_result.get("confidence", 0.5),
            }
            rule_candidates.insert(0, new_candidate)
            logger.info(f"[MaterialIdentifier] Injected LLM-identified primary: {primary}")
        else:
            for cand in rule_candidates:
                if cand["name"].lower().strip() == primary_lower:
                    cand["sources"].add("llm_identification")
                    cand["llm_identified"] = True
                    cand["llm_confidence"] = llm_result.get("confidence", 0.5)
                    cand["evidence"].append(f"[LLM] Primary nanozyme: {primary}")
                    break

        related_names = set()
        for sys_info in llm_result.get("related_systems", []):
            rname = sys_info.get("name", "").strip()
            if rname:
                related_names.add(rname.lower())
                if rname.lower() not in existing_names:
                    rule_candidates.append({
                        "name": rname,
                        "sources": {"llm_related"},
                        "evidence": [f"[LLM] Related system ({sys_info.get('relationship', 'unknown')}): {rname}"],
                        "score": 0,
                        "llm_related": True,
                        "llm_relationship": sys_info.get("relationship", "unknown"),
                    })

        for cand in rule_candidates:
            cand_lower = cand["name"].lower().strip()
            if cand_lower in related_names and cand_lower != primary_lower:
                cand.setdefault("llm_related", True)
                cand["llm_relationship"] = "related_system"

        return rule_candidates

    @staticmethod
    def is_probe_molecule(name: str) -> bool:
        if not name:
            return False
        return name.lower().strip() in PROBE_MOLECULES
