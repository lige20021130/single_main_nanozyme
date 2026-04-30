import re
import logging
from typing import Dict, List, Any, Optional

from single_main_nanozyme_extractor import (
    _KM_PATTERNS, _KM_VMAX_JOINT_PATTERNS, _VMAX_PATTERNS, _VMAX_OCR_PATTERNS,
    _KCAT_PATTERNS, _KCAT_KM_PATTERNS, _LOD_PATTERNS, _LINEAR_RANGE_PATTERNS,
    _SYNTHESIS_METHODS, _SYNTHESIS_CONDITION_PATTERNS,
    _SIZE_PATTERNS, _CRYSTAL_STRUCTURE_PATTERNS, _SURFACE_AREA_PATTERNS,
    _ZETA_POTENTIAL_PATTERNS, _PORE_SIZE_PATTERNS,
    _PH_PATTERNS, _TEMPERATURE_PATTERNS,
    _ENZYME_TYPE_PATTERNS, _SUBSTRATE_KEYWORDS,
    _normalize_ocr_scientific, _parse_scientific_notation, _extract_vmax_fallback,
)

logger = logging.getLogger(__name__)


def _norm_unit(unit):
    try:
        from numeric_validator import normalize_unit
        return normalize_unit(unit) if unit else unit
    except ImportError:
        return unit


class KineticsAgent:
    def extract(self, record, buckets, table_values, selected_name, doc=None):
        if record["main_activity"]["kinetics"]["Km"] is None or record["main_activity"]["kinetics"]["Vmax"] is None:
            self._extract_kinetics_from_text(record, buckets.get("kinetics", []))
        if record["main_activity"]["kinetics"]["Km"] is None or record["main_activity"]["kinetics"]["Vmax"] is None:
            self._extract_kinetics_from_flattened_table(record, buckets.get("kinetics", []), selected_name)
        if record["main_activity"]["kinetics"]["Km"] is None and table_values:
            self._extract_kinetics_from_table(record, table_values)
        self._extract_kcat_from_text(record, buckets.get("kinetics", []))
        return record

    def _extract_kinetics_from_text(self, record, kinetics_texts):
        for idx, text in enumerate(kinetics_texts):
            norm_text = _normalize_ocr_scientific(text)
            if record["main_activity"]["kinetics"]["Km"] is None or record["main_activity"]["kinetics"]["Vmax"] is None:
                for pat in _KM_VMAX_JOINT_PATTERNS:
                    m = pat.search(text)
                    if not m:
                        m = pat.search(norm_text)
                    if m:
                        km_val = _parse_scientific_notation(m.group(1))
                        km_unit = m.group(2)
                        vmax_raw = m.group(3)
                        vmax_unit = m.group(4)
                        vmax_val = _parse_scientific_notation(vmax_raw)
                        if isinstance(km_val, (int, float)) and record["main_activity"]["kinetics"]["Km"] is None:
                            record["main_activity"]["kinetics"]["Km"] = km_val
                            nu = _norm_unit(km_unit)
                            record["main_activity"]["kinetics"]["Km_unit"] = nu if nu else km_unit
                            record["main_activity"]["kinetics"]["source"] = "text"
                        if isinstance(vmax_val, (int, float)) and record["main_activity"]["kinetics"]["Vmax"] is None:
                            record["main_activity"]["kinetics"]["Vmax"] = vmax_val
                            nu = _norm_unit(vmax_unit)
                            record["main_activity"]["kinetics"]["Vmax_unit"] = nu if nu else vmax_unit
                            record["main_activity"]["kinetics"]["source"] = "text"
                            logger.info(f"[KineticsAgent] Vmax set by joint pattern: {vmax_val} {vmax_unit}")
                        break

            if record["main_activity"]["kinetics"]["Km"] is None:
                for pat in _KM_PATTERNS:
                    m = pat.search(text)
                    if not m:
                        m = pat.search(norm_text)
                    if m:
                        groups = m.groups()
                        if len(groups) == 3:
                            if groups[0] in ("mM", "μM", "uM", "M", "mmol", "umol", "nmol"):
                                value, unit = groups[1], groups[0]
                                substrate = None
                            else:
                                substrate, value, unit = groups
                        elif len(groups) == 2:
                            value, unit = groups
                            substrate = None
                        else:
                            continue
                        try:
                            record["main_activity"]["kinetics"]["Km"] = float(value)
                            nu = _norm_unit(unit)
                            record["main_activity"]["kinetics"]["Km_unit"] = nu if nu else unit
                            if substrate:
                                record["main_activity"]["kinetics"]["substrate"] = substrate
                            record["main_activity"]["kinetics"]["source"] = "text"
                        except ValueError:
                            pass
                        break

            if record["main_activity"]["kinetics"]["Vmax"] is None:
                for pat in _VMAX_PATTERNS:
                    m = pat.search(text)
                    if not m:
                        m = pat.search(norm_text)
                    if m:
                        groups = m.groups()
                        logger.info(f"[KineticsAgent] VMAX_PATTERNS match: groups={groups} in '{text[:80]}'")
                        if len(groups) == 2:
                            g0, g1 = groups
                            _RATE_UNITS = ("M s⁻¹", "M s-1", "M s–1", "M s^-1", "M/s", "mM/s", "μM/s", "M S⁻¹", "M S-1", "mM·s⁻¹", "mM\u00b7s\u207b\u00b9")
                            g0_is_unit = g0 in _RATE_UNITS or bool(re.match(r'10[−\-–]?\d*\s*M\s*[sS]', g0)) or bool(re.match(r'[mμunp]?M[·\s]*s[⁻\-–]1', g0))
                            g1_is_unit = g1 in _RATE_UNITS or bool(re.match(r'10[−\-–]?\d*\s*M\s*[sS]', g1)) or bool(re.match(r'[mμunp]?M[·\s]*s[⁻\-–]1', g1))
                            if g1_is_unit and not g0_is_unit:
                                value, unit = g0, g1
                                substrate = None
                            elif g0_is_unit:
                                value, unit = g1, g0
                                substrate = None
                            else:
                                substrate, value = g0, g1
                                unit = None
                        elif len(groups) == 3:
                            substrate, value, unit = groups
                        else:
                            continue
                        vmax_val = _parse_scientific_notation(value.strip())
                        record["main_activity"]["kinetics"]["Vmax"] = vmax_val
                        if unit:
                            nu = _norm_unit(unit)
                            record["main_activity"]["kinetics"]["Vmax_unit"] = nu if nu else unit
                        if substrate and not record["main_activity"]["kinetics"]["substrate"]:
                            record["main_activity"]["kinetics"]["substrate"] = substrate
                        record["main_activity"]["kinetics"]["source"] = "text"
                        break

            if record["main_activity"]["kinetics"]["Vmax"] is None:
                fallback = _extract_vmax_fallback(text)
                if fallback and isinstance(fallback.get("value"), (int, float)):
                    record["main_activity"]["kinetics"]["Vmax"] = fallback["value"]
                    print(f'[TRACE] Vmax set to {fallback["value"]} at line 135 (OCR fallback) from text[{idx}]: {text[:80]}')
                    if fallback.get("unit"):
                        nu = _norm_unit(fallback["unit"])
                        record["main_activity"]["kinetics"]["Vmax_unit"] = nu if nu else fallback["unit"]
                    record["main_activity"]["kinetics"]["source"] = fallback.get("source", "text_ocr_fallback")
                    logger.info(f"[KineticsAgent] Vmax OCR fallback: {fallback['value']} {fallback.get('unit', '')}")
            else:
                if 'Vmax' in text or 'vmax' in text.lower():
                    logger.info(f"[KineticsAgent] Vmax already set ({record['main_activity']['kinetics']['Vmax']}), skipping text with Vmax mention")

    def _extract_kinetics_from_flattened_table(self, record, kinetics_texts, selected_name):
        _FLAT_KM_HEADER = re.compile(r'Km\s*[\(（]\s*(mM|μM|uM|M|mmol|umol|nmol)\s*[\)）]', re.I)
        _FLAT_VMAX_HEADER = re.compile(r'Vmax\s*[\(（\[]\s*([^\)）\]]+)\s*[\)）\]]', re.I)
        _FLAT_SUBSTRATE_HEADER = re.compile(r'Substrate', re.I)
        _FLAT_CATALYST_HEADER = re.compile(r'Catalyst|Nanozyme|Material', re.I)
        _NUM_RE = re.compile(r'[\d.]+')

        all_texts = list(kinetics_texts)
        for text in kinetics_texts:
            table_refs = re.findall(r'Table\s+S?\d+', text, re.I)
            if table_refs:
                for ref in table_refs:
                    for other_text in kinetics_texts:
                        if other_text != text and ref.lower() in other_text.lower() and other_text not in all_texts:
                            all_texts.append(other_text)

        for text in all_texts:
            norm_text = _normalize_ocr_scientific(text)
            lines = norm_text.strip().split('\n')
            if len(lines) < 2:
                single_line = self._try_parse_inline_table(text, selected_name, record)
                if single_line:
                    return
                continue

            header = lines[0]
            km_h = _FLAT_KM_HEADER.search(header)
            vmax_h = _FLAT_VMAX_HEADER.search(header)
            if not km_h and not vmax_h:
                continue

            km_unit = km_h.group(1) if km_h else None
            vmax_unit_raw = vmax_h.group(1).strip() if vmax_h else None
            has_substrate_col = bool(_FLAT_SUBSTRATE_HEADER.search(header))
            has_catalyst_col = bool(_FLAT_CATALYST_HEADER.search(header))
            header_parts = re.split(r'\s{2,}|\t', header)
            col_count = len(header_parts)

            for line in lines[1:]:
                parts = re.split(r'\s{2,}|\t', line.strip())
                if len(parts) < 2:
                    continue
                line_lower = line.lower()
                name_lower = selected_name.lower().replace(" ", "")
                line_compact = line_lower.replace(" ", "").replace("-", "")
                is_match = (name_lower in line_compact or selected_name.lower() in line_lower or "this work" in line_lower or "our" in line_lower)
                if not is_match and has_catalyst_col:
                    continue
                if not is_match and col_count <= 3:
                    continue

                if km_h and record["main_activity"]["kinetics"]["Km"] is None:
                    km_idx = None
                    for i, hp in enumerate(header_parts):
                        if re.search(r'\bKm\b', hp, re.I):
                            km_idx = i
                            break
                    if km_idx is not None and km_idx < len(parts):
                        try:
                            km_val = float(parts[km_idx])
                            record["main_activity"]["kinetics"]["Km"] = km_val
                            nu = _norm_unit(km_unit)
                            record["main_activity"]["kinetics"]["Km_unit"] = nu if nu else km_unit
                            record["main_activity"]["kinetics"]["source"] = "text"
                        except ValueError:
                            pass

                if vmax_h and record["main_activity"]["kinetics"]["Vmax"] is None:
                    vmax_idx = None
                    for i, hp in enumerate(header_parts):
                        if re.search(r'\bVmax\b', hp, re.I):
                            vmax_idx = i
                            break
                    if vmax_idx is not None and vmax_idx < len(parts):
                        raw_vmax = parts[vmax_idx].strip()
                        vmax_parsed = _parse_scientific_notation(raw_vmax)
                        if isinstance(vmax_parsed, (int, float)):
                            record["main_activity"]["kinetics"]["Vmax"] = vmax_parsed
                            print(f'[TRACE] Vmax set to {vmax_parsed} at line 223 (flattened table)')
                            nu = _norm_unit(vmax_unit_raw)
                            record["main_activity"]["kinetics"]["Vmax_unit"] = nu if nu else vmax_unit_raw
                            record["main_activity"]["kinetics"]["source"] = "text"
                        else:
                            norm_vmax = _normalize_ocr_scientific(raw_vmax)
                            vmax_parsed2 = _parse_scientific_notation(norm_vmax)
                            if isinstance(vmax_parsed2, (int, float)):
                                record["main_activity"]["kinetics"]["Vmax"] = vmax_parsed2
                                nu = _norm_unit(vmax_unit_raw)
                                record["main_activity"]["kinetics"]["Vmax_unit"] = nu if nu else vmax_unit_raw
                                record["main_activity"]["kinetics"]["source"] = "text"

                if has_substrate_col and not record["main_activity"]["kinetics"]["substrate"]:
                    sub_idx = None
                    for i, hp in enumerate(header_parts):
                        if re.search(r'Substrate', hp, re.I):
                            sub_idx = i
                            break
                    if sub_idx is not None and sub_idx < len(parts):
                        sub_val = parts[sub_idx].strip()
                        if sub_val and len(sub_val) < 20:
                            record["main_activity"]["kinetics"]["substrate"] = sub_val

                if record["main_activity"]["kinetics"]["Km"] is not None:
                    return

    def _try_parse_inline_table(self, text, selected_name, record):
        km_header_m = re.search(r'Km\s*[\(（]\s*(mM|μM|uM|M|mmol|umol|nmol)\s*[\)）]', text, re.I)
        vmax_header_m = re.search(r'Vmax\s*[\(（\[]\s*([^\)）\]]+?)\s*[\)）\]]', text, re.I)
        if not km_header_m and not vmax_header_m:
            return False
        km_unit = km_header_m.group(1) if km_header_m else None
        vmax_unit = vmax_header_m.group(1).strip() if vmax_header_m else None
        header_end = max(km_header_m.end() if km_header_m else 0, vmax_header_m.end() if vmax_header_m else 0)
        data_part = text[header_end:].strip()
        name_lower = selected_name.lower()
        name_variants = [name_lower, name_lower.replace(" ", "")]
        for prefix in ["nanosized ", "nano ", "the "]:
            if name_lower.startswith(prefix):
                name_variants.append(name_lower[len(prefix):])
        pattern_str = r'(?:' + '|'.join(re.escape(nv) for nv in name_variants if nv) + r')'
        catalyst_m = re.search(pattern_str, data_part, re.I)
        if not catalyst_m:
            if "this work" in data_part.lower():
                catalyst_m = re.search(r'[\w\s]*?this work', data_part, re.I)
        if not catalyst_m:
            return False
        after_catalyst = data_part[catalyst_m.start():]
        nums = re.findall(r'([\d.]+)', after_catalyst)
        if len(nums) >= 2:
            if vmax_header_m and km_header_m:
                try:
                    vmax_val = float(nums[0])
                    km_val = float(nums[1])
                    record["main_activity"]["kinetics"]["Km"] = km_val
                    nu = _norm_unit(km_unit)
                    record["main_activity"]["kinetics"]["Km_unit"] = nu if nu else km_unit
                    record["main_activity"]["kinetics"]["Vmax"] = vmax_val
                    nu = _norm_unit(vmax_unit)
                    record["main_activity"]["kinetics"]["Vmax_unit"] = nu if nu else vmax_unit
                    record["main_activity"]["kinetics"]["source"] = "text"
                    return True
                except ValueError:
                    pass
            elif km_header_m:
                try:
                    km_val = float(nums[0])
                    record["main_activity"]["kinetics"]["Km"] = km_val
                    nu = _norm_unit(km_unit)
                    record["main_activity"]["kinetics"]["Km_unit"] = nu if nu else km_unit
                    record["main_activity"]["kinetics"]["source"] = "text"
                    return True
                except ValueError:
                    pass
        return False

    def _extract_kinetics_from_table(self, record, table_values):
        for val in table_values:
            param = val.get("parameter", "")
            if param == "Km" and record["main_activity"]["kinetics"]["Km"] is None:
                try:
                    record["main_activity"]["kinetics"]["Km"] = float(val["value"])
                    nu = _norm_unit(val.get("unit"))
                    record["main_activity"]["kinetics"]["Km_unit"] = nu if nu else val.get("unit")
                    record["main_activity"]["kinetics"]["substrate"] = val.get("substrate")
                    record["main_activity"]["kinetics"]["source"] = "table"
                except (ValueError, TypeError):
                    pass
            elif param == "Vmax" and record["main_activity"]["kinetics"]["Vmax"] is None:
                try:
                    record["main_activity"]["kinetics"]["Vmax"] = float(val["value"])
                except (ValueError, TypeError):
                    record["main_activity"]["kinetics"]["Vmax"] = val["value"]
                nu = _norm_unit(val.get("unit"))
                record["main_activity"]["kinetics"]["Vmax_unit"] = nu if nu else val.get("unit")
                record["main_activity"]["kinetics"]["source"] = "table"
            elif param in ("kcat", "Kcat", "k_cat") and record["main_activity"]["kinetics"]["kcat"] is None:
                try:
                    parsed = _parse_scientific_notation(str(val["value"]))
                    if isinstance(parsed, (int, float)):
                        record["main_activity"]["kinetics"]["kcat"] = parsed
                        raw_u = val.get("unit", "s^-1")
                        nu = _norm_unit(raw_u)
                        record["main_activity"]["kinetics"]["kcat_unit"] = nu if nu else raw_u
                        record["main_activity"]["kinetics"]["source"] = "table"
                except (ValueError, TypeError):
                    pass
            elif param in ("kcat/Km", "kcat_Km", "Kcat/Km", "catalytic_efficiency") and record["main_activity"]["kinetics"]["kcat_Km"] is None:
                try:
                    parsed = _parse_scientific_notation(str(val["value"]))
                    if isinstance(parsed, (int, float)):
                        record["main_activity"]["kinetics"]["kcat_Km"] = parsed
                        raw_u = val.get("unit", "M^-1 s^-1")
                        nu = _norm_unit(raw_u)
                        record["main_activity"]["kinetics"]["kcat_Km_unit"] = nu if nu else raw_u
                        record["main_activity"]["kinetics"]["source"] = "table"
                except (ValueError, TypeError):
                    pass

    def _extract_kcat_from_text(self, record, kinetics_texts):
        for text in kinetics_texts:
            norm_text = _normalize_ocr_scientific(text)
            if record["main_activity"]["kinetics"]["kcat"] is None:
                for pat in _KCAT_PATTERNS:
                    m = pat.search(text)
                    if not m:
                        m = pat.search(norm_text)
                    if m:
                        groups = m.groups()
                        if len(groups) == 3:
                            substrate, value, unit = groups
                        elif len(groups) == 2:
                            value, unit = groups
                            substrate = None
                        else:
                            continue
                        parsed = _parse_scientific_notation(value.strip())
                        if isinstance(parsed, (int, float)):
                            record["main_activity"]["kinetics"]["kcat"] = parsed
                            nu = _norm_unit(unit)
                            record["main_activity"]["kinetics"]["kcat_unit"] = nu if nu else unit
                            if substrate and not record["main_activity"]["kinetics"]["substrate"]:
                                record["main_activity"]["kinetics"]["substrate"] = substrate
                            break

            if record["main_activity"]["kinetics"]["kcat"] is None:
                e_m = re.search(r'\bkcat\b[^.=]{0,20}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)', norm_text, re.I)
                if not e_m:
                    e_m = re.search(r'\bkcat\b[^.=]{0,20}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)', text, re.I)
                if e_m:
                    try:
                        base = float(e_m.group(1))
                        exp = int(e_m.group(2).replace('−', '-').replace('\u2212', '-'))
                        kcat_val = base * (10 ** exp)
                        if 1e-3 <= kcat_val <= 1e8:
                            record["main_activity"]["kinetics"]["kcat"] = kcat_val
                            nu = _norm_unit("s^-1")
                            record["main_activity"]["kinetics"]["kcat_unit"] = nu if nu else "s^-1"
                            logger.info(f"[KineticsAgent] kcat E-notation: {base}e{exp} = {kcat_val:.2e}")
                    except (ValueError, TypeError):
                        pass

            if record["main_activity"]["kinetics"]["kcat_Km"] is None:
                for pat in _KCAT_KM_PATTERNS:
                    m = pat.search(text)
                    if not m:
                        m = pat.search(norm_text)
                    if m:
                        groups = m.groups()
                        if len(groups) == 3:
                            substrate, value, unit = groups
                        elif len(groups) == 2:
                            value, unit = groups
                            substrate = None
                        else:
                            continue
                        parsed = _parse_scientific_notation(value.strip())
                        if isinstance(parsed, (int, float)):
                            record["main_activity"]["kinetics"]["kcat_Km"] = parsed
                            nu = _norm_unit(unit)
                            record["main_activity"]["kinetics"]["kcat_Km_unit"] = nu if nu else unit
                            break

            if record["main_activity"]["kinetics"]["kcat_Km"] is None:
                eff_m = re.search(r'\bcatalytic\s+efficiency\b[^.=]{0,30}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)', norm_text, re.I)
                if not eff_m:
                    eff_m = re.search(r'\bcatalytic\s+efficiency\b[^.=]{0,30}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)', text, re.I)
                if eff_m:
                    try:
                        base = float(eff_m.group(1))
                        exp = int(eff_m.group(2).replace('−', '-').replace('\u2212', '-'))
                        kcat_km_val = base * (10 ** exp)
                        if 1e0 <= kcat_km_val <= 1e12:
                            record["main_activity"]["kinetics"]["kcat_Km"] = kcat_km_val
                            nu = _norm_unit("M^-1 s^-1")
                            record["main_activity"]["kinetics"]["kcat_Km_unit"] = nu if nu else "M^-1 s^-1"
                    except (ValueError, TypeError):
                        pass

        if record["main_activity"]["kinetics"]["kcat"] is None:
            kcat_km = record["main_activity"]["kinetics"].get("kcat_Km")
            km = record["main_activity"]["kinetics"].get("Km")
            km_unit = record["main_activity"]["kinetics"].get("Km_unit", "")
            if kcat_km and km and isinstance(kcat_km, (int, float)) and isinstance(km, (int, float)) and km > 0:
                km_in_M = km
                if km_unit in ("mM",):
                    km_in_M = km * 1e-3
                elif km_unit in ("μM", "uM"):
                    km_in_M = km * 1e-6
                elif km_unit in ("nM",):
                    km_in_M = km * 1e-9
                kcat_val = kcat_km * km_in_M
                if 1e-3 <= kcat_val <= 1e8:
                    record["main_activity"]["kinetics"]["kcat"] = kcat_val
                    record["main_activity"]["kinetics"]["kcat_unit"] = "s^-1"
                    logger.info(f"[KineticsAgent] kcat derived from kcat/Km={kcat_km:.2e} * Km={km} {km_unit} = {kcat_val:.2e}")


class MorphologyAgent:
    def extract(self, record, buckets, table_values, selected_name, doc=None):
        material_texts = buckets.get("material", []) + buckets.get("characterization", []) + buckets.get("synthesis", [])[:3]
        self._extract_size_properties(record, material_texts)
        char_texts = buckets.get("characterization", []) + buckets.get("material", [])[:3]
        self._extract_physical_properties(record, char_texts)
        return record

    def _extract_size_properties(self, record, material_texts):
        sel = record.get("selected_nanozyme", {})
        if not isinstance(sel, dict):
            return
        if sel.get("size") is None:
            for text in material_texts:
                for pat in _SIZE_PATTERNS:
                    m = pat.search(text)
                    if m:
                        groups = m.groups()
                        if len(groups) == 3:
                            low, high, unit = groups
                            sel["size"] = f"{low}-{high} {unit}"
                            sel["size_unit"] = unit
                            sel["size_distribution"] = f"{low}-{high} {unit}"
                        elif len(groups) == 2:
                            value, unit = groups
                            sel["size"] = f"{value} {unit}"
                            sel["size_unit"] = unit
                        break
                if sel.get("size"):
                    break
        if sel.get("crystal_structure") is None:
            for text in material_texts:
                for pat in _CRYSTAL_STRUCTURE_PATTERNS:
                    m = pat.search(text)
                    if m:
                        if m.lastindex and m.group(1):
                            sel["crystal_structure"] = m.group(1).lower()
                        else:
                            match_text = m.group(0).lower()
                            for struct_name in ("spinel", "perovskite", "fluorite", "cubic", "tetragonal", "hexagonal", "orthorhombic", "monoclinic", "amorphous", "crystalline", "anatase", "rutile", "brookite"):
                                if struct_name in match_text:
                                    sel["crystal_structure"] = struct_name
                                    break
                        break
                if sel.get("crystal_structure"):
                    break

    def _extract_physical_properties(self, record, char_texts):
        sel = record.get("selected_nanozyme", {})
        if not isinstance(sel, dict):
            return
        if sel.get("surface_area") is None:
            for text in char_texts:
                for pat in _SURFACE_AREA_PATTERNS:
                    m = pat.search(text)
                    if m:
                        sel["surface_area"] = f"{m.group(1)} {m.group(2)}"
                        break
                if sel.get("surface_area"):
                    break
        if sel.get("zeta_potential") is None:
            for text in char_texts:
                for pat in _ZETA_POTENTIAL_PATTERNS:
                    m = pat.search(text)
                    if m:
                        sel["zeta_potential"] = f"{m.group(1)} {m.group(2)}"
                        break
                if sel.get("zeta_potential"):
                    break
        if sel.get("pore_size") is None:
            for text in char_texts:
                for pat in _PORE_SIZE_PATTERNS:
                    m = pat.search(text)
                    if m:
                        sel["pore_size"] = f"{m.group(1)} {m.group(2)}"
                        break
                if sel.get("pore_size"):
                    break


class SynthesisAgent:
    def extract(self, record, buckets, table_values, selected_name, doc=None):
        synthesis_texts = buckets.get("synthesis", []) + buckets.get("material", [])[:5] + buckets.get("characterization", [])[:3]
        self._extract_synthesis_method(record, synthesis_texts)
        return record

    def _extract_synthesis_method(self, record, synthesis_texts):
        sel = record.get("selected_nanozyme", {})
        if not isinstance(sel, dict):
            return
        if sel.get("synthesis_method") is None:
            method_scores = {}
            for text in synthesis_texts:
                for method_name, pattern in _SYNTHESIS_METHODS.items():
                    if pattern.search(text):
                        score = method_scores.get(method_name, 0) + 1
                        method_scores[method_name] = score
            if method_scores:
                best_method = max(method_scores, key=method_scores.get)
                sel["synthesis_method"] = best_method.replace("_", " ")

        synth_cond = sel.get("synthesis_conditions", {})
        if not isinstance(synth_cond, dict):
            synth_cond = {}
            sel["synthesis_conditions"] = synth_cond

        if synth_cond.get("temperature") is None:
            for text in synthesis_texts:
                for pat in _SYNTHESIS_CONDITION_PATTERNS["temperature"]:
                    m = pat.search(text)
                    if m:
                        synth_cond["temperature"] = f"{m.group(1)} °C"
                        break
                if synth_cond.get("temperature"):
                    break

        if synth_cond.get("time") is None:
            for text in synthesis_texts:
                for pat in _SYNTHESIS_CONDITION_PATTERNS["time"]:
                    m = pat.search(text)
                    if m:
                        synth_cond["time"] = f"{m.group(1)} {m.group(2)}"
                        break
                if synth_cond.get("time"):
                    break

        if not synth_cond.get("precursors"):
            for text in synthesis_texts:
                for pat in _SYNTHESIS_CONDITION_PATTERNS["precursors"]:
                    m = pat.search(text)
                    if m:
                        raw = m.group(1).strip()
                        precursors = [p.strip() for p in re.split(r'[,\s]+', raw) if p.strip() and len(p.strip()) > 1]
                        if precursors:
                            synth_cond["precursors"] = precursors[:5]
                        break
                if synth_cond.get("precursors"):
                    break


class ApplicationAgent:
    _APP_TYPE_KEYWORDS = {
        "detection": ["detection", "sensing", "sensor", "biosensor", "assay", "monitoring", "determin"],
        "therapeutic": ["therapeutic", "antitumor", "antibacterial", "wound heal", "cytoprotect", "neuroprotect", "anti-inflammator", "antiinflammator", "disinfect", "steriliz"],
        "environmental": ["pollutant", "heavy metal", "pesticide", "organophosph", "endocrine", "degrad", "environmental", "drinking water", "waste water", "river", "lake", "tap water", "sea water"],
        "diagnostic": ["diagnos", "theranost", "biomarker", "point-of-care", "poc"],
    }

    _ANALYTE_PATTERNS = [
        re.compile(r'\b(?:detection\s+(?:of|for)|sensing\s+(?:of|for)|determin(?:ation|ing)\s+(?:of|for))\s+([\w\-]+(?:\s[\w\-]+){0,3})', re.I),
        re.compile(r'\b(?:glucose|cholesterol|uric\s+acid|lactate|ascorbic\s+acid|dopamine|cysteine|glutathione|bilirubin)\b', re.I),
        re.compile(r'\b(?:Hg[\s2]*\+{1,2}|Pb[\s2]*\+{1,2}|Cd[\s2]*\+{1,2}|Cu[\s2]*\+{1,2}|Fe[\s3]*\+{1,2}|Cr\s*[Vv][Ii]+|As\s*[Vv][Ii]+)\b', re.I),
        re.compile(r'\b(?:xanthine|hypoxanthine|acetylcholine|choline|urea|hydrogen\s+peroxide|H2O2|phenol|bisphenol|catechol|hydroquinone)\b', re.I),
        re.compile(r'\b(?:mercury|lead|cadmium|arsenic|chromium)\b', re.I),
    ]

    _SAMPLE_TYPE_MAP = {
        "serum": "serum", "plasma": "plasma", "urine": "urine", "blood": "blood",
        "saliva": "saliva", "tear": "tear", "water": "water", "food": "food",
        "milk": "food", "juice": "food", "wine": "food", "beer": "food",
        "cell": "cell_culture", "tissue": "tissue", "river": "environmental_water",
        "lake": "environmental_water", "tap water": "environmental_water",
        "sea water": "environmental_water", "waste water": "environmental_water",
        "drinking water": "environmental_water",
    }

    def extract(self, record, buckets, table_values, selected_name, doc=None):
        self._extract_applications_from_text(record, buckets.get("application", []))
        return record

    def _is_kinetics_context(self, text):
        kinetics_kw = ("km", "vmax", "kcat", "michaelis", "kinetic", "michaelis-menten")
        text_lower = text.lower()
        return any(kw in text_lower for kw in kinetics_kw)

    def _extract_applications_from_text(self, record, app_texts):
        if record["applications"]:
            return
        seen_apps = set()
        for text in app_texts:
            app = {}
            for pat in _LOD_PATTERNS:
                lod_m = pat.search(text)
                if lod_m:
                    app["detection_limit"] = f"{lod_m.group(1)} {lod_m.group(2)}"
                    break
            for pat in _LINEAR_RANGE_PATTERNS:
                lr_m = pat.search(text)
                if lr_m:
                    app["linear_range"] = f"{lr_m.group(1)} {lr_m.group(2)}"
                    break
            text_lower = text.lower()
            for app_type, keywords in self._APP_TYPE_KEYWORDS.items():
                if any(kw in text_lower for kw in keywords):
                    app["application_type"] = app_type
                    break
            for pat in self._ANALYTE_PATTERNS:
                m = pat.search(text)
                if m:
                    analyte = m.group(1).strip() if m.lastindex else m.group(0).strip()
                    analyte = re.sub(r'\s+', ' ', analyte).strip()
                    if len(analyte) > 2 and analyte.lower() not in ("the", "this", "that"):
                        if analyte.lower() == "h2o2" and self._is_kinetics_context(text):
                            continue
                        app["target_analyte"] = analyte
                    break
            for sample_kw, sample_type in self._SAMPLE_TYPE_MAP.items():
                if sample_kw in text_lower:
                    app["sample_type"] = sample_type
                    break
            if any(kw in text_lower for kw in ["colorimetric", "colorimetry"]):
                app["method"] = "colorimetric"
            elif any(kw in text_lower for kw in ["fluorescent", "fluorescence"]):
                app["method"] = "fluorescent"
            elif any(kw in text_lower for kw in ["electrochem"]):
                app["method"] = "electrochemical"
            elif any(kw in text_lower for kw in ["smartphone", "phone"]):
                app["method"] = "smartphone-based"
            has_substance = any(v is not None for k, v in app.items() if k in ("detection_limit", "linear_range", "target_analyte", "sample_type"))
            has_type = app.get("application_type") is not None
            if not has_substance and not has_type:
                continue
            dedup_key = (app.get("application_type"), app.get("target_analyte"), app.get("detection_limit"), app.get("linear_range"))
            if dedup_key in seen_apps:
                continue
            seen_apps.add(dedup_key)
            for key in ("application_type", "target_analyte", "method", "linear_range", "detection_limit", "sample_type", "notes"):
                app.setdefault(key, None)
            record["applications"].append(app)


class RuleExtractorAdapter:
    def __init__(self):
        self.kinetics_agent = KineticsAgent()
        self.morphology_agent = MorphologyAgent()
        self.synthesis_agent = SynthesisAgent()
        self.application_agent = ApplicationAgent()

    def extract_from_evidence(self, record, buckets, table_values, selected_name, doc=None):
        if record["main_activity"]["enzyme_like_type"] is None:
            search_texts = buckets.get("activity", []) + buckets.get("mechanism", [])
            if doc:
                title = doc.metadata.get("title", "")
                if title:
                    search_texts.insert(0, title)
                for chunk in doc.chunks[:3]:
                    if "abstract" in chunk.lower()[:200]:
                        search_texts.insert(0, chunk[:2000])
                        break
            for text in search_texts:
                for pattern, etype in _ENZYME_TYPE_PATTERNS:
                    if pattern.search(text):
                        record["main_activity"]["enzyme_like_type"] = etype
                        break
                if record["main_activity"]["enzyme_like_type"]:
                    break
            if record["main_activity"]["enzyme_like_type"] is None and doc:
                for chunk in doc.chunks:
                    for pattern, etype in _ENZYME_TYPE_PATTERNS:
                        if pattern.search(chunk):
                            record["main_activity"]["enzyme_like_type"] = etype
                            break
                    if record["main_activity"]["enzyme_like_type"]:
                        break

        if not record["main_activity"]["substrates"]:
            found = set()
            for text in buckets.get("activity", []):
                for sub in _SUBSTRATE_KEYWORDS:
                    if sub in text:
                        found.add(sub)
            if found:
                record["main_activity"]["substrates"] = sorted(found)

        self.kinetics_agent.extract(record, buckets, table_values, selected_name, doc)
        self.morphology_agent.extract(record, buckets, table_values, selected_name, doc)
        self.synthesis_agent.extract(record, buckets, table_values, selected_name, doc)
        self.application_agent.extract(record, buckets, table_values, selected_name, doc)

        self._extract_pH_profile(record, buckets)
        self._extract_temperature_profile(record, buckets)

        if doc:
            self._fulltext_fallback_extract(record, doc, selected_name)

        return record

    def _extract_pH_profile(self, record, buckets):
        ph_profile = record["main_activity"].get("pH_profile", {})
        if not isinstance(ph_profile, dict):
            ph_profile = {}
            record["main_activity"]["pH_profile"] = ph_profile

        search_texts = (
            buckets.get("activity", [])
            + buckets.get("kinetics", [])
            + buckets.get("application", [])[:5]
            + record.get("raw_supporting_text", {}).get("kinetics", [])[:5]
        )

        if ph_profile.get("optimal_pH") is None:
            for text in search_texts:
                for pat in _PH_PATTERNS["optimal_pH"]:
                    m = pat.search(text)
                    if m:
                        try:
                            ph_profile["optimal_pH"] = float(m.group(1))
                            record["main_activity"]["conditions"]["pH"] = m.group(1)
                        except (ValueError, IndexError):
                            pass
                        break
                if ph_profile.get("optimal_pH") is not None:
                    break

        if ph_profile.get("optimal_pH") is None:
            for text in search_texts:
                if re.search(r'\b(?:kinetic|reaction|catalytic|assay|steady-state)\b', text, re.I):
                    m = re.search(r'\b(?:buffer|solution)\s*\([^)]*pH\s*([\d.]+)', text, re.I)
                    if m:
                        try:
                            val = float(m.group(1))
                            if 0 <= val <= 14:
                                record["main_activity"]["conditions"]["pH"] = m.group(1)
                                break
                        except (ValueError, IndexError):
                            pass

        if ph_profile.get("optimal_pH") is None:
            _PH_LOOSE_PATTERNS = [
                re.compile(r'\bpH\s*([\d.]+)\s*\)', re.I),
                re.compile(r'\bpH\s+([\d.]+)', re.I),
            ]
            for text in search_texts:
                if re.search(r'\b(?:optimal|optimum|best|highest|maximum|peak)\b', text, re.I) and re.search(r'\bpH\b', text, re.I):
                    for pat in _PH_LOOSE_PATTERNS:
                        m = pat.search(text)
                        if m:
                            try:
                                val = float(m.group(1))
                                if 0 < val <= 14:
                                    ph_profile["optimal_pH"] = val
                                    record["main_activity"]["conditions"]["pH"] = m.group(1)
                                    break
                            except (ValueError, IndexError):
                                pass
                    if ph_profile.get("optimal_pH") is not None:
                        break

        if ph_profile.get("pH_range") is None:
            for text in search_texts:
                for pat in _PH_PATTERNS["pH_range"]:
                    m = pat.search(text)
                    if m:
                        ph_profile["pH_range"] = f"{m.group(1)}-{m.group(2)}"
                        break
                if ph_profile.get("pH_range") is not None:
                    break

        if ph_profile.get("pH_stability_range") is None:
            for text in search_texts:
                for pat in _PH_PATTERNS["pH_stability"]:
                    m = pat.search(text)
                    if m:
                        ph_profile["pH_stability_range"] = f"{m.group(1)}-{m.group(2)}"
                        break
                if ph_profile.get("pH_stability_range") is not None:
                    break

    def _extract_temperature_profile(self, record, buckets):
        temp_profile = record["main_activity"].get("temperature_profile", {})
        if not isinstance(temp_profile, dict):
            temp_profile = {}
            record["main_activity"]["temperature_profile"] = temp_profile

        search_texts = (
            buckets.get("activity", [])
            + buckets.get("kinetics", [])
            + buckets.get("application", [])[:5]
            + record.get("raw_supporting_text", {}).get("kinetics", [])[:5]
        )

        norm_texts = [_normalize_ocr_scientific(t) for t in search_texts]

        if temp_profile.get("optimal_temperature") is None:
            for text, norm in zip(search_texts, norm_texts):
                for pat in _TEMPERATURE_PATTERNS["optimal_temperature"]:
                    m = pat.search(text)
                    if not m:
                        m = pat.search(norm)
                    if m:
                        temp_profile["optimal_temperature"] = f"{m.group(1)} °C"
                        record["main_activity"]["conditions"]["temperature"] = f"{m.group(1)} °C"
                        break
                if temp_profile.get("optimal_temperature") is not None:
                    break

        if temp_profile.get("optimal_temperature") is None:
            for text, norm in zip(search_texts, norm_texts):
                if re.search(r'\b(?:kinetic|reaction|catalytic|assay|steady-state)\b', text, re.I):
                    m = re.search(r'\b(?:at|under)\s*([\d.]+)\s*°?\s*C\b', norm, re.I)
                    if not m:
                        m = re.search(r'\b([\d.]+)\s*°\s*C\b', norm, re.I)
                    if m:
                        try:
                            val = float(m.group(1))
                            if 15 <= val <= 80:
                                record["main_activity"]["conditions"]["temperature"] = f"{m.group(1)} °C"
                                break
                        except (ValueError, IndexError):
                            pass

        if temp_profile.get("optimal_temperature") is None:
            _TEMP_LOOSE_PATTERNS = [
                re.compile(r'([\d.]+)\s*°\s*C', re.I),
                re.compile(r'([\d.]+)\s*°C', re.I),
            ]
            for text, norm in zip(search_texts, norm_texts):
                if re.search(r'\b(?:optimal|optimum|best|highest|maximum|peak|dependent|effect)\b', text, re.I) and re.search(r'\b(?:temperature|temp|°C)\b', text, re.I):
                    for pat in _TEMP_LOOSE_PATTERNS:
                        m = pat.search(text)
                        if not m:
                            m = pat.search(norm)
                        if m:
                            try:
                                val = float(m.group(1))
                                if 15 <= val <= 80:
                                    temp_profile["optimal_temperature"] = f"{m.group(1)} °C"
                                    record["main_activity"]["conditions"]["temperature"] = f"{m.group(1)} °C"
                                    break
                            except (ValueError, IndexError):
                                pass
                    if temp_profile.get("optimal_temperature") is not None:
                        break

        if temp_profile.get("temperature_range") is None:
            for text, norm in zip(search_texts, norm_texts):
                for pat in _TEMPERATURE_PATTERNS["temperature_range"]:
                    m = pat.search(text)
                    if not m:
                        m = pat.search(norm)
                    if m:
                        temp_profile["temperature_range"] = f"{m.group(1)}-{m.group(2)} °C"
                        break
                if temp_profile.get("temperature_range") is not None:
                    break

        if temp_profile.get("temperature_range") is None:
            _TEMP_RANGE_FALLBACK = [
                re.compile(r'\btemperature\s+(?:ranging\s+)?(?:from\s+)?([\d.]+)\s*[-–—~to]+\s*([\d.]+)\s*°?C', re.I),
            ]
            for text, norm in zip(search_texts, norm_texts):
                for pat in _TEMP_RANGE_FALLBACK:
                    m = pat.search(text)
                    if not m:
                        m = pat.search(norm)
                    if m:
                        try:
                            low, high = float(m.group(1)), float(m.group(2))
                            if 10 <= low <= 100 and 10 <= high <= 100:
                                temp_profile["temperature_range"] = f"{m.group(1)}-{m.group(2)} °C"
                                break
                        except (ValueError, IndexError):
                            pass
                if temp_profile.get("temperature_range") is not None:
                    break

        if temp_profile.get("thermal_stability") is None:
            for text, norm in zip(search_texts, norm_texts):
                for pat in _TEMPERATURE_PATTERNS["thermal_stability"]:
                    m = pat.search(text)
                    if not m:
                        m = pat.search(norm)
                    if m:
                        temp_profile["thermal_stability"] = f"stable up to {m.group(1)} °C"
                        break
                if temp_profile.get("thermal_stability") is not None:
                    break

    _MORPHOLOGY_TERMS = [
        "nanoparticle", "nanoparticles", "nanosphere", "nanospheres",
        "nanosheet", "nanosheets", "nanorod", "nanorods",
        "nanowire", "nanowires", "nanotube", "nanotubes",
        "nanofiber", "nanofibers", "nanocube", "nanocubes",
        "nanoprism", "nanoprisms", "nanostar", "nanostars",
        "nanoflower", "nanoflowers", "nanocluster", "nanoclusters",
        "nanodot", "nanodots", "nanoring", "nanorings",
        "octahedr", "cuboctahedr", "dodecahedr", "icosahedr",
        "sphere", "spherical", "cubic", "cubical",
        "rod-shaped", "sheet-like", "wire-like", "flower-like",
        "core-shell", "yolk-shell", "hollow sphere", "hollow structure",
        "mesoporous", "porous", "lamellar", "layered",
        "dendritic", "branched", "urchin-like", "bundle",
        "platelet", "flake", "belt", "ribbon",
        "needle-like", "spindle", "ellipsoid", "ellipsoidal",
        "irregular", "aggregat",
    ]

    def _fulltext_fallback_extract(self, record, doc, selected_name):
        all_text = "\n".join(doc.chunks) if doc.chunks else ""
        if not all_text:
            return

        norm_text = _normalize_ocr_scientific(all_text)
        search_pairs = [(all_text, norm_text)]

        sel = record.get("selected_nanozyme", {})
        act = record.get("main_activity", {})
        ph_prof = act.get("pH_profile", {})
        temp_prof = act.get("temperature_profile", {})

        if ph_prof.get("optimal_pH") is None:
            for orig, norm in search_pairs:
                for pat in _PH_PATTERNS["optimal_pH"]:
                    m = pat.search(orig)
                    if not m:
                        m = pat.search(norm)
                    if m:
                        try:
                            val = float(m.group(1))
                            if 0 <= val <= 14:
                                ph_prof["optimal_pH"] = val
                                logger.info(f"[SMN] Fulltext fallback: optimal_pH={val}")
                                break
                        except (ValueError, IndexError):
                            pass
                if ph_prof.get("optimal_pH") is not None:
                    break

        if temp_prof.get("optimal_temperature") is None:
            for orig, norm in search_pairs:
                for pat in _TEMPERATURE_PATTERNS["optimal_temperature"]:
                    m = pat.search(orig)
                    if not m:
                        m = pat.search(norm)
                    if m:
                        temp_prof["optimal_temperature"] = f"{m.group(1)} °C"
                        logger.info(f"[SMN] Fulltext fallback: optimal_temperature={m.group(1)}°C")
                        break
                if temp_prof.get("optimal_temperature") is not None:
                    break
                if temp_prof.get("optimal_temperature") is not None:
                    break



        if sel.get("synthesis_method") is None:
            method_scores = {}
            for method_name, pattern in _SYNTHESIS_METHODS.items():
                if pattern.search(all_text):
                    method_scores[method_name] = method_scores.get(method_name, 0) + 1
            if method_scores:
                best = max(method_scores, key=method_scores.get)
                if best != "general_synthesis" or len(method_scores) == 1:
                    sel["synthesis_method"] = best.replace("_", " ")
                    logger.info(f"[SMN] Fulltext fallback: synthesis_method={best}")

        if sel.get("size") is None:
            for pat in _SIZE_PATTERNS:
                m = pat.search(all_text)
                if m:
                    groups = m.groups()
                    if len(groups) == 3:
                        sel["size"] = f"{groups[0]}-{groups[1]} {groups[2]}"
                        sel["size_unit"] = groups[2]
                    elif len(groups) == 2:
                        sel["size"] = f"{groups[0]} {groups[1]}"
                        sel["size_unit"] = groups[1]
                    logger.info(f"[SMN] Fulltext fallback: size={sel.get('size')}")
                    break

        if sel.get("morphology") is None:
            found_terms = []
            tl = all_text.lower()
            seen_roots = set()
            for term in self._MORPHOLOGY_TERMS:
                root = term.rstrip("s")
                if root in seen_roots:
                    continue
                if term in tl:
                    found_terms.append(term)
                    seen_roots.add(root)
            if found_terms:
                sel["morphology"] = ", ".join(found_terms[:3])
                logger.info(f"[SMN] Fulltext fallback: morphology={sel['morphology']}")

        if sel.get("crystal_structure") is None:
            for pat in _CRYSTAL_STRUCTURE_PATTERNS:
                m = pat.search(all_text)
                if m:
                    if m.lastindex and m.group(1):
                        sel["crystal_structure"] = m.group(1).lower()
                    else:
                        match_text = m.group(0).lower()
                        for struct_name in ("spinel", "perovskite", "fluorite", "cubic",
                                           "tetragonal", "hexagonal", "orthorhombic",
                                           "monoclinic", "amorphous", "crystalline",
                                           "anatase", "rutile", "brookite"):
                            if struct_name in match_text:
                                sel["crystal_structure"] = struct_name
                                break
                    logger.info(f"[SMN] Fulltext fallback: crystal_structure={sel.get('crystal_structure')}")
                    break

        act["pH_profile"] = ph_prof
        act["temperature_profile"] = temp_prof
