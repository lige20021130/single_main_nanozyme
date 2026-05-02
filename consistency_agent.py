import re
import copy
import logging
from typing import Dict, List, Any, Tuple

logger = logging.getLogger(__name__)

_ALIASES_TO_CANONICAL = {
    "peroxidase_like": "peroxidase-like",
    "peroxidase-like": "peroxidase-like",
    "peroxidase like": "peroxidase-like",
    "pod-like": "peroxidase-like",
    "pod_like": "peroxidase-like",
    "oxidase_like": "oxidase-like",
    "oxidase-like": "oxidase-like",
    "oxidase like": "oxidase-like",
    "oxd-like": "oxidase-like",
    "oxd_like": "oxidase-like",
    "catalase_like": "catalase-like",
    "catalase-like": "catalase-like",
    "catalase like": "catalase-like",
    "cat-like": "catalase-like",
    "cat_like": "catalase-like",
    "superoxide_dismutase_like": "superoxide-dismutase-like",
    "superoxide-dismutase-like": "superoxide-dismutase-like",
    "sod-like": "superoxide-dismutase-like",
    "sod_like": "superoxide-dismutase-like",
    "glucose_oxidase_like": "glucose-oxidase-like",
    "glucose-oxidase-like": "glucose-oxidase-like",
    "gox-like": "glucose-oxidase-like",
    "gox_like": "glucose-oxidase-like",
    "glutathione_peroxidase_like": "glutathione-peroxidase-like",
    "glutathione-peroxidase-like": "glutathione-peroxidase-like",
    "gpx-like": "glutathione-peroxidase-like",
    "gpx_like": "glutathione-peroxidase-like",
    "glutathione_oxidase_like": "glutathione-oxidase-like",
    "glutathione-oxidase-like": "glutathione-oxidase-like",
    "gshox-like": "glutathione-oxidase-like",
    "gshox_like": "glutathione-oxidase-like",
    "laccase_like": "laccase-like",
    "laccase-like": "laccase-like",
    "phosphatase_like": "phosphatase-like",
    "phosphatase-like": "phosphatase-like",
    "alp-like": "phosphatase-like",
    "alp_like": "phosphatase-like",
    "esterase_like": "esterase-like",
    "esterase-like": "esterase-like",
    "nuclease_like": "nuclease-like",
    "nuclease-like": "nuclease-like",
    "nitroreductase_like": "nitroreductase-like",
    "nitroreductase-like": "nitroreductase-like",
    "ntr-like": "nitroreductase-like",
    "ntr_like": "nitroreductase-like",
    "hydrolase_like": "hydrolase-like",
    "hydrolase-like": "hydrolase-like",
    "haloperoxidase_like": "haloperoxidase-like",
    "haloperoxidase-like": "haloperoxidase-like",
    "tyrosinase_like": "tyrosinase-like",
    "tyrosinase-like": "tyrosinase-like",
    "cascade_enzymatic": "cascade-enzymatic",
    "cascade-enzymatic": "cascade-enzymatic",
}

_NANO_SUFFIXES = re.compile(
    r'\s+'
    r'(?:nanoparticles?|NPs?|nanosheets?|nanocubes?|nanorods?|nanoclusters?|'
    r'nanozymes?|nanocomposites?|nanospheres?|nanoflowers?|nanowires?|'
    r'nanotubes?|nanostars?|nanobelts?|nanoplates?|nanodots?|'
    r'nanostructures?|nanomaterials?|nanoplates?)'
    r'\s*$',
    re.I
)

_CONCENTRATION_UNITS = {"mM", "μM", "uM", "M", "nM", "pM", "mmol/L", "umol/L", "nmol/L", "mol/L"}
_RATE_UNITS = {"M/s", "mM/s", "μM/s", "M^-1 s^-1", "M min^-1", "mM min^-1", "M s^-1", "mM s^-1"}


def _is_concentration_unit(unit):
    if not unit:
        return False
    u = unit.strip().lower().replace(" ", "").replace("^-1", "").replace("⁻¹", "")
    return any(u.startswith(p) for p in ("mm", "μm", "um", "nm", "pm", "mol"))


def _is_rate_unit(unit):
    if not unit:
        return False
    u = unit.strip().lower().replace(" ", "")
    return any(kw in u for kw in ("/s", "s^-1", "s⁻¹", "/min", "min^-1", "min⁻¹", "·s", "s-1"))


class ConsistencyAgent:
    def normalize_output(self, record: Dict) -> Tuple[Dict, List[str]]:
        record = copy.deepcopy(record)
        warnings = []
        record, w1 = self.normalize_enzyme_types(record)
        warnings.extend(w1)
        record, w2 = self.normalize_all_units(record)
        warnings.extend(w2)
        record, w3 = self.normalize_material_name(record)
        warnings.extend(w3)
        record, w4 = self.deduplicate_applications(record)
        warnings.extend(w4)
        record, w5 = self.check_cross_field_consistency(record)
        warnings.extend(w5)
        record, w6 = self.check_kinetics_substrate_consistency(record)
        warnings.extend(w6)
        record, w7 = self.check_application_enzyme_consistency(record)
        warnings.extend(w7)
        return record, warnings

    def normalize_enzyme_types(self, record: Dict) -> Tuple[Dict, List[str]]:
        warnings = []
        act = record.get("main_activity", {})
        if not isinstance(act, dict):
            return record, warnings
        etype = act.get("enzyme_like_type")
        if etype and isinstance(etype, str):
            canonical = _ALIASES_TO_CANONICAL.get(etype)
            if not canonical:
                lower = etype.lower().replace(" ", "_")
                canonical = _ALIASES_TO_CANONICAL.get(lower)
            if not canonical:
                lower2 = etype.lower().replace(" ", "-")
                canonical = _ALIASES_TO_CANONICAL.get(lower2)
            if canonical and canonical != etype:
                act["enzyme_like_type"] = canonical
                warnings.append(f"enzyme_type_normalized: {etype} -> {canonical}")
            elif etype and "_" in etype:
                hyphen = etype.replace("_", "-")
                act["enzyme_like_type"] = hyphen
                warnings.append(f"enzyme_type_underscore_to_hyphen: {etype} -> {hyphen}")
        return record, warnings

    def normalize_all_units(self, record: Dict) -> Tuple[Dict, List[str]]:
        warnings = []
        try:
            from numeric_validator import normalize_unit
        except ImportError:
            return record, warnings

        kin = record.get("main_activity", {}).get("kinetics", {})
        if isinstance(kin, dict):
            for key in ("Km_unit", "Vmax_unit", "kcat_unit", "kcat_Km_unit"):
                u = kin.get(key)
                if u and isinstance(u, str):
                    nu = normalize_unit(u)
                    if nu != u:
                        kin[key] = nu
                        warnings.append(f"unit_normalized: {key} {u} -> {nu}")

        sel = record.get("selected_nanozyme", {})
        if isinstance(sel, dict):
            u = sel.get("size_unit")
            if u and isinstance(u, str):
                nu = normalize_unit(u)
                if nu != u:
                    sel["size_unit"] = nu

        for app in record.get("applications", []):
            if not isinstance(app, dict):
                continue
            for key in ("detection_limit_unit", "linear_range_unit"):
                u = app.get(key)
                if u and isinstance(u, str):
                    nu = normalize_unit(u)
                    if nu != u:
                        app[key] = nu

        return record, warnings

    def normalize_material_name(self, record: Dict) -> Tuple[Dict, List[str]]:
        warnings = []
        sel = record.get("selected_nanozyme", {})
        if not isinstance(sel, dict):
            return record, warnings
        name = sel.get("name")
        if not name or not isinstance(name, str):
            return record, warnings
        cleaned = _NANO_SUFFIXES.sub("", name).strip()
        if cleaned and cleaned != name:
            sel["name"] = cleaned
            warnings.append(f"material_name_cleaned: {name} -> {cleaned}")
        return record, warnings

    def deduplicate_applications(self, record: Dict) -> Tuple[Dict, List[str]]:
        warnings = []
        apps = record.get("applications", [])
        if not apps or not isinstance(apps, list):
            return record, warnings
        seen = {}
        deduped = []
        for app in apps:
            if not isinstance(app, dict):
                deduped.append(app)
                continue
            atype = (app.get("application_type") or "").lower()
            analyte = (app.get("target_analyte") or "").lower()
            key = (atype, analyte)
            if key in seen:
                existing = seen[key]
                for k in ("detection_limit", "linear_range", "method", "sample_type", "notes"):
                    if existing.get(k) is None and app.get(k) is not None:
                        existing[k] = app[k]
                warnings.append(f"application_deduped: {key}")
            else:
                seen[key] = app
                deduped.append(app)
        if len(deduped) < len(apps):
            record["applications"] = deduped
        return record, warnings

    def check_cross_field_consistency(self, record: Dict) -> Tuple[Dict, List[str]]:
        warnings = []
        act = record.get("main_activity", {})
        if not isinstance(act, dict):
            return record, warnings
        kin = act.get("kinetics", {})
        if isinstance(kin, dict):
            km_unit = kin.get("Km_unit", "")
            if km_unit and not _is_concentration_unit(km_unit):
                warnings.append("Km_unit_not_concentration")
                kin["needs_review"] = True
            vmax_unit = kin.get("Vmax_unit", "")
            if vmax_unit and not _is_rate_unit(vmax_unit):
                warnings.append("Vmax_unit_not_rate")
                kin["needs_review"] = True
            kcat = kin.get("kcat")
            km = kin.get("Km")
            if kcat and km and isinstance(kcat, (int, float)) and isinstance(km, (int, float)) and km > 0:
                eff = kcat / km
                if eff < 1e-3 or eff > 1e12:
                    warnings.append(f"kcat_Km_unreasonable: kcat/Km={eff:.2e}")
                    kin["needs_review"] = True

        etype = act.get("enzyme_like_type", "")
        ph_profile = act.get("pH_profile", {})
        if isinstance(ph_profile, dict):
            opt_ph = ph_profile.get("optimal_pH")
            if opt_ph is not None:
                try:
                    ph_val = float(opt_ph)
                    if "catalase-like" in str(etype) and ph_val < 4:
                        warnings.append(f"catalase_like_low_pH: {ph_val}")
                        act.setdefault("needs_review", True)
                    if "peroxidase-like" in str(etype) and ph_val > 9:
                        warnings.append(f"peroxidase_like_high_pH: {ph_val}")
                        act.setdefault("needs_review", True)
                except (ValueError, TypeError):
                    pass

        sel = record.get("selected_nanozyme", {})
        if isinstance(sel, dict):
            synth_method = (sel.get("synthesis_method") or "").lower()
            synth_cond = sel.get("synthesis_conditions", {})
            if isinstance(synth_cond, dict) and synth_cond.get("temperature"):
                try:
                    temp_str = str(synth_cond["temperature"])
                    temp_val = float(re.search(r'([\d.]+)', temp_str).group(1))
                    if ("hydrothermal" in synth_method or "solvothermal" in synth_method) and temp_val < 80:
                        warnings.append(f"hydrothermal_low_temperature: {temp_val}°C")
                    if ("calcination" in synth_method or "annealing" in synth_method) and temp_val < 300:
                        warnings.append(f"calcination_low_temperature: {temp_val}°C")
                except (ValueError, TypeError, AttributeError):
                    pass

        return record, warnings

    def check_kinetics_substrate_consistency(self, record: Dict) -> Tuple[Dict, List[str]]:
        warnings = []
        act = record.get("main_activity", {})
        kin = act.get("kinetics", {})
        if not isinstance(kin, dict):
            return record, warnings
        km_sub = (kin.get("substrate") or "").strip().lower()
        kin_list = act.get("kinetics_list", [])
        if isinstance(kin_list, list) and len(kin_list) > 1:
            substrates = set()
            for entry in kin_list:
                if isinstance(entry, dict):
                    s = (entry.get("substrate") or "").strip().lower()
                    if s:
                        substrates.add(s)
            if len(substrates) > 1:
                warnings.append(f"multiple_kinetics_substrates: {substrates}")
                kin["needs_review"] = True
        return record, warnings

    _ENZYME_APP_COMPATIBILITY = {
        "peroxidase-like": {"sensing", "therapeutic", "antibacterial", "antioxidant", "environmental", "biofilm_inhibition", "other"},
        "oxidase-like": {"sensing", "therapeutic", "antibacterial", "antioxidant", "environmental", "other"},
        "catalase-like": {"therapeutic", "antioxidant", "environmental", "other"},
        "superoxide-dismutase-like": {"therapeutic", "antioxidant", "other"},
        "glutathione-peroxidase-like": {"therapeutic", "antioxidant", "other"},
        "glucose-oxidase-like": {"sensing", "therapeutic", "antibacterial", "environmental", "other"},
        "phosphatase-like": {"sensing", "therapeutic", "environmental", "other"},
        "laccase-like": {"sensing", "environmental", "other"},
        "esterase-like": {"sensing", "environmental", "other"},
        "nitroreductase-like": {"sensing", "therapeutic", "antibacterial", "other"},
        "hydrolase-like": {"sensing", "environmental", "other"},
        "haloperoxidase-like": {"sensing", "antibacterial", "other"},
        "glutathione-oxidase-like": {"sensing", "therapeutic", "antioxidant", "other"},
        "nuclease-like": {"sensing", "therapeutic", "other"},
        "cascade-enzymatic": {"sensing", "therapeutic", "antibacterial", "antioxidant", "environmental", "biofilm_inhibition", "other"},
    }

    def check_application_enzyme_consistency(self, record: Dict) -> Tuple[Dict, List[str]]:
        warnings = []
        etype = (record.get("main_activity", {}).get("enzyme_like_type") or "").lower().strip()
        if not etype:
            return record, warnings
        compatible = self._ENZYME_APP_COMPATIBILITY.get(etype)
        if not compatible:
            return record, warnings
        for app in record.get("applications", []):
            if not isinstance(app, dict):
                continue
            app_type = (app.get("application_type") or "").lower().strip()
            if not app_type:
                continue
            if app_type not in compatible:
                warnings.append(f"app_type_incompatible_with_enzyme: {app_type} vs {etype}")
                app["needs_review"] = True
        return record, warnings
