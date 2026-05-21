import logging
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

_YAML_PATH = Path(__file__).parent / "domain_knowledge.yaml"

_instance: Optional["DomainKnowledge"] = None


class DomainKnowledge:
    def __init__(self, yaml_path: Optional[Path] = None):
        path = yaml_path or _YAML_PATH
        if not path.exists():
            raise FileNotFoundError(f"Domain knowledge YAML not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f)
        self._enzyme_alias_map: Optional[Dict[str, str]] = None
        self._application_alias_map: Optional[Dict[str, str]] = None
        logger.info(
            "[DomainKnowledge] Loaded from %s: %d enzyme types, %d application types",
            path,
            len(self._data.get("enzyme_types", [])),
            len(self._data.get("application_types", [])),
        )

    @property
    def enzyme_types(self) -> List[Dict[str, Any]]:
        return self._data.get("enzyme_types", [])

    @property
    def application_types(self) -> List[Dict[str, Any]]:
        return self._data.get("application_types", [])

    @property
    def probe_molecules(self) -> Dict[str, Any]:
        return self._data.get("probe_molecules", {})

    @property
    def numeric_ranges(self) -> Dict[str, Any]:
        return self._data.get("numeric_ranges", {})

    @property
    def unit_conversion(self) -> Dict[str, Any]:
        return self._data.get("unit_conversion", {})

    def get_enzyme_type_values(self) -> List[str]:
        return [et["value"] for et in self.enzyme_types]

    def get_enzyme_alias_map(self) -> Dict[str, str]:
        if self._enzyme_alias_map is not None:
            return self._enzyme_alias_map
        alias_map: Dict[str, str] = {}
        for et in self.enzyme_types:
            canonical = et["value"]
            alias_map[canonical] = canonical
            for alias in et.get("aliases", []):
                alias_map[alias.lower()] = canonical
        self._enzyme_alias_map = alias_map
        return alias_map

    def get_application_type_values(self) -> List[str]:
        return [at["value"] for at in self.application_types]

    def get_application_alias_map(self) -> Dict[str, str]:
        if self._application_alias_map is not None:
            return self._application_alias_map
        alias_map: Dict[str, str] = {}
        for at in self.application_types:
            canonical = at["value"]
            alias_map[canonical] = canonical
            for alias in at.get("aliases", []):
                alias_map[alias.lower()] = canonical
        self._application_alias_map = alias_map
        return alias_map

    def get_probe_molecule_names(self) -> set:
        names: set = set()
        for pm in self.probe_molecules.get("examples", []):
            names.add(pm["name"].lower())
            for alias in pm.get("aliases", []):
                names.add(alias.lower())
        return names

    def get_substrate_enzyme_mapping(self) -> Dict[str, List[str]]:
        return self._data.get("common_substrate_enzyme_mapping", {})

    def get_numeric_range(self, param: str) -> Dict[str, Any]:
        return self.numeric_ranges.get(param, {})

    def get_all_substrates(self) -> List[str]:
        seen: set = set()
        result: List[str] = []
        for et in self.enzyme_types:
            for sub in et.get("substrates", []):
                if sub not in seen:
                    seen.add(sub)
                    result.append(sub)
        return result

    def get_enzyme_registry(self) -> Dict[str, Dict[str, Any]]:
        registry: Dict[str, Dict[str, Any]] = {}
        for et in self.enzyme_types:
            registry[et["value"]] = {
                "keywords": et.get("aliases", []) + [et["value"]],
                "substrates": et.get("substrates", []),
                "assay_keywords": et.get("assay_keywords", []),
            }
        return registry

    def generate_enzyme_type_prompt_snippet(self) -> str:
        values = self.get_enzyme_type_values()
        return " | ".join(f'"{v}"' for v in values)

    def generate_application_type_prompt_snippet(self) -> str:
        values = self.get_application_type_values()
        return " | ".join(f'"{v}"' for v in values)

    def generate_substrate_prompt_snippet(self) -> str:
        substrates = self.get_all_substrates()
        return ", ".join(substrates)

    def generate_probe_molecule_prompt_snippet(self) -> str:
        names = [pm["name"] for pm in self.probe_molecules.get("examples", [])]
        return ", ".join(names)

    def get_enzyme_type_regex_patterns(self) -> List[Tuple[re.Pattern, str]]:
        if hasattr(self, '_regex_patterns_cache') and self._regex_patterns_cache is not None:
            return self._regex_patterns_cache
        patterns: List[Tuple[re.Pattern, str]] = []
        for entry in self._data.get("enzyme_type_regex_patterns", []):
            canonical = entry["canonical"]
            for pat_str in entry.get("patterns", []):
                patterns.append((re.compile(rf'\b{pat_str}\b', re.I), canonical))
        self._regex_patterns_cache = patterns
        return patterns

    def get_enzyme_specific_km_ranges(self) -> Dict[str, Tuple[float, float, str]]:
        result: Dict[str, Tuple[float, float, str]] = {}
        for etype, info in self._data.get("enzyme_specific_km_ranges", {}).items():
            result[etype] = (info["min"], info["max"], info["unit"])
        return result

    def get_enzyme_specific_vmax_ranges(self) -> Dict[str, Tuple[float, float, str]]:
        result: Dict[str, Tuple[float, float, str]] = {}
        for etype, info in self._data.get("enzyme_specific_vmax_ranges", {}).items():
            result[etype] = (info["min"], info["max"], info["unit"])
        return result

    def get_analyte_enzyme_incompatibility(self) -> Dict[str, Dict[str, str]]:
        return self._data.get("analyte_enzyme_incompatibility", {})

    def get_analyte_enzyme_compatibility(self) -> Dict[str, List[str]]:
        raw = self._data.get("analyte_enzyme_compatibility", {})
        return {k: [v.lower() for v in vs] for k, vs in raw.items()}

    def generate_substrate_knowledge_prompt(self) -> str:
        lines = []
        for et in self.enzyme_types:
            substrates = et.get("substrates", [])
            if substrates:
                lines.append(f"Common substrates for {et['value']}: {', '.join(substrates)}")
        return "\n".join(lines)


def get_domain_knowledge() -> DomainKnowledge:
    global _instance
    if _instance is None:
        _instance = DomainKnowledge()
    return _instance
