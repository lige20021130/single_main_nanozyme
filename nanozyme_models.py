import re
import logging
from enum import Enum
from typing import Dict, List, Any

from domain_knowledge import get_domain_knowledge

logger = logging.getLogger(__name__)

_dk = get_domain_knowledge()

_ENZYME_ALIAS_MAP: Dict[str, str] = _dk.get_enzyme_alias_map()

_EnzymeTypeMembers = {
    v.upper().replace("-", "_").replace(" ", "_").replace(".", "_"): v
    for v in _dk.get_enzyme_type_values()
}

EnzymeType = Enum("EnzymeType", _EnzymeTypeMembers)


def _make_normalize_enzyme(cls):
    @classmethod
    def normalize_canonical(cls_, value: str) -> str:
        if not value:
            return value
        key = value.strip().lower()

        if key in _ENZYME_ALIAS_MAP:
            return _ENZYME_ALIAS_MAP[key]

        hyphen_key = key.replace("_", "-")
        if hyphen_key in _ENZYME_ALIAS_MAP:
            return _ENZYME_ALIAS_MAP[hyphen_key]

        cleaned = re.sub(r'\s*\([A-Za-z]+\)\s*', ' ', key).strip()
        cleaned = re.sub(r'\s+', '-', cleaned)
        if cleaned in _ENZYME_ALIAS_MAP:
            return _ENZYME_ALIAS_MAP[cleaned]

        cleaned_hyphen = cleaned.replace("_", "-")
        if cleaned_hyphen in _ENZYME_ALIAS_MAP:
            return _ENZYME_ALIAS_MAP[cleaned_hyphen]

        for member in cls_:
            if member.value.lower() == cleaned:
                return member.value
        for member in cls_:
            if member.value.lower() == key:
                return member.value
        for member in cls_:
            if member.value.lower() == hyphen_key:
                return member.value
        return value

    return normalize_canonical


EnzymeType.normalize_canonical = _make_normalize_enzyme(EnzymeType)

_dk_registry = _dk.get_enzyme_registry()
ENZYME_REGISTRY: Dict[EnzymeType, Dict[str, Any]] = {}
for _member in EnzymeType:
    _val = _member.value
    if _val in _dk_registry:
        ENZYME_REGISTRY[_member] = _dk_registry[_val]
    else:
        ENZYME_REGISTRY[_member] = {
            "keywords": [_val],
            "substrates": [],
            "assay_keywords": [],
        }


def get_all_enzyme_keywords() -> List[str]:
    keywords = []
    for meta in ENZYME_REGISTRY.values():
        keywords.extend(meta["keywords"])
    return keywords


def get_all_substrate_keywords() -> List[str]:
    substrates = []
    for meta in ENZYME_REGISTRY.values():
        substrates.extend(meta["substrates"])
    return list(dict.fromkeys(substrates))


def get_enzyme_type_enum_string() -> str:
    return " | ".join(f'"{e.value}"' for e in EnzymeType)


def get_assay_type_enum_string() -> str:
    return '"colorimetric" | "fluorometric" | "spectrophotometric" | "electrochemical" | "chemiluminescent" | "other"'


_APPLICATION_TYPE_ALIAS_MAP: Dict[str, str] = _dk.get_application_alias_map()

_AppTypeMembers = {
    v.upper().replace("-", "_").replace(" ", "_"): v
    for v in _dk.get_application_type_values()
}

ApplicationType = Enum("ApplicationType", _AppTypeMembers)


def _make_normalize_application(cls):
    @classmethod
    def normalize_canonical(cls_, value: str) -> str:
        if not value:
            return value
        key = value.strip().lower()
        if key in _APPLICATION_TYPE_ALIAS_MAP:
            return _APPLICATION_TYPE_ALIAS_MAP[key]
        for member in cls_:
            if member.value.lower() == key:
                return member.value
        return value

    return normalize_canonical


ApplicationType.normalize_canonical = _make_normalize_application(ApplicationType)


def get_application_type_enum_string() -> str:
    return " | ".join(f'"{e.value}"' for e in ApplicationType)
