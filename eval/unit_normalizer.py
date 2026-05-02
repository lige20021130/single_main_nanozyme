import re
import json
import sys
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger(__name__)

_UNIT_ALIASES = {
    "mM": ["mm", "mmol/l", "mmol l⁻¹", "mmol·l⁻¹", "mmol/liter", "millimolar"],
    "μM": ["um", "μm", "umol/l", "μmol/l", "μmol l⁻¹", "umol/l", "micromolar"],
    "nM": ["nm", "nmol/l", "nmol l⁻¹", "nanomolar"],
    "pM": ["pm", "pmol/l", "pmol l⁻¹", "picomolar"],
    "M": ["mol/l", "mol l⁻¹", "molar"],
    "mg/L": ["mg/l", "mg l⁻¹", "milligram per liter", "mg·l⁻¹"],
    "μg/L": ["ug/l", "μg/l", "μg l⁻¹", "ug l⁻¹", "microgram per liter"],
    "ng/L": ["ng/l", "ng l⁻¹", "nanogram per liter"],
    "s⁻¹": ["s-1", "/s", "per second", "sec⁻¹", "sec-1"],
    "min⁻¹": ["min-1", "/min", "per minute"],
    "M⁻¹s⁻¹": ["m-1 s-1", "m⁻¹·s⁻¹", "m-1·s-1", "/m/s"],
    "nm": ["nanometer", "nanometre"],
    "μm": ["um", "micrometer", "micrometre"],
    "mm": ["millimeter", "millimetre"],
    "°C": ["c", "deg c", "degree celsius", "celsius"],
    "K": ["kelvin"],
    "mg/mL": ["mg/ml", "mg·ml⁻¹", "mg ml⁻¹"],
    "μg/mL": ["ug/ml", "μg/ml", "μg·ml⁻¹", "ug ml⁻¹"],
    "ng/mL": ["ng/ml", "ng·ml⁻¹"],
    "pg/mL": ["pg/ml", "pg·ml⁻¹"],
    "g/L": ["g/l", "g·l⁻¹"],
    "U/mg": ["u/mg", "unit/mg", "units/mg"],
    "U/mL": ["u/ml", "unit/ml", "units/ml"],
}

_ALIAS_MAP = {}
for canonical, aliases in _UNIT_ALIASES.items():
    for alias in aliases:
        _ALIAS_MAP[alias.lower().strip()] = canonical


def normalize_unit_string(unit: str) -> Optional[str]:
    if not unit or not isinstance(unit, str):
        return unit
    cleaned = unit.strip().replace(" ", "").replace("·", "").replace("⁻¹", "-1").replace("⁻²", "-2")
    lower = cleaned.lower()
    if lower in _ALIAS_MAP:
        return _ALIAS_MAP[lower]
    for alias, canonical in _ALIAS_MAP.items():
        if lower == alias.replace(" ", "").lower():
            return canonical
    return unit


_CONVERSION_FACTORS = {
    ("mM", "M"): 1e-3,
    ("μM", "M"): 1e-6,
    ("nM", "M"): 1e-9,
    ("pM", "M"): 1e-12,
    ("μM", "mM"): 1e-3,
    ("nM", "mM"): 1e-6,
    ("nM", "μM"): 1e-3,
    ("pM", "μM"): 1e-6,
    ("μg/mL", "mg/L"): 1.0,
    ("ng/mL", "μg/L"): 1.0,
    ("ng/mL", "mg/L"): 1e-3,
    ("pg/mL", "ng/mL"): 1e-3,
    ("pg/mL", "μg/L"): 1e-3,
    ("nm", "μm"): 1e-3,
    ("nm", "mm"): 1e-6,
    ("μm", "mm"): 1e-3,
    ("min⁻¹", "s⁻¹"): 1.0 / 60,
}


def convert_value(value: float, from_unit: str, to_unit: str) -> Optional[float]:
    if from_unit == to_unit:
        return value
    fu = normalize_unit_string(from_unit) or from_unit
    tu = normalize_unit_string(to_unit) or to_unit
    if fu == tu:
        return value
    key = (fu, tu)
    if key in _CONVERSION_FACTORS:
        return value * _CONVERSION_FACTORS[key]
    rev_key = (tu, fu)
    if rev_key in _CONVERSION_FACTORS:
        factor = _CONVERSION_FACTORS[rev_key]
        if factor != 0:
            return value / factor
    return None


def normalize_record_units(record: Dict[str, Any], target_units: Dict[str, str] = None) -> Tuple[Dict[str, Any], List[str]]:
    changes = []
    target_units = target_units or {}

    kin = record.get("main_activity", {}).get("kinetics", {})
    for val_key, unit_key in [("Km", "Km_unit"), ("Vmax", "Vmax_unit"),
                               ("kcat", "kcat_unit"), ("kcat_Km", "kcat_Km_unit")]:
        val = kin.get(val_key)
        unit = kin.get(unit_key)
        if val is not None and unit:
            normed = normalize_unit_string(unit)
            if normed and normed != unit:
                kin[unit_key] = normed
                changes.append(f"kinetics.{unit_key}: {unit} -> {normed}")
            target = target_units.get(val_key)
            if target and normed != target:
                converted = convert_value(float(val), normed, target)
                if converted is not None:
                    kin[val_key] = converted
                    kin[unit_key] = target
                    changes.append(f"kinetics.{val_key}: {val} {normed} -> {converted} {target}")

    sel = record.get("selected_nanozyme", {})
    size_unit = sel.get("size_unit")
    if size_unit:
        normed = normalize_unit_string(size_unit)
        if normed and normed != size_unit:
            sel["size_unit"] = normed
            changes.append(f"selected_nanozyme.size_unit: {size_unit} -> {normed}")

    for app in record.get("applications", []):
        dl_unit = app.get("detection_limit_unit")
        if dl_unit:
            normed = normalize_unit_string(dl_unit)
            if normed and normed != dl_unit:
                app["detection_limit_unit"] = normed
                changes.append(f"application.detection_limit_unit: {dl_unit} -> {normed}")

    for iv in record.get("important_values", []):
        iv_unit = iv.get("unit")
        if iv_unit and isinstance(iv_unit, str):
            normed = normalize_unit_string(iv_unit)
            if normed and normed != iv_unit:
                iv["unit"] = normed
                changes.append(f"important_values.unit: {iv_unit} -> {normed}")

    return record, changes


def batch_normalize(results_dir: str, output_dir: str = None, target_units: Dict[str, str] = None) -> List[str]:
    results_path = Path(results_dir)
    output_path = Path(output_dir) if output_dir else results_path
    output_path.mkdir(parents=True, exist_ok=True)
    all_changes = []
    for jf in results_path.glob("*.json"):
        try:
            with open(jf, "r", encoding="utf-8") as f:
                record = json.load(f)
            record, changes = normalize_record_units(record, target_units)
            if changes:
                out_file = output_path / jf.name
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(record, f, ensure_ascii=False, indent=2)
                all_changes.extend([f"{jf.name}: {c}" for c in changes])
                logger.info(f"Normalized {jf.name}: {len(changes)} changes")
        except Exception as e:
            logger.error(f"Failed to process {jf}: {e}")
    return all_changes


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("Usage: python unit_normalizer.py <results_dir> [output_dir]")
        sys.exit(1)
    rdir = sys.argv[1]
    odir = sys.argv[2] if len(sys.argv) > 2 else None
    changes = batch_normalize(rdir, odir)
    if changes:
        print(f"Applied {len(changes)} unit normalizations:")
        for c in changes:
            print(f"  {c}")
    else:
        print("No unit normalizations needed.")
