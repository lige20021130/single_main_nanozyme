import re
import copy
import logging
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

_MAGNITUDE_RANGES = {
    "Km": (1e-12, 10.0),
    "Vmax": (1e-15, 1e8),
    "kcat": (1e-6, 1e10),
    "kcat_Km": (1e-3, 1e12),
}


def _to_float(val):
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        val = val.strip()
        try:
            return float(val)
        except ValueError:
            pass
        m = re.match(r'([\d.]+)\s*[×x\u00d7]\s*10[\u207b\u2212\u2013\-]?\s*(\d+)', val)
        if m:
            base = float(m.group(1))
            exp = int(m.group(2))
            has_neg = bool(re.search(r'10[\u207b\u2212\u2013\-]', val))
            if has_neg:
                return base * (10 ** -exp)
            return base * (10 ** exp)
        m = re.match(r'([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)', val)
        if m:
            base = float(m.group(1))
            exp = int(m.group(2).replace('−', '-').replace('\u2212', '-'))
            return base * (10 ** exp)
    return None


def _values_agree(val1, val2, tolerance=0.5):
    if val1 is None or val2 is None:
        return False
    f1, f2 = _to_float(val1), _to_float(val2)
    if f1 is None or f2 is None:
        return False
    if f1 == 0 and f2 == 0:
        return True
    denom = max(abs(f1), abs(f2))
    if denom == 0:
        return True
    return abs(f1 - f2) / denom <= tolerance


class CrossValidationAgent:
    def detect_truncation(self, rule_val, llm_val) -> bool:
        if rule_val is None or llm_val is None:
            return False
        f_rule = _to_float(rule_val)
        f_llm = _to_float(llm_val)
        if f_rule is None or f_llm is None:
            return False
        if f_rule == f_llm:
            return False
        rule_str = f"{abs(f_rule):.6f}"
        llm_sci = f"{abs(f_llm):.6e}"
        llm_mantissa = llm_sci.split('e')[0] if 'e' in llm_sci else llm_sci
        if len(rule_str) >= 4 and llm_mantissa.startswith(rule_str[:4]):
            return True
        if len(llm_mantissa) >= 4 and rule_str.startswith(llm_mantissa[:4]):
            return True
        if f_rule >= 1 and f_llm < 1:
            rule_int_part = str(int(f_rule))
            llm_int_part = str(int(abs(f_llm)))
            if rule_int_part.startswith(llm_int_part) and len(rule_int_part) <= len(llm_int_part) + 1:
                ratio = f_rule / f_llm if f_llm != 0 else 0
                if ratio > 1e4 or ratio < 1e-4:
                    return True
        return False

    def validate_kinetics(self, rule_val, llm_val, vlm_val, param_name, rule_unit=None, llm_unit=None) -> Dict[str, Any]:
        sources = []
        if rule_val is not None:
            f = _to_float(rule_val)
            if f is not None:
                sources.append(("rule", f, rule_unit))
        if llm_val is not None:
            f = _to_float(llm_val)
            if f is not None:
                sources.append(("llm", f, llm_unit))
        if vlm_val is not None:
            f = _to_float(vlm_val)
            if f is not None:
                sources.append(("vlm", f, None))

        if not sources:
            return {"final_value": None, "final_unit": None, "confidence": "low", "needs_review": True, "source": "none", "reason": "no_source"}

        if len(sources) == 1:
            src, val, unit = sources[0]
            conf = "medium" if src == "rule" else "low"
            return {"final_value": val, "final_unit": unit, "confidence": conf, "needs_review": src != "rule", "source": src, "reason": "single_source"}

        mag_range = _MAGNITUDE_RANGES.get(param_name)
        rule_entry = next((s for s in sources if s[0] == "rule"), None)
        llm_entry = next((s for s in sources if s[0] == "llm"), None)

        if len(sources) == 2:
            s1, s2 = sources[0], sources[1]
            if _values_agree(s1[1], s2[1]):
                preferred = s1 if s1[0] == "rule" else s2 if s2[0] == "rule" else s1
                return {"final_value": preferred[1], "final_unit": preferred[2], "confidence": "high", "needs_review": False, "source": preferred[0], "reason": "two_sources_agree"}

            if rule_entry and llm_entry and self.detect_truncation(rule_entry[1], llm_entry[1]):
                return {"final_value": llm_entry[1], "final_unit": llm_entry[2] or rule_entry[2], "confidence": "medium", "needs_review": True, "source": "llm", "reason": "truncation_detected"}

            if mag_range and rule_entry and llm_entry:
                rule_in = mag_range[0] <= abs(rule_entry[1]) <= mag_range[1]
                llm_in = mag_range[0] <= abs(llm_entry[1]) <= mag_range[1]
                if not rule_in and llm_in:
                    return {"final_value": llm_entry[1], "final_unit": llm_entry[2] or rule_entry[2], "confidence": "medium", "needs_review": True, "source": "llm", "reason": "rule_outside_magnitude_range"}

            preferred = rule_entry if rule_entry else sources[0]
            alt_entry = llm_entry if llm_entry and llm_entry != preferred else next((s for s in sources if s != preferred), None)
            result = {"final_value": preferred[1], "final_unit": preferred[2], "confidence": "low", "needs_review": True, "source": preferred[0], "reason": "conflict_unresolved"}
            if alt_entry:
                result["_alternative"] = {"value": alt_entry[1], "unit": alt_entry[2], "source": alt_entry[0]}
            return result

        if len(sources) == 3:
            vals = [s[1] for s in sources]
            all_agree = all(_values_agree(vals[0], v) for v in vals[1:])
            if all_agree:
                return {"final_value": rule_entry[1] if rule_entry else sources[0][1], "final_unit": rule_entry[2] if rule_entry else sources[0][2], "confidence": "high", "needs_review": False, "source": "rule", "reason": "three_sources_agree"}

            pair_agree = None
            for i in range(len(sources)):
                for j in range(i + 1, len(sources)):
                    if _values_agree(sources[i][1], sources[j][1]):
                        pair_agree = (sources[i], sources[j])
                        break
                if pair_agree:
                    break

            if pair_agree:
                preferred = next((s for s in pair_agree if s[0] == "rule"), pair_agree[0])
                return {"final_value": preferred[1], "final_unit": preferred[2], "confidence": "high", "needs_review": False, "source": preferred[0], "reason": "pair_agree"}

            if rule_entry and llm_entry and self.detect_truncation(rule_entry[1], llm_entry[1]):
                return {"final_value": llm_entry[1], "final_unit": llm_entry[2] or rule_entry[2], "confidence": "medium", "needs_review": True, "source": "llm", "reason": "truncation_detected_3src"}

            preferred = rule_entry if rule_entry else sources[0]
            result = {"final_value": preferred[1], "final_unit": preferred[2], "confidence": "low", "needs_review": True, "source": preferred[0], "reason": "conflict_unresolved_3src"}
            alts = [{"value": s[1], "unit": s[2], "source": s[0]} for s in sources if s != preferred]
            if alts:
                result["_alternatives"] = alts
            return result

        return {"final_value": None, "final_unit": None, "confidence": "low", "needs_review": True, "source": "none", "reason": "unexpected"}

    def validate_kinetics_set(self, record, llm_kinetics, vlm_kinetics) -> Dict[str, Dict]:
        results = {}
        kin = record.get("main_activity", {}).get("kinetics", {})
        for param in ("Km", "Vmax", "kcat", "kcat_Km"):
            rule_val = kin.get(param)
            rule_unit = kin.get(f"{param}_unit")
            llm_val = llm_kinetics.get(param) if llm_kinetics else None
            llm_unit = llm_kinetics.get(f"{param}_unit") if llm_kinetics else None
            vlm_val = vlm_kinetics.get(param) if vlm_kinetics else None
            results[param] = self.validate_kinetics(rule_val, llm_val, vlm_val, param, rule_unit, llm_unit)
        return results

    def merge_results(self, record, llm_result, vlm_results) -> Dict:
        record = copy.deepcopy(record)

        llm_kinetics = {}
        if llm_result:
            llm_act = llm_result.get("main_activity", {})
            if isinstance(llm_act, dict):
                llm_kin = llm_act.get("kinetics", {})
                if isinstance(llm_kin, dict):
                    for k in ("Km", "Vmax", "kcat", "kcat_Km"):
                        v = llm_kin.get(k)
                        if v is not None:
                            llm_kinetics[k] = v
                        llm_k_key = f"_llm_{k}"
                        if llm_k_key in llm_kin:
                            llm_kinetics[k] = llm_kin[llm_k_key]
                        llm_u_key = f"_llm_{k}_unit"
                        if llm_u_key in llm_kin:
                            llm_kinetics[f"{k}_unit"] = llm_kin[llm_u_key]

        vlm_kinetics = {}
        if vlm_results:
            for vlm_r in vlm_results:
                if not isinstance(vlm_r, dict):
                    continue
                fig_kin = vlm_r.get("kinetics", {})
                if isinstance(fig_kin, dict):
                    for k in ("Km", "Vmax", "kcat", "kcat_Km"):
                        v = fig_kin.get(k)
                        if v is not None and k not in vlm_kinetics:
                            vlm_kinetics[k] = v
                            u = fig_kin.get(f"{k}_unit")
                            if u:
                                vlm_kinetics[f"{k}_unit"] = u

        if llm_kinetics or vlm_kinetics:
            validation = self.validate_kinetics_set(record, llm_kinetics, vlm_kinetics)
            kin = record["main_activity"]["kinetics"]
            for param, result in validation.items():
                if result.get("final_value") is not None:
                    should_apply = False
                    if kin.get(param) is None:
                        should_apply = True
                    elif result.get("confidence") == "high":
                        should_apply = True
                    elif result.get("reason", "").startswith("truncation"):
                        should_apply = True
                    elif result.get("reason", "") == "rule_outside_magnitude_range":
                        should_apply = True
                    if should_apply:
                        kin[param] = result["final_value"]
                        if result.get("final_unit"):
                            kin[f"{param}_unit"] = result["final_unit"]
                        if result.get("source"):
                            kin["source"] = result["source"]
                        if result.get("needs_review"):
                            kin["needs_review"] = True
                        if result.get("confidence"):
                            kin[f"_confidence_{param}"] = result["confidence"]
                        if result.get("reason"):
                            kin[f"_reason_{param}"] = result["reason"]
                    if not should_apply and kin.get(param) is not None:
                        if result.get("_alternative") or result.get("_alternatives"):
                            alts = result.get("_alternatives", [])
                            if result.get("_alternative"):
                                alts = [result["_alternative"]]
                            for alt in alts:
                                kin[f"_llm_{param}_alternative"] = alt["value"]
                                record.setdefault("important_values", []).append({
                                    "name": f"{param}_alternative",
                                    "value": alt["value"],
                                    "unit": alt.get("unit"),
                                    "source": alt.get("source"),
                                    "needs_review": True,
                                    "context": f"Cross-validation: {result.get('reason', 'conflict')}"
                                })

        if llm_result:
            llm_sel = llm_result.get("selected_nanozyme", {})
            if isinstance(llm_sel, dict):
                sel = record["selected_nanozyme"]
                for key in ("morphology", "composition", "characterization"):
                    if sel.get(key) is None and llm_sel.get(key) is not None:
                        sel[key] = llm_sel[key]
                llm_synth = llm_sel.get("synthesis_conditions", {})
                if isinstance(llm_synth, dict):
                    synth = sel.get("synthesis_conditions", {})
                    if not isinstance(synth, dict):
                        synth = {}
                        sel["synthesis_conditions"] = synth
                    for key in ("temperature", "time"):
                        if synth.get(key) is None and llm_synth.get(key) is not None:
                            synth[key] = llm_synth[key]
                    if not synth.get("precursors") and llm_synth.get("precursors"):
                        synth["precursors"] = llm_synth["precursors"]

            llm_act = llm_result.get("main_activity", {})
            if isinstance(llm_act, dict):
                act = record["main_activity"]
                if act.get("enzyme_like_type") is None and llm_act.get("enzyme_like_type") is not None:
                    act["enzyme_like_type"] = llm_act["enzyme_like_type"]
                if not act.get("substrates") and llm_act.get("substrates"):
                    act["substrates"] = llm_act["substrates"]
                if act.get("mechanism") is None and llm_act.get("mechanism") is not None:
                    act["mechanism"] = llm_act["mechanism"]
                llm_cond = llm_act.get("conditions", {})
                if isinstance(llm_cond, dict):
                    cond = act.get("conditions", {})
                    for key in ("pH", "temperature"):
                        if cond.get(key) is None and llm_cond.get(key) is not None:
                            cond[key] = llm_cond[key]
                llm_ph = llm_act.get("pH_profile", {})
                if isinstance(llm_ph, dict):
                    ph = act.get("pH_profile", {})
                    for key in ("optimal_pH", "pH_range"):
                        if ph.get(key) is None and llm_ph.get(key) is not None:
                            ph[key] = llm_ph[key]
                llm_temp = llm_act.get("temperature_profile", {})
                if isinstance(llm_temp, dict):
                    tp = act.get("temperature_profile", {})
                    for key in ("optimal_temperature", "temperature_range"):
                        if tp.get(key) is None and llm_temp.get(key) is not None:
                            tp[key] = llm_temp[key]

            llm_apps = llm_result.get("applications", [])
            if isinstance(llm_apps, list):
                from application_extractor import is_valid_analyte
                for llm_app in llm_apps:
                    if not isinstance(llm_app, dict):
                        continue
                    if llm_app.get("target_analyte") and not is_valid_analyte(llm_app["target_analyte"] or ""):
                        llm_app["target_analyte"] = None
                    existing = record.get("applications", [])
                    is_dup = False
                    for ex in existing:
                        if (ex.get("application_type") == llm_app.get("application_type") and
                            (ex.get("target_analyte") or "").lower() == (llm_app.get("target_analyte") or "").lower()):
                            is_dup = True
                            for k in ("detection_limit", "linear_range", "method", "sample_type", "notes"):
                                if ex.get(k) is None and llm_app.get(k) is not None:
                                    ex[k] = llm_app[k]
                            break
                    if not is_dup:
                        record.setdefault("applications", []).append(llm_app)

        if vlm_results:
            for vlm_r in vlm_results:
                if not isinstance(vlm_r, dict):
                    continue
                ev = vlm_r.get("extracted_values", {})
                if not isinstance(ev, dict):
                    ev = {}
                fig_kin = {}
                for param in ("Km", "Vmax", "kcat", "kcat_Km"):
                    items = ev.get(param, [])
                    if isinstance(items, list) and items:
                        best = items[0] if isinstance(items[0], dict) else {"value": items[0]}
                        if best.get("value") is not None:
                            fig_kin[param] = best["value"]
                            fig_kin[f"{param}_unit"] = best.get("unit")
                    elif isinstance(items, dict) and items.get("value") is not None:
                        fig_kin[param] = items["value"]
                        fig_kin[f"{param}_unit"] = items.get("unit")
                if isinstance(fig_kin, dict):
                    for param in ("Km", "Vmax", "kcat", "kcat_Km"):
                        v = fig_kin.get(param)
                        if v is not None:
                            f = _to_float(v)
                            if f is not None:
                                record.setdefault("important_values", []).append({
                                    "name": f"VLM_{param}",
                                    "value": f,
                                    "unit": fig_kin.get(f"{param}_unit"),
                                    "source": "VLM",
                                    "needs_review": True,
                                    "context": vlm_r.get("_source_caption", ""),
                                })

                particle_size = ev.get("particle_size")
                if particle_size and record["selected_nanozyme"].get("size") is None:
                    if isinstance(particle_size, dict):
                        record["selected_nanozyme"]["size"] = particle_size.get("value")
                        record["selected_nanozyme"]["size_unit"] = particle_size.get("unit", "nm")
                    elif isinstance(particle_size, (int, float)):
                        record["selected_nanozyme"]["size"] = particle_size
                        record["selected_nanozyme"]["size_unit"] = "nm"

                observations = vlm_r.get("observations")
                if observations and record["selected_nanozyme"].get("morphology") is None:
                    if isinstance(observations, list):
                        record["selected_nanozyme"]["morphology"] = "; ".join(str(o) for o in observations[:3])
                    elif isinstance(observations, str):
                        record["selected_nanozyme"]["morphology"] = observations

                sensing = ev.get("sensing_performance")
                if isinstance(sensing, dict):
                    self._merge_vlm_sensing_into_applications(record, sensing)

                other_vals = ev.get("other_values", [])
                if isinstance(other_vals, list):
                    for ov in other_vals:
                        if isinstance(ov, dict):
                            record.setdefault("important_values", []).append({
                                "name": ov.get("name", "VLM_value"),
                                "value": ov.get("value"),
                                "unit": ov.get("unit"),
                                "source": "VLM",
                                "needs_review": True,
                            })

        return record

    def _merge_vlm_sensing_into_applications(self, record, sensing):
        if not isinstance(sensing, dict):
            return
        apps = record.get("applications", [])
        lod = sensing.get("LOD") or sensing.get("detection_limit")
        lr = sensing.get("linear_range")
        analyte = sensing.get("target_analyte")
        method = sensing.get("method")
        if analyte:
            from application_extractor import is_valid_analyte
            if not is_valid_analyte(str(analyte)):
                analyte = None
        if not lod and not lr and not analyte:
            return
        matched = False
        for app in apps:
            if analyte and (app.get("target_analyte") or "").lower() == str(analyte).lower():
                if lod and app.get("detection_limit") is None:
                    app["detection_limit"] = str(lod)
                if lr and app.get("linear_range") is None:
                    app["linear_range"] = str(lr)
                if method and app.get("method") is None:
                    app["method"] = method
                matched = True
                break
        if not matched:
            new_app = {
                "application_type": "detection",
                "target_analyte": str(analyte) if analyte else None,
                "method": method,
                "detection_limit": str(lod) if lod else None,
                "linear_range": str(lr) if lr else None,
                "sample_type": None,
                "notes": "from VLM sensing_performance",
            }
            apps.append(new_app)
            record["applications"] = apps

    @staticmethod
    def _build_match_key(entry: Dict) -> Tuple:
        sub = (entry.get("substrate") or "").strip().lower()
        mv = (entry.get("material_variant") or "").strip().lower()
        dm = (entry.get("detection_method") or "").strip().lower()
        return (sub, mv, dm)

    def _merge_kinetics_entry(self, rule_entry: Optional[Dict], llm_entry: Optional[Dict], vlm_entry: Optional[Dict]) -> Dict:
        merged = {}
        sources_used = []
        if rule_entry:
            merged.update(rule_entry)
            sources_used.append("rule")
        if llm_entry:
            for k, v in llm_entry.items():
                if v is not None and merged.get(k) is None:
                    merged[k] = v
            sources_used.append("llm")
        if vlm_entry:
            for k, v in vlm_entry.items():
                if v is not None and merged.get(k) is None:
                    merged[k] = v
            sources_used.append("vlm")

        for param in ("Km", "Vmax", "kcat", "kcat_Km"):
            rule_val = rule_entry.get(param) if rule_entry else None
            rule_unit = rule_entry.get(f"{param}_unit") if rule_entry else None
            llm_val = llm_entry.get(param) if llm_entry else None
            llm_unit = llm_entry.get(f"{param}_unit") if llm_entry else None
            vlm_val = vlm_entry.get(param) if vlm_entry else None
            vlm_unit = vlm_entry.get(f"{param}_unit") if vlm_entry else None

            result = self.validate_kinetics(rule_val, llm_val, vlm_val, param, rule_unit, llm_unit)
            if result.get("final_value") is not None:
                merged[param] = result["final_value"]
                if result.get("final_unit"):
                    merged[f"{param}_unit"] = result["final_unit"]
                merged[f"_confidence_{param}"] = result.get("confidence", "low")
                merged[f"_reason_{param}"] = result.get("reason", "")
                if result.get("source"):
                    merged["source"] = result["source"]
                if result.get("needs_review"):
                    merged["needs_review"] = True
                if result.get("_alternative"):
                    merged[f"_llm_{param}_alternative"] = result["_alternative"]["value"]
            elif rule_val is not None:
                merged[param] = rule_val
                merged[f"{param}_unit"] = rule_unit

        if not merged.get("source"):
            merged["source"] = "+".join(sources_used) if sources_used else "unknown"
        if len(sources_used) >= 2:
            merged["_cross_validated"] = True
        return merged

    def validate_kinetics_list(
        self,
        rule_list: List[Dict],
        llm_list: List[Dict],
        vlm_list: List[Dict],
    ) -> List[Dict]:
        rule_map = {}
        for entry in rule_list:
            if not isinstance(entry, dict):
                continue
            key = self._build_match_key(entry)
            rule_map[key] = entry

        llm_map = {}
        for entry in llm_list:
            if not isinstance(entry, dict):
                continue
            key = self._build_match_key(entry)
            if key not in llm_map:
                llm_map[key] = entry
            else:
                for k, v in entry.items():
                    if v is not None and llm_map[key].get(k) is None:
                        llm_map[key][k] = v

        vlm_map = {}
        for entry in vlm_list:
            if not isinstance(entry, dict):
                continue
            key = self._build_match_key(entry)
            if key not in vlm_map:
                vlm_map[key] = entry
            else:
                for k, v in entry.items():
                    if v is not None and vlm_map[key].get(k) is None:
                        vlm_map[key][k] = v

        all_keys = list(dict.fromkeys(list(rule_map.keys()) + list(llm_map.keys()) + list(vlm_map.keys())))
        merged_list = []
        for key in all_keys:
            r = rule_map.get(key)
            l = llm_map.get(key)
            v = vlm_map.get(key)
            merged = self._merge_kinetics_entry(r, l, v)
            merged_list.append(merged)

        rule_primary = None
        for entry in rule_list:
            if isinstance(entry, dict) and entry.get("substrate") and not entry.get("material_variant"):
                rule_primary = entry
                break
        if rule_primary:
            pk = self._build_match_key(rule_primary)
            for i, entry in enumerate(merged_list):
                if self._build_match_key(entry) == pk:
                    merged_list.insert(0, merged_list.pop(i))
                    break

        logger.info(
            f"[CVA] validate_kinetics_list: rule={len(rule_map)}, llm={len(llm_map)}, "
            f"vlm={len(vlm_map)}, merged={len(merged_list)}"
        )
        return merged_list

    def validate_sensing_performance(
        self,
        rule_apps: List[Dict],
        vlm_sensing: Dict,
    ) -> List[Dict]:
        if not isinstance(vlm_sensing, dict):
            return rule_apps

        def _flatten_sensing_val(val):
            if val is None:
                return None
            if isinstance(val, dict):
                v = val.get("value")
                u = val.get("unit")
                if v is not None and u is not None:
                    return f"{v} {u}"
                return str(v) if v is not None else None
            return str(val)

        vlm_lod = _flatten_sensing_val(vlm_sensing.get("LOD") or vlm_sensing.get("detection_limit"))
        vlm_lr = _flatten_sensing_val(vlm_sensing.get("linear_range"))
        vlm_analyte = vlm_sensing.get("target_analyte")
        vlm_method = vlm_sensing.get("method")

        if vlm_analyte:
            from application_extractor import is_valid_analyte
            if not is_valid_analyte(str(vlm_analyte)):
                vlm_analyte = None

        if not vlm_lod and not vlm_lr and not vlm_analyte:
            return rule_apps

        result_apps = copy.deepcopy(rule_apps)
        matched = False
        for app in result_apps:
            if not isinstance(app, dict):
                continue
            is_sensing = app.get("application_type") in ("sensing", "biosensing", "detection")
            analyte_match = vlm_analyte and (app.get("target_analyte") or "").lower() == str(vlm_analyte).lower()
            if vlm_analyte and analyte_match:
                matched = True
            elif not vlm_analyte and is_sensing:
                matched = True
            else:
                continue
            if vlm_lod and app.get("detection_limit") is None:
                app["detection_limit"] = str(vlm_lod)
                app["_lod_source"] = "VLM"
                app["_lod_confidence"] = "low"
            elif vlm_lod and app.get("detection_limit"):
                rule_lod_str = str(app["detection_limit"])
                try:
                    rule_lod_val = float(re.sub(r'[^\d.]', '', rule_lod_str.split()[0]) if rule_lod_str else '0')
                    vlm_lod_val = float(re.sub(r'[^\d.]', '', str(vlm_lod).split()[0]))
                    if rule_lod_val > 0 and vlm_lod_val > 0:
                        rel_diff = abs(rule_lod_val - vlm_lod_val) / max(rule_lod_val, vlm_lod_val)
                        if rel_diff < 0.3:
                            app["_lod_confidence"] = "high"
                            app["_lod_cross_validated"] = True
                        else:
                            app["_lod_confidence"] = "low"
                            app["_vlm_lod_alternative"] = str(vlm_lod)
                except (ValueError, IndexError):
                    pass
            if vlm_lr and app.get("linear_range") is None:
                app["linear_range"] = str(vlm_lr)
                app["_lr_source"] = "VLM"
            if vlm_method and app.get("method") is None:
                app["method"] = vlm_method
            break

        if not matched and (vlm_lod or vlm_lr or vlm_analyte):
            new_app = {
                "application_type": "detection",
                "target_analyte": str(vlm_analyte) if vlm_analyte else None,
                "method": vlm_method,
                "detection_limit": str(vlm_lod) if vlm_lod else None,
                "linear_range": str(vlm_lr) if vlm_lr else None,
                "sample_type": None,
                "notes": "from VLM sensing_performance",
                "_lod_source": "VLM" if vlm_lod else None,
                "_lod_confidence": "low" if vlm_lod else None,
            }
            result_apps.append(new_app)

        return result_apps

    def check_multi_figure_kinetics_consistency(self, vlm_results) -> List[Dict[str, Any]]:
        if not vlm_results or len(vlm_results) < 2:
            return []
        figure_kinetics = []
        for vlm_r in vlm_results:
            if not isinstance(vlm_r, dict):
                continue
            ev = vlm_r.get("extracted_values", {})
            if not isinstance(ev, dict):
                ev = {}
            fig_data = {"caption": vlm_r.get("_source_caption", "")}
            for param in ("Km", "Vmax", "kcat", "kcat_Km"):
                items = ev.get(param, [])
                val = None
                unit = None
                if isinstance(items, list) and items:
                    best = items[0] if isinstance(items[0], dict) else {"value": items[0]}
                    val = _to_float(best.get("value")) if isinstance(best, dict) else _to_float(items[0])
                    unit = best.get("unit") if isinstance(best, dict) else None
                elif isinstance(items, dict) and items.get("value") is not None:
                    val = _to_float(items["value"])
                    unit = items.get("unit")
                if val is not None:
                    fig_data[param] = val
                    fig_data[f"{param}_unit"] = unit
            if any(k in fig_data for k in ("Km", "Vmax", "kcat", "kcat_Km")):
                figure_kinetics.append(fig_data)
        if len(figure_kinetics) < 2:
            return []
        inconsistencies = []
        for param in ("Km", "Vmax", "kcat", "kcat_Km"):
            values = []
            for fk in figure_kinetics:
                if param in fk:
                    values.append((fk[param], fk.get(f"{param}_unit"), fk.get("caption", "")))
            if len(values) < 2:
                continue
            for i in range(len(values)):
                for j in range(i + 1, len(values)):
                    v1, u1, c1 = values[i]
                    v2, u2, c2 = values[j]
                    if v1 is None or v2 is None:
                        continue
                    denom = max(abs(v1), abs(v2))
                    if denom == 0:
                        continue
                    rel_diff = abs(v1 - v2) / denom
                    if rel_diff > 0.3:
                        inconsistencies.append({
                            "parameter": param,
                            "figure_1_value": v1,
                            "figure_1_unit": u1,
                            "figure_1_caption": c1[:100],
                            "figure_2_value": v2,
                            "figure_2_unit": u2,
                            "figure_2_caption": c2[:100],
                            "relative_difference": round(rel_diff, 3),
                            "severity": "high" if rel_diff > 0.5 else "medium",
                        })
        return inconsistencies
