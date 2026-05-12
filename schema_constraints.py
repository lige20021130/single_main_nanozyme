import json
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

_ENZYME_TYPE_ENUM = [
    "peroxidase-like", "oxidase-like", "catalase-like",
    "superoxide-dismutase-like", "glutathione-peroxidase-like",
    "esterase-like", "nitroreductase-like", "hydrolase-like",
    "phosphatase-like", "laccase-like", "haloperoxidase-like",
    "glucose-oxidase-like", "glutathione-oxidase-like",
    "nuclease-like", "tyrosinase-like", "cascade-enzymatic",
    "multi-enzyme-like", "ribozyme-like", "cellulase-like",
    "amylase-like", "protease-like", "lipase-like", "urease-like",
    "ascorbate-oxidase-like", "dehydrogenase-like", "invertase-like",
    "chitinase-like", "xylanase-like",
]

_APPLICATION_TYPE_ENUM = [
    "sensing", "therapeutic", "antibacterial", "environmental",
    "antioxidant", "biofilm_inhibition", "other",
]

_SIZE_UNIT_ENUM = ["nm", "μm", "um", "mm", "μM", None]

_KM_UNIT_ENUM = ["M", "mM", "μM", "uM", "nM", "mM·min", None]

_VMAX_UNIT_ENUM = [
    "M/s", "M·s-1", "M s^-1",
    "mM/s", "mM·s-1",
    "μM/s", "uM/s", "μM·s-1",
    "nM/s",
    "μM/min", "uM/min",
    None,
]

_KCAT_UNIT_ENUM = ["s⁻¹", "s-1", "min⁻¹", "min-1", None]

_KCAT_KM_UNIT_ENUM = ["M⁻¹s⁻¹", "M-1s-1", "M⁻¹min⁻¹", None]

try:
    from pydantic import BaseModel, Field, field_validator
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False
    BaseModel = object
    Field = lambda *a, **kw: None
    field_validator = lambda *a, **kw: lambda f: f

if PYDANTIC_AVAILABLE:
    class KineticsEntryModel(BaseModel):
        Km: float | None = None
        Km_unit: str | None = None
        Vmax: float | None = None
        Vmax_unit: str | None = None
        kcat: float | None = None
        kcat_unit: str | None = None
        kcat_Km: float | None = None
        kcat_Km_unit: str | None = None
        substrate: str | None = None
        detection_method: str | None = None
        material_variant: str | None = None

    class SynthesisConditionsModel(BaseModel):
        temperature: float | None = None
        time: str | None = None
        precursors: list[str] = Field(default_factory=list)
        solvent: str | None = None
        atmosphere: str | None = None
        post_treatment: str | None = None

    class ApplicationEntryModel(BaseModel):
        application_type: str | None = None
        target_analyte: str | None = None
        detection_limit: float | None = None
        detection_limit_unit: str | None = None
        method: str | None = None
        sample_type: str | None = None

        @field_validator("application_type")
        @classmethod
        def validate_app_type(cls, v):
            if v and v not in _APPLICATION_TYPE_ENUM:
                raise ValueError(f"application_type '{v}' not in allowed enum")
            return v

    class NanozymeExtractionModel(BaseModel):
        enzyme_like_type: str | None = None
        kinetics: KineticsEntryModel | None = None
        kinetics_list: list[KineticsEntryModel] = Field(default_factory=list)
        morphology: str | None = None
        size: float | None = None
        size_unit: str | None = None
        crystal_structure: str | None = None
        surface_area: str | None = None
        synthesis_method: str | None = None
        synthesis_conditions: SynthesisConditionsModel | None = None
        characterization: list[str] = Field(default_factory=list)
        applications: list[ApplicationEntryModel] = Field(default_factory=list)
        pH_profile: dict | None = None
        temperature_profile: dict | None = None
else:
    KineticsEntryModel = None
    SynthesisConditionsModel = None
    ApplicationEntryModel = None
    NanozymeExtractionModel = None


NANOZYME_KINETICS_SCHEMA = {
    "type": "object",
    "properties": {
        "Km": {"type": ["number", "null"]},
        "Km_unit": {"type": ["string", "null"]},
        "Vmax": {"type": ["number", "null"]},
        "Vmax_unit": {"type": ["string", "null"]},
        "kcat": {"type": ["number", "null"]},
        "kcat_unit": {"type": ["string", "null"]},
        "kcat_Km": {"type": ["number", "null"]},
        "kcat_Km_unit": {"type": ["string", "null"]},
        "substrate": {"type": ["string", "null"]},
        "detection_method": {"type": ["string", "null"]},
        "material_variant": {"type": ["string", "null"]},
    },
    "required": [],
}

NANOZYME_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "selected_nanozyme": {
            "type": "object",
            "properties": {
                "name": {"type": ["string", "null"]},
                "morphology": {"type": ["string", "null"]},
                "size": {"type": ["number", "string", "null"]},
                "size_unit": {"type": ["string", "null"]},
                "crystal_structure": {"type": ["string", "null"]},
                "surface_area": {"type": ["string", "null"]},
                "synthesis_method": {"type": ["string", "null"]},
                "synthesis_conditions": {
                    "type": "object",
                    "properties": {
                        "temperature": {"type": ["number", "string", "null"]},
                        "time": {"type": ["string", "null"]},
                        "precursors": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                    },
                },
                "characterization": {
                    "type": "array",
                    "items": {"type": "string"}
                },
            },
            "required": ["name"]
        },
        "main_activity": {
            "type": "object",
            "properties": {
                "enzyme_like_type": {
                    "type": ["string", "null"],
                },
                "substrates": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "kinetics": NANOZYME_KINETICS_SCHEMA,
                "kinetics_list": {
                    "type": "array",
                    "items": NANOZYME_KINETICS_SCHEMA,
                },
                "pH_profile": {
                    "type": "object",
                    "properties": {
                        "optimal_pH": {"type": ["number", "null"]},
                        "pH_range": {"type": ["string", "null"]},
                    },
                },
                "temperature_profile": {
                    "type": "object",
                    "properties": {
                        "optimal_temperature": {"type": ["number", "null"]},
                        "temperature_range": {"type": ["string", "null"]},
                    },
                },
            },
        },
        "applications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "application_type": {"type": ["string", "null"]},
                    "target_analyte": {"type": ["string", "null"]},
                    "detection_limit": {"type": ["number", "null"]},
                    "detection_limit_unit": {"type": ["string", "null"]},
                    "method": {"type": ["string", "null"]},
                    "sample_type": {"type": ["string", "null"]},
                },
            }
        },
    },
    "required": ["selected_nanozyme", "main_activity"]
}


def get_enzyme_type_enum_string() -> str:
    return " | ".join(f'"{e}"' for e in _ENZYME_TYPE_ENUM)


def get_application_type_enum_string() -> str:
    return " | ".join(f'"{a}"' for a in _APPLICATION_TYPE_ENUM)


def get_schema_for_openai() -> Dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "nanozyme_extraction",
            "strict": True,
            "schema": NANOZYME_EXTRACTION_SCHEMA,
        }
    }


def validate_against_schema(data: Dict[str, Any]) -> List[str]:
    errors = []

    sel = data.get("selected_nanozyme", {})
    if not isinstance(sel, dict) or not sel.get("name"):
        errors.append("selected_nanozyme.name is required")

    ma = data.get("main_activity", {})
    etype = ma.get("enzyme_like_type")
    if etype and etype not in _ENZYME_TYPE_ENUM:
        errors.append(f"enzyme_like_type '{etype}' not in allowed enum")

    kin = ma.get("kinetics", {})
    if isinstance(kin, dict):
        km = kin.get("Km")
        km_u = kin.get("Km_unit", "")
        if isinstance(km, (int, float)) and km_u == "M" and km > 1.0:
            errors.append(f"Km={km} M is unrealistically large for nanozyme")
        if isinstance(km, (int, float)) and km_u == "mM" and km > 1000:
            errors.append(f"Km={km} mM is unrealistically large for nanozyme")

        vmax = kin.get("Vmax")
        vmax_u = kin.get("Vmax_unit", "")
        if isinstance(vmax, (int, float)) and vmax_u in ("M/s", "M·s-1", "M s^-1") and abs(vmax) < 1.0:
            errors.append(f"Vmax={vmax} {vmax_u} should be converted to μM/s (multiply by 1e6)")
        if isinstance(vmax, (int, float)) and vmax_u in ("mM/s", "mM·s-1") and abs(vmax) < 1.0:
            errors.append(f"Vmax={vmax} {vmax_u} should be converted to μM/s (multiply by 1e3)")

    for i, kl in enumerate(ma.get("kinetics_list", [])):
        if not isinstance(kl, dict):
            continue
        kl_km = kl.get("Km")
        kl_kmu = kl.get("Km_unit", "")
        if isinstance(kl_km, (int, float)) and kl_kmu == "M" and kl_km > 1.0:
            errors.append(f"kinetics_list[{i}].Km={kl_km} M is unrealistically large")
        kl_vmax = kl.get("Vmax")
        kl_vmaxu = kl.get("Vmax_unit", "")
        if isinstance(kl_vmax, (int, float)) and kl_vmaxu in ("M/s", "M·s-1", "M s^-1") and abs(kl_vmax) < 1.0:
            errors.append(f"kinetics_list[{i}].Vmax={kl_vmax} {kl_vmaxu} should be converted to μM/s")

    apps = data.get("applications", [])
    for i, app in enumerate(apps):
        if not isinstance(app, dict):
            continue
        at = app.get("application_type")
        if at and at not in _APPLICATION_TYPE_ENUM:
            errors.append(f"applications[{i}].application_type '{at}' not in allowed enum")

    return errors


def auto_fix_schema_errors(data: Dict[str, Any], errors: List[str]) -> Dict[str, Any]:
    for err in errors:
        if "unrealistically large" in err and "Km" in err:
            kin = data.get("main_activity", {}).get("kinetics", {})
            if isinstance(kin, dict):
                kin["Km"] = None
                kin["Km_unit"] = None
        elif "should be converted to μM/s" in err and "Vmax" in err:
            kin = data.get("main_activity", {}).get("kinetics", {})
            if isinstance(kin, dict):
                vmax = kin.get("Vmax")
                vmax_u = kin.get("Vmax_unit", "")
                if isinstance(vmax, (int, float)):
                    if vmax_u in ("M/s", "M·s-1", "M s^-1"):
                        kin["Vmax"] = vmax * 1e6
                        kin["Vmax_unit"] = "μM/s"
                    elif vmax_u in ("mM/s", "mM·s-1"):
                        kin["Vmax"] = vmax * 1e3
                        kin["Vmax_unit"] = "μM/s"
    return data
