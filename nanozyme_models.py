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
    "glucose oxidase (gox)-like": "glucose-oxidase-like",
    "gox-like": "glucose-oxidase-like",
    "phosphatase (alp)-like": "phosphatase-like",
    "alp-like": "phosphatase-like",
    "nitroreductase (ntr)-like": "nitroreductase-like",
    "ntr-like": "nitroreductase-like",
    "glutathione oxidase (gshox)-like": "glutathione-oxidase-like",
    "gshox-like": "glutathione-oxidase-like",
    "haloperoxidase (vhpo)-like": "haloperoxidase-like",
    "vhpo-like": "haloperoxidase-like",
    "multi-enzyme-like": "multi-enzyme-like",
    "dual-enzyme-like": "multi-enzyme-like",
    "triple-enzyme-like": "multi-enzyme-like",
    "ribozyme-like": "ribozyme-like",
    "cellulase-like": "cellulase-like",
    "amylase-like": "amylase-like",
    "protease-like": "protease-like",
    "lipase-like": "lipase-like",
    "urease-like": "urease-like",
    "ascorbate-oxidase-like": "ascorbate-oxidase-like",
    "aao-like": "ascorbate-oxidase-like",
    "dehydrogenase-like": "dehydrogenase-like",
    "invertase-like": "invertase-like",
    "chitinase-like": "chitinase-like",
    "xylanase-like": "xylanase-like",
    "ferroxidase-like": "ferroxidase-like",
    "glutathione-reductase-like": "glutathione-reductase-like",
    "gr-like": "glutathione-reductase-like",
    "superoxide-oxidase-like": "superoxide-oxidase-like",
    "soo-like": "superoxide-oxidase-like",
    "peroxynitritase-like": "peroxynitritase-like",
    "nadh-peroxidase-like": "NADH-peroxidase-like",
    "thioredoxin-reductase-like": "thioredoxin-reductase-like",
    "trxr-like": "thioredoxin-reductase-like",
    "glutathione-transferase-like": "glutathione-transferase-like",
    "gst-like": "glutathione-transferase-like",
    "monooxygenase-like": "monooxygenase-like",
    "dioxygenase-like": "dioxygenase-like",
    "sulfite-oxidase-like": "sulfite-oxidase-like",
    "peroxidase-mimicking": "peroxidase-like",
    "oxidase-mimicking": "oxidase-like",
    "catalase-mimicking": "catalase-like",
    "sod-mimicking": "superoxide-dismutase-like",
    "gpx-mimicking": "glutathione-peroxidase-like",
    "gox-mimicking": "glucose-oxidase-like",
    "peroxidase-mimic": "peroxidase-like",
    "oxidase-mimic": "oxidase-like",
    "catalase-mimic": "catalase-like",
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
    GLUCOSE_OXIDASE = "glucose-oxidase-like"
    GLUTATHIONE_OXIDASE = "glutathione-oxidase-like"
    NUCLEASE = "nuclease-like"
    TYROSINASE = "tyrosinase-like"
    CASCADE_ENZYMATIC = "cascade-enzymatic"
    MULTI_ENZYME = "multi-enzyme-like"
    RIBOZYME = "ribozyme-like"
    CELLULASE = "cellulase-like"
    AMYLASE = "amylase-like"
    PROTEASE = "protease-like"
    LIPASE = "lipase-like"
    UREASE = "urease-like"
    ASCORBATE_OXIDASE = "ascorbate-oxidase-like"
    DEHYDROGENASE = "dehydrogenase-like"
    INVERTASE = "invertase-like"
    CHITINASE = "chitinase-like"
    XYLANASE = "xylanase-like"
    FERROXIDASE = "ferroxidase-like"
    GLUTATHIONE_REDUCTASE = "glutathione-reductase-like"
    SUPEROXIDE_OXIDASE = "superoxide-oxidase-like"
    PEROXYNITRITASE = "peroxynitritase-like"
    NADH_PEROXIDASE = "NADH-peroxidase-like"
    THIOREDOXIN_REDUCTASE = "thioredoxin-reductase-like"
    GLUTATHIONE_TRANSFERASE = "glutathione-transferase-like"
    MONOOXYGENASE = "monooxygenase-like"
    DIOXYGENASE = "dioxygenase-like"
    SULFITE_OXIDASE = "sulfite-oxidase-like"

    @classmethod
    def normalize_canonical(cls, value: str) -> str:
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

        for member in cls:
            if member.value.lower() == cleaned:
                return member.value
        for member in cls:
            if member.value.lower() == key:
                return member.value
        for member in cls:
            if member.value.lower() == hyphen_key:
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
    EnzymeType.GLUCOSE_OXIDASE: {
        "keywords": ["glucose oxidase-like", "GOx-like", "glucose oxidase mimetic", "GOx activity"],
        "substrates": ["glucose", "O2"],
        "assay_keywords": ["glucose oxidase assay", "glucose detection"],
    },
    EnzymeType.GLUTATHIONE_OXIDASE: {
        "keywords": ["glutathione oxidase-like", "GSHOx-like", "glutathione oxidase mimetic"],
        "substrates": ["GSH", "O2"],
        "assay_keywords": ["glutathione oxidase assay", "GSH oxidation"],
    },
    EnzymeType.NUCLEASE: {
        "keywords": ["nuclease-like", "nuclease mimetic", "DNA cleavage", "RNA cleavage"],
        "substrates": ["DNA", "RNA", "oligonucleotides"],
        "assay_keywords": ["nuclease assay", "DNA cleavage assay"],
    },
    EnzymeType.TYROSINASE: {
        "keywords": ["tyrosinase-like", "tyrosinase mimetic", "polyphenol oxidase-like"],
        "substrates": ["L-DOPA", "tyrosine", "phenol", "catechol"],
        "assay_keywords": ["tyrosinase assay", "L-DOPA oxidation"],
    },
    EnzymeType.CASCADE_ENZYMATIC: {
        "keywords": ["cascade enzymatic", "cascade enzyme activity", "multi-enzyme cascade", "enzyme cascade"],
        "substrates": [],
        "assay_keywords": ["cascade assay", "sequential reaction"],
    },
    EnzymeType.MULTI_ENZYME: {
        "keywords": ["multi-enzyme-like", "dual-enzyme-like", "triple-enzyme-like", "multi-enzyme activity"],
        "substrates": ["TMB", "H2O2", "ABTS", "OPD"],
        "assay_keywords": ["multi-enzyme assay", "dual-enzyme activity"],
    },
    EnzymeType.RIBOZYME: {
        "keywords": ["ribozyme-like", "ribozyme mimetic", "ribozyme activity"],
        "substrates": ["RNA", "DNA", "oligonucleotides"],
        "assay_keywords": ["ribozyme assay", "RNA cleavage"],
    },
    EnzymeType.CELLULASE: {
        "keywords": ["cellulase-like", "cellulase mimetic", "cellulase activity"],
        "substrates": ["CMC", "carboxymethyl cellulose", "cellulose", "filter paper"],
        "assay_keywords": ["cellulase assay", "CMC hydrolysis", "DNS assay"],
    },
    EnzymeType.AMYLASE: {
        "keywords": ["amylase-like", "amylase mimetic", "amylase activity", "α-amylase-like"],
        "substrates": ["starch", "amylose", "amylopectin", "soluble starch"],
        "assay_keywords": ["amylase assay", "starch hydrolysis", "DNS method"],
    },
    EnzymeType.PROTEASE: {
        "keywords": ["protease-like", "protease mimetic", "protease activity"],
        "substrates": ["casein", "BSA", "gelatin", "peptide"],
        "assay_keywords": ["protease assay", "casein hydrolysis"],
    },
    EnzymeType.LIPASE: {
        "keywords": ["lipase-like", "lipase mimetic", "lipase activity"],
        "substrates": ["p-NPB", "p-nitrophenyl butyrate", "triolein", "olive oil"],
        "assay_keywords": ["lipase assay", "p-NPB hydrolysis", "ester hydrolysis"],
    },
    EnzymeType.UREASE: {
        "keywords": ["urease-like", "urease mimetic", "urease activity"],
        "substrates": ["urea"],
        "assay_keywords": ["urease assay", "urea hydrolysis", "phenol red method"],
    },
    EnzymeType.ASCORBATE_OXIDASE: {
        "keywords": ["ascorbate oxidase-like", "AAO-like", "ascorbate oxidase mimetic", "ascorbate oxidase activity"],
        "substrates": ["ascorbic acid", "AA", "vitamin C"],
        "assay_keywords": ["ascorbate oxidase assay", "AA oxidation"],
    },
    EnzymeType.DEHYDROGENASE: {
        "keywords": ["dehydrogenase-like", "dehydrogenase mimetic", "dehydrogenase activity",
                     "formate dehydrogenase-like", "alcohol dehydrogenase-like", "glucose dehydrogenase-like"],
        "substrates": ["NADH", "NAD+", "formate", "ethanol", "glucose"],
        "assay_keywords": ["dehydrogenase assay", "NADH oxidation"],
    },
    EnzymeType.NUCLEASE: {
        "keywords": ["nuclease-like", "nuclease mimetic", "DNA cleavage", "RNA cleavage", "DNase-like", "RNase-like"],
        "substrates": ["DNA", "RNA", "oligonucleotides", "plasmid DNA"],
        "assay_keywords": ["nuclease assay", "DNA cleavage assay", "gel electrophoresis"],
    },
    EnzymeType.TYROSINASE: {
        "keywords": ["tyrosinase-like", "tyrosinase mimetic", "polyphenol oxidase-like", "tyrosinase activity"],
        "substrates": ["L-DOPA", "tyrosine", "phenol", "catechol"],
        "assay_keywords": ["tyrosinase assay", "L-DOPA oxidation"],
    },
    EnzymeType.INVERTASE: {
        "keywords": ["invertase-like", "invertase mimetic", "invertase activity", "sucrase-like"],
        "substrates": ["sucrose", "saccharose"],
        "assay_keywords": ["invertase assay", "sucrose hydrolysis", "DNS method"],
    },
    EnzymeType.CHITINASE: {
        "keywords": ["chitinase-like", "chitinase mimetic", "chitinase activity"],
        "substrates": ["chitin", "colloidal chitin", "CM-chitin"],
        "assay_keywords": ["chitinase assay", "chitin hydrolysis"],
    },
    EnzymeType.XYLANASE: {
        "keywords": ["xylanase-like", "xylanase mimetic", "xylanase activity"],
        "substrates": ["xylan", "beechwood xylan", "birchwood xylan"],
        "assay_keywords": ["xylanase assay", "xylan hydrolysis", "DNS method"],
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


_APPLICATION_TYPE_ALIAS_MAP: Dict[str, str] = {
    "detection": "sensing",
    "colorimetric detection": "sensing",
    "colorimetric sensing": "sensing",
    "biosensing": "sensing",
    "biosensor": "sensing",
    "determination": "sensing",
    "monitoring": "sensing",
    "assay": "sensing",
    "diagnostic": "sensing",
    "diagnosis": "sensing",
    "imaging": "bioimaging",
    "bioimaging": "bioimaging",
    "cell imaging": "bioimaging",
    "fluorescence imaging": "bioimaging",
    "mr imaging": "bioimaging",
    "photoacoustic imaging": "bioimaging",
    "sensor": "sensing",
    "therapy": "therapeutic",
    "antitumor": "therapeutic",
    "tumor therapy": "therapeutic",
    "wound healing": "therapeutic",
    "phototherapy": "therapeutic",
    "photothermal therapy": "therapeutic",
    "chemodynamic therapy": "therapeutic",
    "sonodynamic therapy": "therapeutic",
    "photodynamic therapy": "therapeutic",
    "starvation therapy": "therapeutic",
    "gas therapy": "therapeutic",
    "cytoprotection": "cytoprotection",
    "cell protection": "cytoprotection",
    "neuroprotection": "cytoprotection",
    "cardioprotection": "cytoprotection",
    "anti-inflammation": "antioxidant",
    "ros scavenging": "antioxidant",
    "free radical scavenging": "antioxidant",
    "oxidative stress protection": "antioxidant",
    "radioprotection": "antioxidant",
    "anti-infection": "antibacterial",
    "antibacterial activity": "antibacterial",
    "sterilization": "antibacterial",
    "bacteriostatic": "antibacterial",
    "biocidal": "antibacterial",
    "degradation": "environmental",
    "water treatment": "environmental",
    "pollutant removal": "environmental",
    "organic pollutant degradation": "environmental",
    "waste water": "environmental",
    "heavy metal detection": "environmental",
    "biofilm inhibition": "biofilm_inhibition",
    "anti-biofilm": "biofilm_inhibition",
}


class ApplicationType(Enum):
    SENSING = "sensing"
    THERAPEUTIC = "therapeutic"
    ANTIBACTERIAL = "antibacterial"
    ENVIRONMENTAL = "environmental"
    ANTIOXIDANT = "antioxidant"
    BIOFILM_INHIBITION = "biofilm_inhibition"
    CYTOPROTECTION = "cytoprotection"
    BIOIMAGING = "bioimaging"
    OTHER = "other"

    @classmethod
    def normalize_canonical(cls, value: str) -> str:
        if not value:
            return value
        key = value.strip().lower()
        if key in _APPLICATION_TYPE_ALIAS_MAP:
            return _APPLICATION_TYPE_ALIAS_MAP[key]
        for member in cls:
            if member.value.lower() == key:
                return member.value
        return value


def get_application_type_enum_string() -> str:
    return " | ".join(f'"{e.value}"' for e in ApplicationType)


def get_figure_type_enum_string() -> str:
    return '"SEM" | "TEM" | "XRD" | "XPS" | "Raman" | "FTIR" | "EPR" | "AFM" | "UV-vis" | "kinetics_plot" | "calibration_curve" | "mechanism_diagram" | "application_result" | "other"'
