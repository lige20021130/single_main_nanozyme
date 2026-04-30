import re
import logging
from typing import Optional, Dict, List, Any, Set
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class IssueSeverity(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


@dataclass
class GuardIssue:
    field: str
    severity: IssueSeverity
    description: str
    rule_value: Any = None
    llm_value: Any = None


@dataclass
class GuardCheckResult:
    action: str = "continue"
    warnings: List[str] = field(default_factory=list)
    re_extract_reason: str = ""
    re_extract_fields: List[str] = field(default_factory=list)


@dataclass
class LLMCheckResult:
    issues: List[GuardIssue] = field(default_factory=list)


@dataclass
class ResolutionResult:
    field: str = ""
    resolved_by: str = ""
    resolution: str = ""


class AgenticConsistencyGuard:
    def __init__(self, selected_name: str, all_candidate_names: List[Dict],
                 text_chunks: List[str] = None, client=None):
        self.selected_name = selected_name
        self.candidate_names = [c["name"] if isinstance(c, dict) else c
                                for c in all_candidate_names]
        self.text_chunks = text_chunks or []
        self.client = client

    def check_after_rule_extraction(self, record: Dict, buckets: Dict) -> GuardCheckResult:
        result = GuardCheckResult(action="continue")
        warnings = []

        sel = record.get("selected_nanozyme", {})
        act = record.get("main_activity", {})
        kin = act.get("kinetics", {})

        if not sel.get("name"):
            result.action = "trigger_re_extraction"
            result.re_extract_reason = "no_material_name"
            result.re_extract_fields = ["name"]
            return result

        if not act.get("enzyme_like_type"):
            warnings.append("rule_extraction_missing_enzyme_type")

        if kin.get("Km") is None and kin.get("Vmax") is None:
            kinetics_texts = buckets.get("kinetics", [])
            if kinetics_texts:
                has_km_mention = any(re.search(r'\bKm\b', t, re.I) for t in kinetics_texts)
                has_vmax_mention = any(re.search(r'\bVmax\b', t, re.I) for t in kinetics_texts)
                if has_km_mention or has_vmax_mention:
                    warnings.append("rule_extraction_kinetics_mentioned_but_not_extracted")

        if not record.get("applications"):
            app_texts = buckets.get("application", [])
            if app_texts:
                warnings.append("rule_extraction_app_bucket_nonempty_but_no_applications")

        result.warnings = warnings
        if warnings:
            result.action = "continue_with_warnings"

        return result

    def check_after_llm_extraction(self, record: Dict, llm_result: Dict,
                                    buckets: Dict) -> LLMCheckResult:
        issues = []

        if not llm_result:
            return LLMCheckResult(issues=issues)

        llm_sel = llm_result.get("selected_nanozyme", {})
        llm_act = llm_result.get("main_activity", {})
        llm_kin = llm_act.get("kinetics", {})

        rule_sel = record.get("selected_nanozyme", {})
        rule_act = record.get("main_activity", {})
        rule_kin = rule_act.get("kinetics", {})

        llm_name = llm_sel.get("name", "")
        if llm_name and rule_sel.get("name"):
            if llm_name.lower() != rule_sel["name"].lower():
                if not self._names_compatible(rule_sel["name"], llm_name):
                    issues.append(GuardIssue(
                        field="selected_nanozyme.name",
                        severity=IssueSeverity.HIGH,
                        description=f"Material name conflict: rule={rule_sel['name']}, llm={llm_name}",
                        rule_value=rule_sel["name"],
                        llm_value=llm_name,
                    ))

        llm_etype = llm_act.get("enzyme_like_type")
        rule_etype = rule_act.get("enzyme_like_type")
        if llm_etype and rule_etype:
            llm_norm = self._normalize_enzyme_type(llm_etype)
            rule_norm = self._normalize_enzyme_type(rule_etype)
            if llm_norm and rule_norm and llm_norm != rule_norm:
                issues.append(GuardIssue(
                    field="main_activity.enzyme_like_type",
                    severity=IssueSeverity.HIGH,
                    description=f"Enzyme type conflict: rule={rule_etype}, llm={llm_etype}",
                    rule_value=rule_etype,
                    llm_value=llm_etype,
                ))

        for param in ("Km", "Vmax", "kcat"):
            llm_val = llm_kin.get(param)
            rule_val = rule_kin.get(param)
            if llm_val is not None and rule_val is not None:
                try:
                    lv = float(llm_val) if not isinstance(llm_val, (int, float)) else llm_val
                    rv = float(rule_val) if not isinstance(rule_val, (int, float)) else rule_val
                    if rv != 0 and lv != 0:
                        ratio = lv / rv
                        if ratio > 100 or ratio < 0.01:
                            issues.append(GuardIssue(
                                field=f"main_activity.kinetics.{param}",
                                severity=IssueSeverity.MEDIUM,
                                description=f"{param} magnitude conflict: rule={rule_val}, llm={llm_val}",
                                rule_value=rule_val,
                                llm_value=llm_val,
                            ))
                except (ValueError, TypeError, ZeroDivisionError):
                    pass

        return LLMCheckResult(issues=issues)

    async def resolve_with_llm(self, issue: GuardIssue, buckets: Dict) -> ResolutionResult:
        result = ResolutionResult(
            field=issue.field,
            resolved_by="rule",
            resolution="No LLM client available, keeping rule value",
        )

        if not self.client:
            return result

        context_texts = []
        for key in ("kinetics", "activity", "material"):
            context_texts.extend(buckets.get(key, [])[:3])
        context = " ".join(context_texts)[:2000]

        prompt = (
            f"You are a nanozyme data validation expert. There is a conflict in field '{issue.field}':\n"
            f"- Rule-based extraction value: {issue.rule_value}\n"
            f"- LLM extraction value: {issue.llm_value}\n"
            f"Context from paper: {context[:1000]}\n\n"
            f"Which value is more likely correct? Reply with ONLY one of: 'rule' or 'llm', "
            f"followed by a brief reason in one sentence.\n"
            f"Format: WINNER|REASON"
        )

        try:
            import asyncio
            response = await asyncio.wait_for(
                self.client.chat_completion_text(
                    [{"role": "user", "content": prompt}],
                    temperature=0.1, max_tokens=200,
                ),
                timeout=30,
            )
            if response:
                text = response.strip()
                if "|" in text:
                    winner, reason = text.split("|", 1)
                    winner = winner.strip().lower()
                    reason = reason.strip()
                else:
                    winner = text.strip().lower()
                    reason = text

                if winner == "llm":
                    result.resolved_by = "llm"
                    result.resolution = reason[:200]
                else:
                    result.resolved_by = "rule"
                    result.resolution = reason[:200]

                logger.info(f"[AgenticGuard] LLM resolved {issue.field}: winner={result.resolved_by}")
        except Exception as e:
            logger.warning(f"[AgenticGuard] LLM resolution failed: {e}")
            result.resolution = f"LLM resolution failed: {str(e)[:100]}"

        return result

    @staticmethod
    def _names_compatible(name1: str, name2: str) -> bool:
        n1 = name1.lower().replace("-", "").replace(" ", "")
        n2 = name2.lower().replace("-", "").replace(" ", "")
        if n1 == n2:
            return True
        if n1 in n2 or n2 in n1:
            return True
        suffixes = ("nps", "nanoparticles", "nanoparticle", "nanozyme", "nanocomposite",
                     "nanosheets", "nanosheet", "nanorods", "nanorod", "nanoflowers",
                     "nanoflower", "nanocubes", "nanocube", "nanocluster", "nanoclusters")
        for s in suffixes:
            if n1.rstrip(s) == n2.rstrip(s) and n1.rstrip(s):
                return True
        return False

    @staticmethod
    def _normalize_enzyme_type(etype: str) -> Optional[str]:
        if not etype:
            return None
        t = etype.lower().replace(" ", "-").replace("_", "-")
        aliases = {
            "pod-like": "peroxidase-like",
            "sod-like": "superoxide-dismutase-like",
            "gpx-like": "glutathione-peroxidase-like",
            "cat-like": "catalase-like",
            "oxd-like": "oxidase-like",
        }
        return aliases.get(t, t)
