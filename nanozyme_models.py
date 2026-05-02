import re
from enum import Enum
from typing import Dict, List, Any


_ENZYME_ALIAS_MAP: Dict[str, str] = {
    "peroxidase (pod)-like": "peroxidase-like",
    "pod-like": "peroxidase-like",
    "oxidase (oxd)-like": "oxidase-like",
    "oxd-like": "oxidase-like",
    "catalase (cat)-like": "catalase-like",
    "cat-like": "catalase-like",
    "superoxide dismutase (sod)-like": "superoxide-dismutase-like",
    "sod-like": "superoxide-dismutase-like",
    "glutathione peroxidase (gpx)-like": "glutathione-peroxidase-like",
    "gpx-like": "glutathione-peroxidase-like",
}


class EnzymeType(Enum):
    PEROXIDASE = "peroxidase-like"
    OXIDASE = "oxidase-like"
    CATALASE = "catalase-like"
    SUPEROXIDE_DISMUTASE = "superoxide-dismutase-like"
    GLUTATHIONE_PEROXIDASE = "glutathione-peroxidase-like"
    ESTERASE = "esterase-like"
    NITROREDUCTASE = "nitroreductase-like"
    HYDROLASE = "hydrolase-like"
    PHOSPHATASE = "phosphatase-like"
    LACCASE = "laccase-like"
    HALOPEROXIDASE = "haloperoxidase-like"

    @classmethod
    def normalize_canonical(cls, value: str) -> str:
        if not value:
            return value
        key = value.strip().lower()
        if key in _ENZYME_ALIAS_MAP:
            return _ENZYME_ALIAS_MAP[key]
        cleaned = re.sub(r'\s*\([A-Za-z]+\)\s*', ' ', key).strip()
        cleaned = re.sub(r'\s+', '-', cleaned)
        for member in cls:
            if member.value.lower() == cleaned:
                return member.value
        for member in cls:
            if member.value.lower() == key:
                return member.value
        return value


ENZYME_REGISTRY: Dict[EnzymeType, Dict[str, Any]] = {
    EnzymeType.PEROXIDASE: {
        "keywords": ["peroxidase-like", "peroxidase mimetic", "peroxidase activity", "POD-like", "POD activity"],
        "substrates": ["TMB", "ABTS", "OPD", "guaiacol", "pyrogallol", "o-phenylenediamine"],
        "assay_keywords": ["TMB assay", "ABTS assay", "colorimetric assay"],
    },
    EnzymeType.OXIDASE: {
        "keywords": ["oxidase-like", "oxidase mimetic", "oxidase activity", "OX-like", "OXD-like"],
        "substrates": ["TMB", "ABTS", "OPD", "DHF", "catechol"],
        "assay_keywords": ["oxidase assay", "TMB oxidation"],
    },
    EnzymeType.CATALASE: {
        "keywords": ["catalase-like", "catalase mimetic", "catalase activity", "CAT-like", "CAT activity"],
        "substrates": ["H2O2"],
        "assay_keywords": ["H2O2 decomposition", "catalase assay", "O2 evolution"],
    },
    EnzymeType.SUPEROXIDE_DISMUTASE: {
        "keywords": ["superoxide dismutase-like", "SOD-like", "SOD mimetic", "SOD activity", "superoxide dismutase activity"],
        "substrates": ["superoxide", "O2-"],
        "assay_keywords": ["SOD assay", "NBT", "pyrogallol autoxidation"],
    },
    EnzymeType.GLUTATHIONE_PEROXIDASE: {
        "keywords": ["glutathione peroxidase-like", "GPx-like", "GPx mimetic", "GPx activity"],
        "substrates": ["H2O2", "GSH"],
        "assay_keywords": ["GPx assay", "NADPH consumption"],
    },
    EnzymeType.ESTERASE: {
        "keywords": ["esterase-like", "esterase mimetic", "esterase activity"],
        "substrates": ["p-NPA", "p-nitrophenyl acetate"],
        "assay_keywords": ["esterase assay", "p-NPA hydrolysis"],
    },
    EnzymeType.NITROREDUCTASE: {
        "keywords": ["nitroreductase-like", "nitroreductase mimetic", "NTR-like", "NTR activity"],
        "substrates": ["nitrofurazone", "nitroaromatics", "4-nitrophenol"],
        "assay_keywords": ["nitroreductase assay", "nitro reduction"],
    },
    EnzymeType.HYDROLASE: {
        "keywords": ["hydrolase-like", "hydrolase mimetic", "hydrolase activity"],
        "substrates": ["p-NPA", "esters", "peptides"],
        "assay_keywords": ["hydrolase assay", "hydrolysis"],
    },
    EnzymeType.PHOSPHATASE: {
        "keywords": ["phosphatase-like", "phosphatase mimetic", "ALP-like", "ACP-like", "phosphatase activity"],
        "substrates": ["p-NPP", "BCIP", "pnpp"],
        "assay_keywords": ["phosphatase assay", "p-NPP hydrolysis"],
    },
    EnzymeType.LACCASE: {
        "keywords": ["laccase-like", "laccase mimetic", "laccase activity"],
        "substrates": ["ABTS", "syringaldazine", "guaiacol", "2,6-DMP"],
        "assay_keywords": ["laccase assay", "ABTS oxidation"],
    },
    EnzymeType.HALOPEROXIDASE: {
        "keywords": ["haloperoxidase-like", "haloperoxidase mimetic", "VHPO-like", "haloperoxidase activity"],
        "substrates": ["Br-", "I-", "Cl-"],
        "assay_keywords": ["haloperoxidase assay", "halogenation"],
    },
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


def get_application_type_enum_string() -> str:
    return '"sensing" | "therapeutic" | "antibacterial" | "environmental" | "antioxidant" | "biofilm_inhibition" | "other"'


def get_figure_type_enum_string() -> str:
    return '"SEM" | "TEM" | "XRD" | "XPS" | "Raman" | "FTIR" | "EPR" | "AFM" | "UV-vis" | "kinetics_plot" | "calibration_curve" | "mechanism_diagram" | "application_result" | "other"'
