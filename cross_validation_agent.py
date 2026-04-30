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
                if result.get("final_value") is not None and kin.get(param) is None:
                    kin[param] = result["final_value"]
                    if result.get("final_unit"):
                        kin[f"{param}_unit"] = result["final_unit"]
                    if result.get("source"):
                        kin["source"] = result["source"]
                    if result.get("needs_review"):
                        kin["needs_review"] = True
                elif result.get("final_value") is not None and kin.get(param) is not None:
                    if result["source"] != "rule" and result.get("reason", "").startswith("truncation"):
                        kin[param] = result["final_value"]
                        if result.get("final_unit"):
                            kin[f"{param}_unit"] = result["final_unit"]
                        kin["needs_review"] = True
                    elif result["source"] != "rule" and result.get("reason", "") == "rule_outside_magnitude_range":
                        kin[param] = result["final_value"]
                        if result.get("final_unit"):
                            kin[f"{param}_unit"] = result["final_unit"]
                        kin["needs_review"] = True
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
                for key in ("morphology", "composition", "stability", "dopants_or_defects", "characterization"):
                    if sel.get(key) is None and llm_sel.get(key) is not None:
                        sel[key] = llm_sel[key]
                llm_synth = llm_sel.get("synthesis_conditions", {})
                if isinstance(llm_synth, dict):
                    synth = sel.get("synthesis_conditions", {})
                    if not isinstance(synth, dict):
                        synth = {}
                        sel["synthesis_conditions"] = synth
                    for key in ("temperature", "time", "method_detail"):
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
                if act.get("assay_method") is None and llm_act.get("assay_method") is not None:
                    act["assay_method"] = llm_act["assay_method"]
                if act.get("mechanism") is None and llm_act.get("mechanism") is not None:
                    act["mechanism"] = llm_act["mechanism"]
                llm_cond = llm_act.get("conditions", {})
                if isinstance(llm_cond, dict):
                    cond = act.get("conditions", {})
                    for key in ("buffer", "pH", "temperature", "reaction_time"):
                        if cond.get(key) is None and llm_cond.get(key) is not None:
                            cond[key] = llm_cond[key]
                llm_ph = llm_act.get("pH_profile", {})
                if isinstance(llm_ph, dict):
                    ph = act.get("pH_profile", {})
                    for key in ("optimal_pH", "pH_range", "pH_stability_range"):
                        if ph.get(key) is None and llm_ph.get(key) is not None:
                            ph[key] = llm_ph[key]
                llm_temp = llm_act.get("temperature_profile", {})
                if isinstance(llm_temp, dict):
                    tp = act.get("temperature_profile", {})
                    for key in ("optimal_temperature", "temperature_range", "thermal_stability"):
                        if tp.get(key) is None and llm_temp.get(key) is not None:
                            tp[key] = llm_temp[key]

            llm_apps = llm_result.get("applications", [])
            if isinstance(llm_apps, list):
                for llm_app in llm_apps:
                    if not isinstance(llm_app, dict):
                        continue
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
                fig_kin = vlm_r.get("kinetics", {})
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

                particle_size = vlm_r.get("particle_size")
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

                sensing = vlm_r.get("sensing_performance")
                if isinstance(sensing, dict):
                    self._merge_vlm_sensing_into_applications(record, sensing)

                other_vals = vlm_r.get("other_values", [])
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
