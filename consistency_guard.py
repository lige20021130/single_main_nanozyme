import re
import logging
from typing import Dict, List, Optional, Any, Tuple, Set

logger = logging.getLogger(__name__)

_CONTRAST_MARKERS = frozenset({
    "in contrast", "compared with", "compared to", "whereas", "while",
    "on the other hand", "unlike", "different from", "in comparison",
    "higher than", "lower than", "better than", "worse than",
    "superior to", "inferior to", "as compared", "versus", "vs.",
})

_COMPARISON_TABLE_MARKERS = re.compile(
    r'\bcomparison\b|\bvs\.?\b|\bdifferent\s+(?:nanozyme|catalyst|material|sample)',
    re.I,
)

_OTHER_MATERIAL_PRONOUNS = re.compile(
    r'\bother\s+(?:nanozyme|catalyst|material|sample|system|nanoparticle)\b',
    re.I,
)

_PREVIOUS_WORK_MARKERS = re.compile(
    r'\bprevious\s+(?:work|study|report|literature)\b|\breported\s+(?:by|in)\b|\bref\.?\s*\d',
    re.I,
)

_THIS_WORK_MARKERS = re.compile(
    r'\bthis\s+work\b|\bcurrent\s+work\b|\bpresent\s+(?:work|study)\b|'
    r'\bour\s+(?:nanozyme|catalyst|material|system|sample|nanoparticle|result|finding)\b|'
    r'\bhere(?:in|by|after)?\b|\bas-prepared\b|\bas-synthesized\b|\bproposed\b',
    re.I,
)

_KINETIC_PARAM_NAMES = frozenset({"Km", "Vmax", "kcat", "kcat_Km"})

_PATTERNS_FOR_OTHER_MATERIALS = [
    re.compile(r'\b(?:Fe|Co|Ni|Mn|Cu|Zn|Ce|Au|Ag|Pt|Pd|Ti|V|Cr|Mo|W|Ru|Rh|Ir|La)\d*(?:O\d*)?(?:[A-Z][a-z]?\d*(?:O\d*)?)*\b'),
    re.compile(r'\bMOF[-\s]?\d+\b|\bCOF[-\s]?\d+\b|\bZIF[-\s]?\d+\b'),
    re.compile(r'\b[A-Z][a-z]?\d*(?:@[A-Z][a-z]?\d*)?\b'),
]


class ConsistencyGuard:
    def __init__(self, selected_name: str, all_candidates: Optional[List[str]] = None,
                 text_chunks: Optional[List[str]] = None):
        self.selected_name = selected_name
        self.selected_lower = selected_name.lower().strip() if selected_name else ""
        self.selected_variants = self._build_variants(selected_name)
        self.other_candidates = self._build_other_candidates(all_candidates or [])
        self.aliases: Set[str] = set()
        self._discover_aliases(text_chunks or [])
        self.selected_variants.update(self.aliases)
        self.other_candidates = {c for c in self.other_candidates if c not in self.selected_variants}
        self.warnings: List[str] = []
        self.attribution_log: List[Dict[str, Any]] = []

    def _discover_aliases(self, text_chunks: List[str]) -> None:
        if not text_chunks or not self.selected_name:
            return

        full_text = " ".join(text_chunks)
        fl = full_text.lower()

        self._discover_abbreviation_aliases(fl)
        self._discover_component_aliases(fl)
        self._discover_sazyyme_aliases(fl)
        self._discover_suffix_aliases(fl)
        self._discover_co_occurrence_aliases(fl, text_chunks)

        if self.aliases:
            logger.info(f"[ConsistencyGuard] Discovered aliases for '{self.selected_name}': {self.aliases}")

    def _discover_abbreviation_aliases(self, text_lower: str) -> None:
        patterns = [
            re.compile(
                re.escape(self.selected_lower) + r'\s*\(([^)]+)\)',
                re.I,
            ),
            re.compile(
                r'\b([A-Z][A-Za-z\d]*)\s*\(' + re.escape(self.selected_lower) + r'\)',
                re.I,
            ),
        ]
        for pat in patterns:
            for m in pat.finditer(text_lower):
                alias = m.group(1).strip().lower()
                if not self._is_valid_alias(alias):
                    continue
                self.aliases.add(alias)

        for variant in list(self.selected_variants):
            esc = re.escape(variant)
            pat = re.compile(r'\b([A-Z][A-Za-z\d]*(?:[-/][A-Z][A-Za-z\d]*)*)\s*\(' + esc + r'\)', re.I)
            for m in pat.finditer(text_lower):
                alias = m.group(1).strip().lower()
                if not self._is_valid_alias(alias):
                    continue
                self.aliases.add(alias)

    def _is_valid_alias(self, alias: str) -> bool:
        if len(alias) < 2 or len(alias) > 30:
            return False
        if alias in self.selected_variants:
            return False
        if re.match(r'^[\d\s\-+.,/]+$', alias):
            return False
        if re.match(r'^\d', alias):
            return False
        if any(kw in alias for kw in ("mgml", "mg/kg", "mmol", "nm", "μm", "ml",
                                       "figure", "fig.", "fig ", "table", "scheme",
                                       "ref", "suppl", "esm", "si ", "s1", "s2",
                                       "s3", "s4", "s5", "s6", "s7", "s8", "s9")):
            return False
        stop_words = {"of", "in", "the", "and", "or", "for", "with", "from", "by",
                      "at", "to", "a", "an", "is", "are", "was", "were", "be", "been",
                      "has", "have", "had", "not", "but", "as", "on", "it", "this",
                      "that", "which", "can", "will", "may", "also", "than", "into"}
        if alias in stop_words:
            return False
        if alias.count(" ") > 4:
            return False
        letter_count = sum(1 for c in alias if c.isalpha())
        if letter_count < 2:
            return False
        return True

    def _discover_component_aliases(self, text_lower: str) -> None:
        if "@" in self.selected_lower:
            parts = [p.strip() for p in self.selected_lower.split("@") if p.strip()]
            if len(parts) == 2:
                core, shell = parts
                sazyme_pat = re.compile(
                    r'\b' + re.escape(core) + r'\s*(?:SAzyme|SAE|single[- ]atom[- ](?:enzyme|nanozyme|catalyst))\b',
                    re.I,
                )
                if sazyme_pat.search(text_lower):
                    for suffix in ("sazyyme", "sae", "single-atom enzyme", "single-atom nanozyme",
                                   "single atom enzyme", "single atom nanozyme", "single-atom catalyst"):
                        alias = f"{core} {suffix}"
                        self.aliases.add(alias)
                        alias_compact = f"{core}{suffix.replace(' ', '')}"
                        self.aliases.add(alias_compact)

    def _discover_sazyyme_aliases(self, text_lower: str) -> None:
        for variant in list(self.selected_variants):
            if len(variant) < 2:
                continue
            sazyme_forms = [
                variant + " sazyme",
                variant + " sazymes",
                variant + " sae",
                variant + " nanozyme",
                variant + " nanozymes",
                variant + "sazyyme",
                variant + "sazyymes",
                variant + "sae",
            ]
            for form in sazyme_forms:
                if form in text_lower:
                    self.aliases.add(form)

    def _discover_suffix_aliases(self, text_lower: str) -> None:
        suffixes = (
            "sazyyme", "sazyymes", "sae", "nanozyme", "nanozymes",
            "nanoparticle", "nanoparticles", "nps", "nanosheet", "nanosheets",
            "nanosphere", "nanospheres", "nanorod", "nanorods",
            "nanocluster", "nanoclusters", "catalyst",
        )
        for variant in list(self.selected_variants):
            if len(variant) < 2:
                continue
            for suffix in suffixes:
                combined = variant + " " + suffix
                combined_compact = variant + suffix
                if combined in text_lower:
                    self.aliases.add(combined)
                if combined_compact in text_lower:
                    self.aliases.add(combined_compact)

    def _discover_co_occurrence_aliases(self, text_lower: str, text_chunks: List[str]) -> None:
        if not self.other_candidates:
            return

        for other in list(self.other_candidates):
            if len(other) < 2:
                continue
            other_lower = other.lower()

            if not self._could_be_alias(other):
                continue

            is_defined_as_same = self._check_definition_pattern(other_lower, text_lower)
            if is_defined_as_same:
                self.aliases.add(other_lower)
                logger.info(
                    f"[ConsistencyGuard] Alias discovered via definition pattern: "
                    f"'{other}' is alias of '{self.selected_name}'"
                )
                continue

            co_occurrence_in_same_sentence = 0
            other_alone_sentences = 0
            total_other_mentions = 0

            for chunk in text_chunks:
                cl = chunk.lower()
                for line in cl.split("."):
                    line = line.strip()
                    if not line:
                        continue
                    has_selected = any(v in line for v in self.selected_variants if len(v) >= 2)
                    has_other = other_lower in line

                    if has_other:
                        total_other_mentions += 1
                    if has_other and not has_selected:
                        other_alone_sentences += 1
                    if has_selected and has_other:
                        co_occurrence_in_same_sentence += 1

            if co_occurrence_in_same_sentence < 2:
                continue

            is_compound = other_lower in self.selected_lower or self.selected_lower in other_lower
            if is_compound:
                self.aliases.add(other_lower)
                logger.info(
                    f"[ConsistencyGuard] Alias discovered via compound: "
                    f"'{other}' is alias of '{self.selected_name}'"
                )
                continue

            is_abbreviation = self._is_likely_abbreviation(other)
            if is_abbreviation and other_alone_sentences <= 1:
                self.aliases.add(other_lower)
                logger.info(
                    f"[ConsistencyGuard] Alias discovered via abbreviation co-occurrence: "
                    f"'{other}' is alias of '{self.selected_name}' (co_occ={co_occurrence_in_same_sentence})"
                )
                continue

            if (co_occurrence_in_same_sentence >= 4 and
                    other_alone_sentences == 0 and
                    total_other_mentions >= 4 and
                    self._is_likely_abbreviation(other)):
                self.aliases.add(other_lower)
                logger.info(
                    f"[ConsistencyGuard] Alias discovered via high co-occurrence: "
                    f"'{other}' is alias of '{self.selected_name}' (co_occ={co_occurrence_in_same_sentence}, alone=0)"
                )

    def _could_be_alias(self, candidate: str) -> bool:
        if re.match(r'^[A-Z][a-z]?\d*(?:O\d*)?$', candidate):
            return False
        if re.match(r'^[a-z]?\d+$', candidate):
            return False
        if len(candidate) <= 1:
            return False
        return True

    def _check_definition_pattern(self, other_lower: str, text_lower: str) -> bool:
        for variant in self.selected_variants:
            if len(variant) < 2:
                continue
            combined_forward = variant + " " + other_lower
            combined_reverse = other_lower + " " + variant
            if combined_forward in text_lower or combined_reverse in text_lower:
                return True

            esc_v = re.escape(variant)
            esc_o = re.escape(other_lower)
            pat1 = re.compile(esc_v + r'[-/\s]+' + esc_o, re.I)
            pat2 = re.compile(esc_o + r'[-/\s]+' + esc_v, re.I)
            if pat1.search(text_lower) or pat2.search(text_lower):
                return True

            pat3 = re.compile(esc_o + r'\s*\(' + esc_v + r'\)', re.I)
            pat4 = re.compile(esc_v + r'\s*\(' + esc_o + r'\)', re.I)
            if pat3.search(text_lower) or pat4.search(text_lower):
                return True

        return False

    def _is_likely_abbreviation(self, candidate: str) -> bool:
        if len(candidate) <= 10 and sum(1 for c in candidate if c.isupper()) >= len(candidate.replace(" ", "").replace("-", "").replace("/", "")) * 0.4:
            return True
        if candidate.endswith("s") and len(candidate) >= 3 and candidate[:-1].isupper():
            return True
        suffixes = ("sazyyme", "sae", "nanozyme", "nanozymes", "nanoparticle",
                    "nanoparticles", "nps", "nanosheet", "nanosheets")
        for s in suffixes:
            if candidate.lower().endswith(s):
                return True
        return False

    def _build_variants(self, name: str) -> Set[str]:
        if not name:
            return set()
        variants = set()
        nl = name.lower().strip()
        variants.add(nl)
        if "@" in nl:
            variants.update(p.strip() for p in nl.split("@") if p.strip())
        if "/" in nl:
            variants.update(p.strip() for p in nl.split("/") if p.strip())
        for prefix in ("nano", "the ", "a ", "nano-sized ", "nanosized "):
            if nl.startswith(prefix):
                variants.add(nl[len(prefix):])
        compact = nl.replace(" ", "").replace("-", "")
        if compact != nl:
            variants.add(compact)
        for suffix in (" nanoparticles", " nanosheets", " nanorods",
                       " nanotubes", " nanospheres", " nanozyme",
                       " nanozymes", " catalyst", " nps"):
            if nl.endswith(suffix):
                variants.add(nl[:-len(suffix)])
        return variants

    def _build_other_candidates(self, all_candidates: List[str]) -> Set[str]:
        others = set()
        for cand in all_candidates:
            cl = cand.lower().strip()
            if cl and cl != self.selected_lower and cl not in self.selected_variants:
                others.add(cl)
        return others

    def check_sentence_attribution(self, sentence: str) -> Dict[str, Any]:
        if not sentence or not self.selected_name:
            return {"belongs_to_selected": True, "confidence": "low", "reason": "empty_input"}

        sl = sentence.lower()

        mentions_selected = any(v in sl for v in self.selected_variants if len(v) >= 2)
        mentions_other = any(c in sl for c in self.other_candidates if len(c) >= 2)

        has_this_work = bool(_THIS_WORK_MARKERS.search(sl))
        has_contrast = any(m in sl for m in _CONTRAST_MARKERS)
        has_prev_work = bool(_PREVIOUS_WORK_MARKERS.search(sl))
        has_other_pronoun = bool(_OTHER_MATERIAL_PRONOUNS.search(sl))

        if mentions_selected and not mentions_other:
            if has_contrast:
                return {"belongs_to_selected": True, "confidence": "medium",
                        "reason": "mentions_selected_but_contrast"}
            return {"belongs_to_selected": True, "confidence": "high",
                    "reason": "mentions_selected_only"}

        if mentions_selected and mentions_other:
            if has_this_work and has_contrast:
                return {"belongs_to_selected": True, "confidence": "medium",
                        "reason": "selected_with_this_work_marker_amid_contrast"}
            if has_contrast:
                selected_is_subject = self._is_selected_subject(sentence)
                if selected_is_subject:
                    return {"belongs_to_selected": True, "confidence": "medium",
                            "reason": "selected_is_subject_in_contrast"}
                return {"belongs_to_selected": False, "confidence": "medium",
                        "reason": "contrast_context_mentions_both"}
            return {"belongs_to_selected": True, "confidence": "low",
                    "reason": "mentions_both_no_contrast"}

        if not mentions_selected and mentions_other:
            if has_this_work:
                return {"belongs_to_selected": True, "confidence": "medium",
                        "reason": "this_work_marker_without_explicit_name"}
            if has_prev_work:
                return {"belongs_to_selected": False, "confidence": "high",
                        "reason": "previous_work_reference"}
            return {"belongs_to_selected": False, "confidence": "medium",
                    "reason": "mentions_other_only"}

        if not mentions_selected and not mentions_other:
            if has_this_work:
                return {"belongs_to_selected": True, "confidence": "medium",
                        "reason": "this_work_marker_generic"}
            if has_prev_work:
                return {"belongs_to_selected": False, "confidence": "medium",
                        "reason": "previous_work_generic"}
            return {"belongs_to_selected": True, "confidence": "low",
                    "reason": "no_material_mentioned"}

    def check_kinetics_attribution(
        self,
        param_name: str,
        value: Any,
        evidence_text: str,
        source: str = "",
    ) -> Dict[str, Any]:
        if not evidence_text:
            return {"valid": True, "confidence": "low", "reason": "no_evidence_text"}

        attr = self.check_sentence_attribution(evidence_text)

        if not attr["belongs_to_selected"]:
            self.warnings.append(f"{param_name}_attribution_mismatch")
            self.attribution_log.append({
                "param": param_name, "value": value,
                "reason": attr["reason"], "evidence": evidence_text[:100],
            })
            return {"valid": False, "confidence": attr["confidence"],
                    "reason": f"not_attributed_to_selected:{attr['reason']}"}

        if attr["confidence"] == "low":
            nearby_materials = self._find_nearby_materials(evidence_text)
            if nearby_materials and self.selected_lower not in " ".join(nearby_materials).lower():
                self.warnings.append(f"{param_name}_possible_other_material")
                return {"valid": True, "confidence": "low",
                        "reason": "nearby_other_materials_no_selected"}

        return {"valid": True, "confidence": attr["confidence"],
                "reason": attr["reason"]}

    def check_pH_attribution(self, pH_value: Any, evidence_text: str) -> Dict[str, Any]:
        return self.check_kinetics_attribution("pH", pH_value, evidence_text)

    def check_temperature_attribution(self, temp_value: Any, evidence_text: str) -> Dict[str, Any]:
        return self.check_kinetics_attribution("temperature", temp_value, evidence_text)

    def check_synthesis_attribution(self, method: str, evidence_text: str) -> Dict[str, Any]:
        return self.check_kinetics_attribution("synthesis_method", method, evidence_text)

    def check_application_attribution(self, app: Dict[str, Any], evidence_text: str) -> Dict[str, Any]:
        analyte = app.get("target_analyte", "") or ""
        return self.check_kinetics_attribution(
            f"application_{analyte}", app.get("detection_limit"), evidence_text
        )

    def validate_record_consistency(self, record: Dict[str, Any]) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        warnings: List[str] = list(self.warnings)

        kinetics = record.get("main_activity", {}).get("kinetics", {})
        km_val = kinetics.get("Km")
        vmax_val = kinetics.get("Vmax")
        km_source = kinetics.get("source", "")
        km_substrate = kinetics.get("substrate", "")

        if km_val is not None and vmax_val is not None:
            if isinstance(km_val, (int, float)) and isinstance(vmax_val, (int, float)):
                if km_val > 0 and vmax_val < 0:
                    issues.append({"field": "kinetics", "issue": "Km_positive_Vmax_negative"})
                    warnings.append("kinetics_sign_inconsistency")

        enzyme_type_rule = record.get("main_activity", {}).get("enzyme_like_type")
        if enzyme_type_rule:
            ph_opt = record.get("main_activity", {}).get("pH_profile", {}).get("optimal_pH")
            if ph_opt is not None:
                try:
                    ph_float = float(ph_opt)
                    if enzyme_type_rule == "catalase-like" and ph_float < 5:
                        issues.append({"field": "pH_profile", "issue": "catalase_low_pH",
                                       "detail": f"catalase-like typically optimal at pH>5, got {ph_float}"})
                        warnings.append("enzyme_pH_inconsistency")
                    if enzyme_type_rule == "peroxidase-like" and ph_float > 9:
                        issues.append({"field": "pH_profile", "issue": "peroxidase_high_pH",
                                       "detail": f"peroxidase-like typically optimal at pH<9, got {ph_float}"})
                        warnings.append("enzyme_pH_inconsistency")
                except (ValueError, TypeError):
                    pass

        sel = record.get("selected_nanozyme", {})
        synth_method = sel.get("synthesis_method", "") or ""
        synth_temp = sel.get("synthesis_conditions", {}).get("temperature", "") or ""
        if synth_method and synth_temp:
            try:
                synth_temp_str = str(synth_temp)
                temp_num = float(re.search(r'([\d.]+)', synth_temp_str).group(1))
                if "hydrothermal" in synth_method.lower() and temp_num < 100:
                    issues.append({"field": "synthesis", "issue": "hydrothermal_low_temp",
                                   "detail": f"hydrothermal typically >100°C, got {temp_num}"})
                    warnings.append("synthesis_temp_inconsistency")
                if "calcination" in synth_method.lower() and temp_num < 300:
                    issues.append({"field": "synthesis", "issue": "calcination_low_temp",
                                   "detail": f"calcination typically >300°C, got {temp_num}"})
                    warnings.append("synthesis_temp_inconsistency")
            except (AttributeError, ValueError):
                pass

        size_str = str(sel.get("size", "") or "")
        synth_method_lower = synth_method.lower()
        if size_str and synth_method_lower:
            try:
                size_match = re.search(r'([\d.]+)\s*(nm|μm|um)', size_str)
                if size_match:
                    size_num = float(size_match.group(1))
                    size_unit = size_match.group(2)
                    if size_unit in ("nm",) and size_num > 500 and "nanoparticle" in (sel.get("morphology") or "").lower():
                        issues.append({"field": "size", "issue": "large_nanoparticle",
                                       "detail": f"nanoparticle size {size_num}nm seems large"})
            except (AttributeError, ValueError):
                pass

        cross_result = self.detect_cross_context_mismatches(record)
        if cross_result["mismatches"]:
            issues.extend(cross_result["mismatches"])
            warnings.extend(cross_result["warnings"])

        return {
            "issues": issues,
            "warnings": warnings,
            "attribution_log": self.attribution_log,
            "is_consistent": len(issues) == 0,
        }

    def filter_evidence_bucket(
        self,
        bucket_name: str,
        sentences: List[str],
    ) -> List[str]:
        if bucket_name in ("kinetics", "application", "mechanism"):
            return self._filter_strict_attribution(bucket_name, sentences)
        elif bucket_name in ("activity", "synthesis", "characterization"):
            return self._filter_loose_attribution(bucket_name, sentences)
        else:
            return sentences

    def _filter_strict_attribution(self, bucket_name: str, sentences: List[str]) -> List[str]:
        filtered = []
        for s in sentences:
            attr = self.check_sentence_attribution(s)
            if attr["belongs_to_selected"]:
                filtered.append(s)
            else:
                logger.debug(
                    f"[ConsistencyGuard] Filtered out {bucket_name} sentence: "
                    f"reason={attr['reason']}, text={s[:80]}..."
                )
        if not filtered and sentences:
            logger.warning(
                f"[ConsistencyGuard] Strict filter removed ALL {bucket_name} sentences "
                f"({len(sentences)} total). Falling back to 'this work' only."
            )
            fallback = [s for s in sentences if _THIS_WORK_MARKERS.search(s.lower())]
            if fallback:
                filtered = fallback
            else:
                logger.warning(
                    f"[ConsistencyGuard] No 'this work' sentences found for {bucket_name}. "
                    f"Using original sentences with low confidence."
                )
                filtered = sentences
                self.warnings.append(f"{bucket_name}_attribution_uncertain")
        return filtered

    def _filter_loose_attribution(self, bucket_name: str, sentences: List[str]) -> List[str]:
        filtered = []
        for s in sentences:
            attr = self.check_sentence_attribution(s)
            if attr["belongs_to_selected"]:
                filtered.append(s)
            elif attr["confidence"] == "high" and attr["reason"] in (
                "previous_work_reference", "mentions_other_only"
            ):
                continue
            else:
                filtered.append(s)
        return filtered

    def _find_nearby_materials(self, text: str) -> List[str]:
        found = []
        for pat in _PATTERNS_FOR_OTHER_MATERIALS:
            for m in pat.finditer(text):
                name = m.group(0).strip()
                nl = name.lower()
                if nl not in self.selected_variants and len(name) >= 2:
                    found.append(name)
        return list(dict.fromkeys(found))

    def detect_cross_context_mismatches(self, record: Dict[str, Any]) -> Dict[str, Any]:
        mismatches: List[Dict[str, Any]] = []
        mismatch_warnings: List[str] = []

        kinetics = record.get("main_activity", {}).get("kinetics", {})
        evidence_fields = {
            "kinetics.Km": kinetics.get("_evidence_Km", ""),
            "kinetics.Vmax": kinetics.get("_evidence_Vmax", ""),
            "kinetics.kcat": kinetics.get("_evidence_kcat", ""),
            "kinetics.kcat_Km": kinetics.get("_evidence_kcat_Km", ""),
        }

        field_materials: Dict[str, List[str]] = {}
        field_ph: Dict[str, Optional[float]] = {}
        ph_pattern = re.compile(r'pH\s*[=:≈~]\s*([\d.]+)', re.I)

        for field, ev_text in evidence_fields.items():
            if not ev_text:
                continue
            materials = self._find_nearby_materials(ev_text)
            if materials:
                field_materials[field] = materials
            ph_match = ph_pattern.search(ev_text)
            if ph_match:
                try:
                    field_ph[field] = float(ph_match.group(1))
                except ValueError:
                    field_ph[field] = None

        material_fields = list(field_materials.keys())
        for i in range(len(material_fields)):
            for j in range(i + 1, len(material_fields)):
                f1, f2 = material_fields[i], material_fields[j]
                mats1 = set(m.lower() for m in field_materials[f1])
                mats2 = set(m.lower() for m in field_materials[f2])
                if mats1 != mats2:
                    overlap = mats1 & mats2
                    only_in_1 = mats1 - mats2
                    only_in_2 = mats2 - mats1
                    other_only_1 = any(m in self.other_candidates for m in only_in_1)
                    other_only_2 = any(m in self.other_candidates for m in only_in_2)
                    if other_only_1 or other_only_2:
                        detail = (
                            f"Evidence for {f1} mentions {field_materials[f1]}, "
                            f"but {f2} mentions {field_materials[f2]}"
                        )
                        mismatches.append({
                            "type": "cross_material_mismatch",
                            "field1": f1,
                            "field2": f2,
                            "detail": detail,
                        })
                        mismatch_warnings.append("cross_material_mismatch")

        ph_fields = {f: v for f, v in field_ph.items() if v is not None}
        ph_field_list = list(ph_fields.keys())
        for i in range(len(ph_field_list)):
            for j in range(i + 1, len(ph_field_list)):
                f1, f2 = ph_field_list[i], ph_field_list[j]
                if abs(ph_fields[f1] - ph_fields[f2]) > 2.0:
                    detail = (
                        f"pH in {f1} evidence is {ph_fields[f1]}, "
                        f"but pH in {f2} evidence is {ph_fields[f2]} (diff > 2.0)"
                    )
                    mismatches.append({
                        "type": "condition_mismatch",
                        "field1": f1,
                        "field2": f2,
                        "detail": detail,
                    })
                    mismatch_warnings.append("condition_mismatch")

        enzyme_type = record.get("main_activity", {}).get("enzyme_like_type", "")
        if enzyme_type:
            enzyme_activity = enzyme_type.replace("-like", "").strip().lower()
            applications = record.get("applications", [])
            if isinstance(applications, list):
                for app in applications:
                    if not isinstance(app, dict):
                        continue
                    app_evidence = app.get("_evidence", "") or app.get("evidence", "") or ""
                    if not app_evidence:
                        continue
                    app_lower = app_evidence.lower()
                    known_types = [
                        "peroxidase", "catalase", "oxidase", "superoxide dismutase",
                        "superoxide dismutase-like", "glucose oxidase", "haloperoxidase",
                    ]
                    for kt in known_types:
                        kt_base = kt.replace("-like", "").strip().lower()
                        if kt_base in app_lower and kt_base != enzyme_activity:
                            if enzyme_activity not in app_lower:
                                detail = (
                                    f"enzyme_like_type is '{enzyme_type}' but application evidence "
                                    f"mentions '{kt_base}'"
                                )
                                mismatches.append({
                                    "type": "activity_application_mismatch",
                                    "field1": "main_activity.enzyme_like_type",
                                    "field2": "applications._evidence",
                                    "detail": detail,
                                })
                                mismatch_warnings.append("activity_application_mismatch")
                                break

        return {
            "mismatches": mismatches,
            "warnings": list(dict.fromkeys(mismatch_warnings)),
        }

    def _is_selected_subject(self, sentence: str) -> bool:
        sl = sentence.lower().strip()
        for v in sorted(self.selected_variants, key=len, reverse=True):
            if len(v) < 2:
                continue
            idx = sl.find(v)
            if idx < 0:
                continue
            if idx == 0:
                return True
            before = sl[:idx].rstrip()
            if before.endswith((",", ".", ";", "!", "?")):
                after_comma = sl[idx:]
                for verb in ("showed", "exhibited", "displayed", "demonstrated",
                             "had", "possessed", "achieved", "reached", "produced",
                             "was", "is", "were", "are", "has", "have"):
                    if after_comma.lstrip().startswith(verb):
                        return True
            if any(p in before for p in ("compared with ", "compared to ", "unlike ",
                                          "in contrast to ", "different from ")):
                after_phrase = sl[idx:]
                for verb in ("showed", "exhibited", "displayed", "demonstrated",
                             "had", "possessed", "achieved", "reached", "produced",
                             "was", "is", "were", "are", "has", "have"):
                    if verb in after_phrase:
                        return True
        return False

    def check_llm_result_attribution(self, llm_result: Dict[str, Any]) -> Dict[str, Any]:
        issues: List[str] = []
        filtered_result = {}

        sel = llm_result.get("selected_nanozyme", {})
        if isinstance(sel, dict):
            llm_name = sel.get("name", "") or ""
            if llm_name:
                llm_name_lower = llm_name.lower().strip()
                name_match = (
                    llm_name_lower == self.selected_lower or
                    llm_name_lower in self.selected_variants or
                    self.selected_lower in llm_name_lower or
                    llm_name_lower in self.selected_lower
                )
                if not name_match:
                    issues.append(f"llm_name_mismatch:expected={self.selected_name},got={llm_name}")
                    self.warnings.append("llm_name_mismatch")
                    sel = dict(sel)
                    sel["name"] = self.selected_name
                    sel["_llm_original_name"] = llm_name
            filtered_result["selected_nanozyme"] = sel

        act = llm_result.get("main_activity", {})
        if isinstance(act, dict):
            filtered_result["main_activity"] = act

        apps = llm_result.get("applications", [])
        if isinstance(apps, list):
            filtered_result["applications"] = apps

        ivs = llm_result.get("important_values", [])
        if isinstance(ivs, list):
            filtered_result["important_values"] = ivs

        return {
            "issues": issues,
            "filtered_result": filtered_result,
            "is_consistent": len(issues) == 0,
        }

    def check_vlm_result_attribution(
        self,
        vlm_result: Dict[str, Any],
        caption: str = "",
    ) -> Dict[str, Any]:
        if caption:
            attr = self.check_sentence_attribution(caption)
            if not attr["belongs_to_selected"] and attr["confidence"] in ("high", "medium"):
                ev = vlm_result.get("extracted_values", {}) if isinstance(vlm_result, dict) else {}
                has_kinetics_data = any(
                    ev.get(k) is not None for k in ("Km", "Vmax", "kcat", "kcat_Km")
                ) if isinstance(ev, dict) else False
                if has_kinetics_data:
                    return {
                        "valid": True,
                        "reason": f"caption_uncertain_but_has_kinetics:{attr['reason']}",
                        "confidence": "low",
                        "needs_review": True,
                    }
                return {
                    "valid": False,
                    "reason": f"caption_not_about_selected:{attr['reason']}",
                    "confidence": attr["confidence"],
                }
        return {"valid": True, "reason": "caption_attribution_ok", "confidence": "high"}

    def get_warnings(self) -> List[str]:
        return list(dict.fromkeys(self.warnings))

    def get_attribution_log(self) -> List[Dict[str, Any]]:
        return self.attribution_log
