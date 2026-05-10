import json
import re
import logging
import asyncio
from copy import deepcopy
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
from datetime import datetime

from dependencies import is_available, get_attr

logger = logging.getLogger(__name__)

if is_available("consistency_guard_agentic"):
    from consistency_guard_agentic import IssueSeverity
else:
    class IssueSeverity:
        LOW = type('Enum', (), {'value': 'low'})()
        MEDIUM = type('Enum', (), {'value': 'medium'})()
        HIGH = type('Enum', (), {'value': 'high'})()
        CRITICAL = type('Enum', (), {'value': 'critical'})()

_normalize_unit_fn = get_attr("numeric_validator", "normalize_unit")
_is_concentration_unit_fn = get_attr("numeric_validator", "is_concentration_unit")
_is_rate_unit_fn = get_attr("numeric_validator", "is_rate_unit")

EXTRACTION_MODE = "single_main_nanozyme"
SCHEMA_VERSION = "single_main_nanozyme.v2"

FORBIDDEN_OLD_FIELDS = frozenset({
    "nanozyme_systems", "catalytic_activities", "benchmark_records",
    "assay_graph", "systems_count", "activities_count",
    "single_record_assembler", "system_name",
    "selection_reason", "size_distribution", "dopants_or_defects",
    "zeta_potential", "pore_size", "stability", "composition_structured",
    "assay_method", "signal", "buffer", "reaction_time",
    "pH_stability_range", "thermal_stability", "method_detail",
})

EMPTY_RECORD = {
    "paper": {
        "title": None, "authors": None, "journal": None,
        "year": None, "doi": None, "source_file": None, "document_kind": None,
    },
    "selected_nanozyme": {
        "name": None, "composition": None,
        "morphology": None, "size": None, "size_unit": None,
        "metal_elements": [],
        "synthesis_method": None,
        "synthesis_conditions": {
            "temperature": None, "time": None, "precursors": [],
        },
        "crystal_structure": None, "surface_area": None,
        "characterization": [],
    },
    "main_activity": {
        "enzyme_like_type": None, "substrates": [],
        "conditions": {
            "pH": None, "temperature": None,
        },
        "pH_profile": {
            "optimal_pH": None, "pH_range": None,
        },
        "temperature_profile": {
            "optimal_temperature": None, "temperature_range": None,
        },
        "kinetics": {
            "Km": None, "Km_unit": None, "Vmax": None, "Vmax_unit": None,
            "kcat": None, "kcat_unit": None,
            "kcat_Km": None, "kcat_Km_unit": None,
            "substrate": None, "source": None, "needs_review": False,
            "_evidence_Km": None, "_evidence_Vmax": None,
            "_evidence_kcat": None, "_evidence_kcat_Km": None,
        },
        "kinetics_list": [],
        "mechanism": None,
    },
    "applications": [],
    "important_values": [],
    "raw_supporting_text": {
        "material": [], "activity": [], "kinetics": [], "application": [],
    },
    "diagnostics": {
        "status": "failed", "confidence": "low", "needs_review": True, "warnings": [],
    },
}

_SCHEMA_TOP_KEYS = frozenset(EMPTY_RECORD.keys())
_KINETICS_KEYS = frozenset(EMPTY_RECORD["main_activity"]["kinetics"].keys())
_CONDITIONS_KEYS = frozenset(EMPTY_RECORD["main_activity"]["conditions"].keys())
_PH_PROFILE_KEYS = frozenset(EMPTY_RECORD["main_activity"]["pH_profile"].keys())
_TEMP_PROFILE_KEYS = frozenset(EMPTY_RECORD["main_activity"]["temperature_profile"].keys())
_SYNTHESIS_COND_KEYS = frozenset(EMPTY_RECORD["selected_nanozyme"]["synthesis_conditions"].keys())
_RST_KEYS = frozenset(EMPTY_RECORD["raw_supporting_text"].keys())
_VALID_STATUSES = frozenset({"complete", "partial", "failed"})
_VALID_CONFIDENCES = frozenset({"high", "medium", "low"})

_GENERIC_PHRASES = frozenset({
    "system", "surface", "catalyst", "mg/ml", "nanomaterials", "nanozymes",
    "on the surface", "because", "the surface", "material", "composite",
    "nanoparticle", "nanoparticles", "nanomaterial", "the catalyst",
    "the system", "catalytic system", "the material", "the nanozyme",
    "nanocomposite", "hybrid material", "the composite", "method",
    "substrate", "product", "reaction", "solution", "sample", "buffer",
    "experiment", "result", "data", "figure", "table", "scheme",
    "pv", "pe", "pp", "pes", "pva", "peg", "pla", "pga",
    "s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10",
    "ppis", "api", "gsh", "ros", "rns", "h2o2", "oh",
    "a/ablank", "a/a", "blank",
    "nanocluster", "nanoclusters", "nanodot", "nanodots",
    "nanosheet", "nanosheets", "nanorod", "nanorods",
    "nanowire", "nanowires", "nanotube", "nanotubes",
    "nanofiber", "nanofibers", "nanoflower", "nanoflowers",
    "nanosphere", "nanospheres", "nanocage", "nanocages",
    "nanocube", "nanocubes", "nanostar", "nanostars",
    "nanoprism", "nanoprisms", "nanoring", "nanorings",
    "nanobelt", "nanobelts", "nanoplate", "nanoplates",
    "nanocapsule", "nanocapsules", "nanovehicle", "nanovehicles",
    "nanocontainer", "nanocontainers", "nanoreactor", "nanoreactors",
    "core-shell", "core@shell", "yolk-shell", "yolk@shell",
    "hollow sphere", "hollow spheres", "mesoporous",
    "the probe", "the sensor", "the biosensor", "the platform",
    "the assay", "the method", "the approach", "the strategy",
    "the product", "the precursor", "the reactant",
    "catalyst system", "enzyme mimic", "artificial enzyme",
    "mimic enzyme", "enzyme model",
})

_SHORT_GENERIC_RE = re.compile(r'^[A-Z]{1,3}\d{0,2}$')

_TECHNIQUE_ABBREVIATIONS = frozenset({
    "SERS", "HAADFSTEM", "HAADF", "STEM", "TEM", "SEM", "XRD", "XPS",
    "Raman", "FTIR", "EPR", "AFM", "EDX", "EDS", "SAED", "BET",
    "UV", "IR", "NMR", "ESI", "LSPR", "CT", "EM", "EF",
    "HRTEM", "BF-STEM", "HAADF-STEM", "FDTD", "CV", "ICP",
    "TGA", "DLS", "XAFS", "XANES", "EXAFS", "DSC", "DTA",
    "TG", "PL", "CL", "EL", "FL", "UV-vis", "XRD", "SAXS",
    "WAXS", "GISAXS", "MOSS", "MBS", "EELS", "CL", "EBSD",
    "SAD", "SAED", "FFT", "IFFT", "FIB", "SEM", "FESEM",
    "FETEM", "CTEM", "STEM", "ADF", "ABF", "HAADF",
    "BF", "DF", "DFSTEM", "HAADFSTEM", "HAADF-STEM",
    "ICP-MS", "ICP-OES", "GC-MS", "LC-MS", "HPLC",
    "GPC", "SEC", "DLS", "Zeta", "BET", "BJH",
    "RSD", "SD", "SEM", "NADH", "NADPH",
})

_SUBSTRATE_NAMES = frozenset({
    "H2O2", "TMB", "ABTS", "OPD", "DCFH", "DCFH-DA",
    "guaiacol", "pyrogallol", "catechol", "AR",
    "TMB-H2O2", "ABTS-H2O2", "OPD-H2O2",
    "DAPI", "Amplex Red", "Resorufin", "DHR123", "DHE",
    "L-012", "Luminol", "Isoluminol",
    "NADH", "NADPH", "NAD+", "NADP+",
    "4-AAP", "4-Aminoantipyrine", "Phenol",
    "o-phenylenediamine", "p-phenylenediamine",
    "3,3'-diaminobenzidine", "DAB",
    "o-tolidine", "Leucomalachite green",
    "Terephthalic acid", "TA", "PTA",
    "Coumarin", "HPF", "SOSG", "DPBF",
    "NBT", "Nitroblue tetrazolium",
    "XTT", "MTT", "WST-1", "WST-8",
    "BCIP", "NPP", "pNPP", "p-Nitrophenyl phosphate",
    "ONPG", "o-Nitrophenyl-β-D-galactopyranoside",
    "MU-Glc", "4-MU", "4-Methylumbelliferyl",
    "pNA", "BAPNA", "SAAPFpNA",
    "Ferrocyanide", "Ferricyanide",
    "L-DOPA", "L-tyrosine", "Epinephrine",
    "Tyr", "DOPA",
    "Pyrogallol", "Gallic acid", "Syringaldazine",
    "Veratryl alcohol", "ABTS radical", "ABTS+",
    "Ruthenium complex", "Ru(bpy)3",
    "Methylene blue", "Rhodamine B", "Rhodamine 6G",
    "Crystal violet", "Malachite green",
    "Indigo carmine", "Congo red", "Methyl orange",
    "Methyl red", "Phenol red",
    "Bromophenol blue", "Bromocresol green",
    "Thymol blue", "Bromothymol blue",
})

_SMALL_MOLECULE_NAMES = frozenset({
    "O2", "H2O", "CO2", "CO", "NO", "NO2", "N2", "NH3",
    "H2", "CH4", "C2H2", "OH", "H2S", "SO2", "SO3",
    "Cl2", "ClO2", "HCl", "HNO3", "H2SO4",
})

_DISEASE_NAMES = frozenset({
    "SARS", "COVID", "HIV", "AIDS", "MERS", "EBOLA",
    "ZIKA", "DENGUE", "MALARIA", "TUBERCULOSIS",
    "DIABETES", "CANCER", "ALZHEIMER", "PARKINSON",
})

_NON_MATERIAL_PHRASES = frozenset({
    "single atom from metal nanoparticles",
    "single atom nanozyme",
    "single-atom nanozyme",
    "single atom catalyst",
    "single-atom catalyst",
    "nanozyme",
    "nanozymes",
    "enzyme mimic",
    "enzyme-mimicking",
    "artificial enzyme",
    "sazs", "sae", "sanes", "sanzs",
    "in our system", "our system", "the system",
    "this work", "the present work",
    "as-prepared", "as-synthesized", "as-prepared nanozyme",
    "the as-prepared", "the as-synthesized",
    "proposed nanozyme", "proposed catalyst",
    "newly developed", "newly synthesized", "newly prepared",
    "the catalyst", "the nanozyme", "the material",
    "our nanozyme", "our catalyst", "our material",
    "the present study", "this study", "present work",
    "the synthesized", "the prepared",
    "bare", "pristine", "pure",
    "free enzyme", "natural enzyme", "native enzyme",
    "commercial enzyme", "free HRP",
    "abstract", "introduction", "results", "discussion",
    "conclusion", "methods", "experimental", "supplementary",
    "supporting information", "references", "acknowledgments",
})

_RATIO_PATTERN = re.compile(r'^[A-Za-z]/[A-Za-z]', re.I)

_REAGENT_NAMES = frozenset({
    "NaAc", "NaCl", "KCl", "NaOH", "HCl", "H2SO4", "HNO3",
    "PBS", "Tris", "HEPES", "MES", "MOPS", "CH3COOH",
    "Na2HPO4", "NaH2PO4", "EDTA", "SDS", "CTAB",
    "DMF", "DMSO", "THF", "EtOH", "CH3OH",
    "Na2CO3", "NaHCO3", "CaCl2", "MgCl2",
    "Na2SO4", "NaNO3", "KNO3", "NH4Cl",
    "K2Cr2O7", "KMnO4", "K3Fe(CN)6", "K4Fe(CN)6",
    "Na2S2O3", "Na2S2O8", "K2S2O8", "(NH4)2S2O8",
    "NaBH4", "KBH4", "LiAlH4", "Na2WO4",
    "FeCl3", "FeCl2", "FeSO4", "Fe(NO3)3",
    "CuSO4", "CuCl2", "Cu(NO3)2",
    "CoCl2", "Co(NO3)2", "NiCl2", "Ni(NO3)2",
    "ZnCl2", "Zn(NO3)2", "ZnSO4",
    "MnCl2", "MnSO4", "Mn(OAc)2",
    "Ce(NO3)3", "CeCl3", "Ce(SO4)2",
    "HAuCl4", "AgNO3", "H2PtCl6", "PdCl2",
    "TiCl4", "Ti(OBu)4", "ZrOCl2", "ZrCl4",
    "AlCl3", "SnCl2", "SnCl4", "Bi(NO3)3",
    "La(NO3)3", "Cr(NO3)3", "CrCl3",
    "HRP", "GOx", "SOD", "CAT",
    "AChE", "ChOx", "LOx", "UOx", "GalOx", "AOx", "XOD", "Xanthine oxidase",
    "Acetylcholinesterase", "Choline oxidase", "Lactate oxidase", "Uricase",
    "Glucose oxidase", "Alcohol oxidase", "Catalase", "Peroxidase",
    "Horseradish peroxidase", "Superoxide dismutase", "Glutathione peroxidase",
    "ALP", "Lac", "Laccase", "ALPase", "Alkaline phosphatase",
    "NADH", "NAD+", "NADPH", "NADP+",
    "HUVEC", "HeLa", "HEK293", "MCF-7", "4T1", "RAW264.7", "RAW 264.7",
    "HepG2", "A549", "MRC-5", "NIH3T3", "L929", "COS-7",
    "RPMI", "RPMI-1640", "RPMI 1640", "DMEM", "FBS",
    "BSA", "HSA", "PVP", "PVA", "PEG", "PEO",
    "Triton", "Tween-20", "Tween-80", "Triton X-100",
    "CH3CN", "Acetonitrile", "Ethanol", "Methanol", "Isopropanol",
    "E coli", "E. coli", "S aureus", "S. aureus",
    "TEA", "Triethylamine", "DIPEA", "Pyridine",
    "TEOS", "APTES", "MTMS", "CTAB",
    "Oleic acid", "Oleylamine", "1-Octadecene",
    "Ethylene glycol", "Glycerol", "Propylene glycol",
    "Sodium citrate", "Citrate", "Urea", "Thiourea",
    "Dopamine hydrochloride", "Melamine", "Cyanuric acid",
    "Glucose", "Fructose", "Sucrose", "Maltose",
    "Starch", "Cellulose", "Chitosan", "Alginate",
    "Pectin", "Gelatin", "Collagen", "Agarose",
    "PAA", "PMAA", "PSS", "PDDA", "PEI",
    "PF127", "F127", "P123", "CTAB",
    "SDBS", "SDS", "Tween", "Span",
})

_SUBSTRATE_PLUS_RE = re.compile(
    r'^(?:' + '|'.join(re.escape(s) for s in _SUBSTRATE_NAMES) + r')\s+(?:system|solution|mixture|assay|reaction)$',
    re.I,
)

_SENTENCE_ID_RE = re.compile(r'^[A-Z]\d{3,}(?:/[A-Z]\d{3,})*$', re.I)

_LEADING_JUNK_RE = re.compile(
    r'^(?:of\s+|the\s+|a\s+|an\s+|uniform\s+dispersion\s+of\s+|'
    r'formation\s+of\s+(?:the\s+)?|synthesis\s+of\s+(?:the\s+)?|'
    r'presence\s+of\s+|activity\s+of\s+|construction\s+of\s+|'
    r'where\s+|able\s+to\s+transform\s+|suggests\s+that\s+(?:the\s+)?|'
    r'are\s+provided\s+by\s+|oxidasemimicking\s+activity\s+of\s+|'
    r'Twodimensional\s+|20-25\s+Twodimensional\s+|'
    r'while\s+the\s+proposed\s+|that\s+(?:magnetic\s+)?|'
    r'catalyst\s+|proposed\s+|novel\s+|new\s+|'
    r'morphology\s+of\s+(?:the\s+)?|structure\s+of\s+(?:the\s+)?|'
    r'synthesis\s+and\s+characterization\s+of\s+|'
    r'process\s+of\s+(?:the\s+)?|'
    r'single\s+atom\s+(?:from\s+)?|'
    r'the\s+proposed\s+|'
    r'as\s+(?:a\s+)?(?:peroxidase|oxidase|catalase|nanozyme)[-\s]?like\s+\w+\s+)',
    re.I,
)

_NON_MATERIAL_TAIL_RE = re.compile(
    r'\s+(?:system|nanosheets|nanoparticles|nanotubes|nanofibers|'
    r'nanorods|nanospheres|nanoclusters|nanodots|nanoflowers|'
    r'nanocubes|nanowires|nanobelts|nanoplates)$',
    re.I,
)

_MORPHOLOGY_WORDS = frozenset({
    "nanoparticle", "nanoparticles", "nanosheet", "nanosheets",
    "nanotube", "nanotubes", "nanorod", "nanorods", "nanowire", "nanowires",
    "nanocluster", "nanoclusters", "nanosphere", "nanospheres",
    "nanocube", "nanocubes", "nanoflower", "nanoflowers",
    "nanofiber", "nanofibers", "nanodot", "nanodots",
    "core-shell", "yolk-shell", "hollow", "mesoporous", "porous",
    "layered", "sandwich", "dendritic", "urchin-like", "spindle",
    "prism", "octahedral", "cubic", "spherical", "rod-like",
    "sheet-like", "belt-like", "plate-like",
})

_MATERIAL_PATTERN_RE = re.compile(
    r"(?:\b(?:MIL|UiO|HKUST|PCN|NU|NOTT|DUT|MOF|COF|ZIF)[-\s]?\d+(?:\([A-Z][a-z]?(?:[A-Z][a-z]?\d*)*\))?(?=\s|$|[^A-Za-z0-9(-]))"
    r"|(?:\b[A-Z][a-z]?\d*(?:[A-Z][a-z]?\d*)+\b)"
    r"|(?:\b[A-Z][a-z]?O\d*\b)"
    r"|(?:\b(?:Fe|Co|Ni|Mn|Cu|Zn|Ce|Au|Ag|Pt|Pd|Ti|V|Cr|Mo|W|Ru|Rh|Ir|"
    r"La|Pr|Nd|Sm|Eu|Gd|Tb|Dy|Ho|Er|Tm|Yb|Lu|Zr|Al|Sn|Bi|In|Ga|Ge|Sb|Te|Hf|Ta|Re|Os|Y|Sc|Cd|Hg|Tl|Pb|Nb)\d*(?:O\d*)?"
    r"(?:[A-Z][a-z]?\d*(?:O\d*)?)*"
    r"(?:@|[-/])?"
    r"(?:[A-Z][a-z]?\d*(?:O\d*)?)*\b)"
    r"|(?:\b[A-Z][a-z]?\d*(?:@[A-Z][a-z]?\d*)?\b)"
    r"|(?:\bMOF[-\s]?\d+\b)"
    r"|(?:\bCOF[-\s]?\d+\b)"
    r"|(?:\bZIF[-\s]?\d+\b)",
)

_COMPOSITE_PATTERN_RE = re.compile(
    r"(?:\b[A-Z][a-z]?\d*(?:O\d*)?(?:[A-Z][a-z]?\d*(?:O\d*)?)*(?:@|/)\s*[A-Z][a-z]?\d*(?:O\d*)?(?:[A-Z][a-z]?\d*(?:O\d*)?)*\b)"
    r"|(?:\b[A-Z][a-z]?\d*(?:O\d*)?\s*(?:@|/)\s*[A-Z][a-z]?\d*(?:O\d*)?\b)",
)

_METAL_ELEMENTS_RE = re.compile(
    r'\b(?:Fe|Co|Ni|Mn|Cu|Zn|Ce|Au|Ag|Pt|Pd|Ti|V|Cr|Mo|W|Ru|Rh|Ir|La|Pr|Nd|Sm|Eu|Gd|Tb|Dy|Ho|Er|Tm|Yb|Lu|Zr|Al|Sn|Bi|In|Ga|Ge|Sb|Te|Hf|Ta|Re|Os|Y|Sc|Cd|Hg|Tl|Pb|Nb)\d*'
)

_SECTION_SCORE_MAP = {
    "title": 8, "abstract": 6, "synthesis": 8,
    "characterization": 5, "characterization_caption": 5,
    "activity": 8, "kinetics": 8, "application": 5, "conclusion": 4,
    "hints_system": 3, "hints_enzyme": 2, "unknown": 0,
    "introduction": -8, "comparison_table": -12, "references": -12,
}
_GENERIC_PENALTY = -20

_ENZYME_TYPE_PATTERNS = [
    (re.compile(r'\bglutathione\s+peroxidase[-\s]?like\b', re.I), "glutathione-peroxidase-like"),
    (re.compile(r'\bglutathione\s+oxidase[-\s]?like\b', re.I), "glutathione-oxidase-like"),
    (re.compile(r'\bglucose\s+oxidase[-\s]?like\b', re.I), "glucose-oxidase-like"),
    (re.compile(r'\bNADH\s+oxidase[-\s]?like\b', re.I), "NADH-oxidase-like"),
    (re.compile(r'\bsuperoxide\s+dismutase[-\s]?like\b', re.I), "superoxide-dismutase-like"),
    (re.compile(r'\bperoxidase[-\s]?like\b', re.I), "peroxidase-like"),
    (re.compile(r'\bPOD[-\s]?like\b', re.I), "peroxidase-like"),
    (re.compile(r'\boxidase[-\s]?like\b', re.I), "oxidase-like"),
    (re.compile(r'\bOXD[-\s]?like\b', re.I), "oxidase-like"),
    (re.compile(r'\bcatalase[-\s]?like\b', re.I), "catalase-like"),
    (re.compile(r'\bCAT[-\s]?like\b', re.I), "catalase-like"),
    (re.compile(r'\bSOD[-\s]?like\b', re.I), "superoxide-dismutase-like"),
    (re.compile(r'\bGPx[-\s]?like\b', re.I), "glutathione-peroxidase-like"),
    (re.compile(r'\bGOx[-\s]?like\b', re.I), "glucose-oxidase-like"),
    (re.compile(r'\besterase[-\s]?like\b', re.I), "esterase-like"),
    (re.compile(r'\bphosphatase[-\s]?like\b', re.I), "phosphatase-like"),
    (re.compile(r'\bALP[-\s]?like\b', re.I), "phosphatase-like"),
    (re.compile(r'\bnitroreductase[-\s]?like\b', re.I), "nitroreductase-like"),
    (re.compile(r'\bNTR[-\s]?like\b', re.I), "nitroreductase-like"),
    (re.compile(r'\bhydrolase[-\s]?like\b', re.I), "hydrolase-like"),
    (re.compile(r'\blaccase[-\s]?like\b', re.I), "laccase-like"),
    (re.compile(r'\bhaloperoxidase[-\s]?like\b', re.I), "haloperoxidase-like"),
    (re.compile(r'\bcascade\s+enzym\w+\s+activ', re.I), "cascade-enzymatic"),
    (re.compile(r'\bmulti[-\s]?enzyme[-\s]?like\b', re.I), "multi-enzyme-like"),
    (re.compile(r'\bdual[-\s]?enzyme[-\s]?like\b', re.I), "multi-enzyme-like"),
    (re.compile(r'\btriple[-\s]?enzyme[-\s]?like\b', re.I), "multi-enzyme-like"),
    (re.compile(r'\bperoxidase\s+and\s+oxidase[-\s]?like\b', re.I), "multi-enzyme-like"),
    (re.compile(r'\bperoxidase[-\s]?oxidase[-\s]?like\b', re.I), "multi-enzyme-like"),
    (re.compile(r'\bPOD[-\s]?like\s+and\s+OXD[-\s]?like\b', re.I), "multi-enzyme-like"),
    (re.compile(r'\bcatalase\s+and\s+peroxidase[-\s]?like\b', re.I), "multi-enzyme-like"),
    (re.compile(r'\btyrosinase[-\s]?like\b', re.I), "tyrosinase-like"),
    (re.compile(r'\bribozyme[-\s]?like\b', re.I), "ribozyme-like"),
    (re.compile(r'\bcellulase[-\s]?like\b', re.I), "cellulase-like"),
    (re.compile(r'\bamylase[-\s]?like\b', re.I), "amylase-like"),
    (re.compile(r'\bprotease[-\s]?like\b', re.I), "protease-like"),
    (re.compile(r'\blipase[-\s]?like\b', re.I), "lipase-like"),
    (re.compile(r'\burease[-\s]?like\b', re.I), "urease-like"),
    (re.compile(r'\bascorbate\s+oxidase[-\s]?like\b', re.I), "ascorbate-oxidase-like"),
    (re.compile(r'\bAAO[-\s]?like\b', re.I), "ascorbate-oxidase-like"),
    (re.compile(r'\bchloroperoxidase[-\s]?like\b', re.I), "haloperoxidase-like"),
    (re.compile(r'\bcytochrome\s+c\s+oxidase[-\s]?like\b', re.I), "oxidase-like"),
    (re.compile(r'\bformate\s+dehydrogenase[-\s]?like\b', re.I), "dehydrogenase-like"),
    (re.compile(r'\balcohol\s+dehydrogenase[-\s]?like\b', re.I), "dehydrogenase-like"),
    (re.compile(r'\bglucose\s+dehydrogenase[-\s]?like\b', re.I), "dehydrogenase-like"),
    (re.compile(r'\bDNAse[-\s]?like\b', re.I), "nuclease-like"),
    (re.compile(r'\bDNase[-\s]?like\b', re.I), "nuclease-like"),
    (re.compile(r'\bRNase[-\s]?like\b', re.I), "nuclease-like"),
    (re.compile(r'\binvertase[-\s]?like\b', re.I), "invertase-like"),
    (re.compile(r'\bchitinase[-\s]?like\b', re.I), "chitinase-like"),
    (re.compile(r'\bxylanase[-\s]?like\b', re.I), "xylanase-like"),
]

_SUBSTRATE_KEYWORDS = {
    "TMB", "ABTS", "OPD", "H2O2", "DCFH", "DCFH-DA",
    "guaiacol", "pyrogallol", "catechol",
    "DAP", "DAPI", "DAF-FM", "Amplex Red", "Resorufin",
    "NADH", "NADPH", "DHA", "L-DOPA", "dopamine",
    "4-AAP", "phenol", "4-aminoantipyrine",
    "Terephthalic acid", "TA", "HPF", "SOSG",
    "DHE", "dihydroethidium", "NBT", "nitroblue tetrazolium",
    "X-Gal", "BCIP", "o-nitrophenyl", "ONPG", "p-nitrophenyl", "pNPP",
    "DTNB", "Ellman", "GSH", "glutathione",
    "ferrocyanide", "ferricyanide", "K4Fe(CN)6", "K3Fe(CN)6",
    "methanol", "ethanol", "formaldehyde",
    "glucose", "cholesterol", "uric acid", "lactate",
    "ascorbic acid", "cysteine", "bilirubin",
    "acetylcholine", "choline", "xanthine", "hypoxanthine",
    "urea", "hydroquinone", "benzoquinone",
}

_KM_PATTERNS = [
    re.compile(r'\bKm\s*[\(（]\s*(\w[\w\d\-]*)\s*[\)）]\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*)?(mM|μM|uM|M|mmol|umol|nmol|mmol/L|umol/L|nmol/L)', re.I),
    re.compile(r'\bKm\s+for\s+(\w[\w\d\-]*)\s+(?:\w+\s+){0,2}(?:was|=|:|≈|~)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*)?(mM|μM|uM|M|mmol|umol|nmol|mmol/L|umol/L|nmol/L)', re.I),
    re.compile(r'\bapparent\s+Km\s+(?:\w+\s+){0,2}(?:was|=|:|≈|~)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*)?(mM|μM|uM|M|mmol|umol|nmol|mmol/L|umol/L|nmol/L)', re.I),
    re.compile(r'\bKm\s+value\s+(?:toward|for|of)\s+(\w[\w\d\-]*)\s+.*?(?:was|is|=|:|≈|~|calculated\s+to\s+be)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*)?(mM|μM|uM|M|mmol|umol|nmol|mmol/L|umol/L|nmol/L)', re.I),
    re.compile(r'\bKm\s*[\(（]\s*(mM|μM|uM|M|mmol|umol|nmol|mmol/L|umol/L|nmol/L)\s*[\)）]\s+([\d.]+)', re.I),
    re.compile(r'\bKm\s*(?:was|is|=|:|≈|~|determined\s+to\s+be|found\s+to\s+be)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*)?(mM|μM|uM|M|mmol|umol|nmol|mmol/L|umol/L|nmol/L)', re.I),
    re.compile(r'\bKm\s+value\s+(?:was|is|=|:|≈|~)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*)?(mM|μM|uM|M|mmol|umol|nmol|mmol/L|umol/L|nmol/L)', re.I),
    re.compile(r'\bKm\s+of\s+(\w[\w\d\-]*)\s+(?:was|is|=|:|≈|~)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*)?(mM|μM|uM|M|mmol|umol|nmol|mmol/L|umol/L|nmol/L)', re.I),
    re.compile(r'\bKm\s+of\s+([\d.]+)\s*(mM|μM|uM|M|mmol|umol|nmol|mmol/L|umol/L|nmol/L)', re.I),
    re.compile(r'\bKm\s*[\(（]\s*(\w[\w\d\-]*)\s*[\)）]\s*=\s*([\d.]+)\s*[×x]\s*10[\^⁻\-–]?\s*[-]?(\d+)\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\s*=\s*([\d.]+)\s*[×x]\s*10[\^⁻\-–]?\s*[-]?(\d+)\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\s*=\s*([\d.]+[eE][\-−]?\d+)\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bMichaelis\s+constant\s*(?:for\s+)?(\w[\w\d\-]*)?\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*(mM|μM|uM|M|mmol/L)', re.I),
    re.compile(r'\bMichaelis[\s-]*Menten\s+constant\s*\)?\s*[^.]{0,60}?(?:was\s+)?(?:calculated\s+to\s+be|found\s+to\s+be)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*|\s+[\d.]+\s+)?(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\s*\)?\s*[^.]{0,60}?(?:was\s+)?(?:calculated\s+to\s+be|found\s+to\s+be|determined\s+to\s+be)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*|\s+[\d.]+\s+)?(mM|μM|uM|M|mmol/L)', re.I),
    re.compile(r'\bKm\s+(?:values?\s+)?(?:to|toward|for)\s+(\S+)\s+(?:and|&)\s+\S+\s+(?:are|were|is|was)\s*([\d.]+)\s+(?:and|&)\s*[\d.]+\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\s+(?:was|is|were|are)\s*(?:calculated\s+(?:to\s+be|as)\s+)?(?:approximately\s+)?([\d.]+)\s*(?:±\s*[\d.]+\s*)?(mM|μM|uM|M|mmol/L)', re.I),
    re.compile(r'\bKm\b[^.]{0,40}?\(([\d.]+)\s*(mM|μM|uM|M)\)', re.I),
    re.compile(r'\bKm\s*(?:of|for)\s+\S+\s+(?:toward|to)\s+\w[\w\d\-]*\s+(?:was|is|=|:)\s*([\d.]+)\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\s+values?\s+(?:of|for)\s+\S+\s+(?:for\s+)?(?:and|&)?\s*\S*\s+(?:are|were|is|was)\s*([\d.]+)\s*(?:and|&|,)\s*[\d.]+\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\s+values?\s+of\s+([\d.]+)\s*(mM|μM|uM|M)\s+(?:and|&|,)\s*[\d.]+\s*(?:mM|μM|uM|M)?', re.I),
    re.compile(r'\bKm\b\s*\)?\s*(?:were|was|are|is)\s*([\d.]+)\s*(?:and|&|,)\s*[\d.]+\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\b[^.]{0,30}?\bare\s*([\d.]+)\s*(?:and|&)\s*[\d.]+\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\s+values?\s+of\s+[^.]{0,80}?\b(?:are|were|is|was)\s+([\d.]+)\s*(?:and|&|,)\s*[\d.]+\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\s+values?\s+of\s+\S+\s+(?:and|&)\s+\S+\s+(?:are|were)\s+([\d.]+)\s+(?:and|&|,)\s*[\d.]+\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\s+(?:toward|to)\s+(\w[\w\d\-]*)\s+(?:was|is|=|:|≈|~)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*)?(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\b[^.]{0,50}?([\d.]+)\s*(mM|μM|uM|M|mmol/L|umol/L)', re.I),
    re.compile(r'\bKm\b\s*[^.\d]{0,20}?([\d.]+)\s*[×x\u00d7]\s*10[\u207b\u2212\u2013\-](\d+)\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bMichaelis[^.]{0,30}?constant\b[^.]{0,50}?([\d.]+)\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\b[^.]{0,15}?determined\b[^.]{0,30}?([\d.]+)\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\b[^.]{0,40}?([\d.]+)\s*[eE][\-−]?\d+\s*(mM|μM|uM|M)', re.I),
]

_KM_VMAX_JOINT_PATTERNS = [
    re.compile(r'\bKm\b.*?\bV\s*max\b.*?(?:were|was|calculated|found)\s+(?:to\s+be\s+)?([\d.]+)\s*(mM|μM|uM|M)\s+(?:and|,)\s+([\d.]+(?:[eE][\-−\u2212]?\d+)?(?:\s*[×x]\s*10[\^⁻\-–]?\s*[-]?\d+)?)\s*(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s|M\s+s-1)', re.I),
    re.compile(r'\bKm\s*=\s*([\d.]+)\s*(mM|μM|uM|M)\s*,?\s*V\s*max\s*=\s*([\d.]+(?:[eE][\-−\u2212]?\d+)?(?:\s*[×x]\s*10[\^⁻\-–]?\s*[-]?\d+)?)\s*(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s|M\s+s-1)', re.I),
    re.compile(r'\bKm\s*=\s*([\d.]+)\s*(mM|μM|uM|M)\s*[,;]\s*V\s*max\s*=\s*([\d.]+)\s*10\s*[\^⁻\-–]?\s*[-]?\s*(\d+)\s*(?:M\s*[sS]|mM\s*[sS])', re.I),
    re.compile(r'\bKm\b[^.]{0,20}?([\d.]+)\s*(mM|μM|uM|M)\s*[,;]\s*V\s*max\b[^.]{0,20}?([\d.]+)\s*10\s*[\^⁻\-–]?\s*[-]?\s*(\d+)\s*(?:M\s*[sS]|mM\s*[sS])', re.I),
    re.compile(r'\bKm\b[^.]{0,30}?([\d.]+)\s*(mM|μM|uM|M)\s+.*?\bV\s*max\b\s*=\s*([\d.]+(?:[eE][\-−\u2212]?\d+)?(?:\s*[×x\u00d7]\s*10[\^⁻\-–]?\s*[-]?\d+)?)\s*(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s|M\s+s-1)', re.I),
    re.compile(r'\bKm\b[^.]{0,30}?([\d.]+)\s*(mM|μM|uM|M)\s+.*?\bV\s*max\b[^.]{0,10}?([\d.]+(?:[eE][\-−\u2212]?\d+)?(?:\s*[×x\u00d7]\s*10[\^⁻\-–]?\s*[-]?\d+)?)\s*(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s|M\s+s-1)', re.I),
    re.compile(r'\bV\s*max\s*=\s*([\d.]+(?:[eE][\-−\u2212]?\d+)?(?:\s*[×x]\s*10[\^⁻\-–]?\s*[-]?\d+)?)\s*(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s|M\s+s-1)\s*[,;]\s*Km\s*=\s*([\d.]+)\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\b\s+(?:and|&)\s+V\s*max\b\s+(?:were|was|are|is)\s+(?:calculated|found|determined)?\s*(?:to\s+be\s+)?([\d.]+)\s*(mM|μM|uM|M|mmol)\s+(?:and|,)\s+([\d.]+[eE][\-−\u2212]?\d+)\s*(M\s*[sS][\-\u207b\u2212\u2013]?1|M/?s|mM/?s|μM/?s|M\s+s-1)', re.I),
    re.compile(r'\bKm\b\s+(?:and|&)\s+V\s*max\b\s+(?:were|was|are|is)\s+(?:calculated|found|determined)?\s*(?:to\s+be\s+)?([\d.]+)\s*(mM|μM|uM|M|mmol)\s+(?:and|,)\s+([\d.]+)\s*[×x\u00d7]\s*10[\^⁻\-\u207b\u2212\u2013]?\s*([\d]+)\s*(M\s*[sS][\-\u207b\u2212\u2013]?1|M/?s|mM/?s|μM/?s|M\s+s-1)', re.I),
    re.compile(r'\bV\s*max\b.*?\bKm\b.*?(?:can\s+be\s+)?(?:calculated|found|determined)\s+(?:to\s+be\s+|as\s+)?([\d.]+(?:[eE][\-−\u2212]?\d+)?)\s*(mM|μM|uM|M)\s+(?:and|,)\s+([\d.]+(?:[eE][\-−\u2212]?\d+)?)\s*(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s|M\s+s-1|s\u207b\u00b9)', re.I),
    re.compile(r'\bV\s*max\b[^.]{0,30}?\bKm\b[^.]{0,30}?(?:calculated|found|was)\s+(?:to\s+be\s+|as\s+)?([\d.]+(?:[eE][\-−\u2212]?\d+)?)\s*(mM|μM|uM|M)\s+(?:and|,)\s+([\d.]+(?:[eE][\-−\u2212]?\d+)?)\s*(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s|M\s+s-1|s\u207b\u00b9)', re.I),
]

_KCAT_PATTERNS = [
    re.compile(r'\bkcat\s*[\(（]\s*(\w[\w\d\-]*)\s*[\)）]\s*(?:was|=|:|≈|~)\s*([\d.]+(?:\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-|\^)?\s*[-]?\d+)?)\s*(s\^-1|s(?:\u207b|\u2212|\u2013|-)?1|s-1|min\^-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bkcat(?!\s*/\s*Km)\s+(?:for\s+)?(\w[\w\d\-]*)?\s*(?:was|=|:|≈|~)\s*([\d.]+(?:\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-|\^)?\s*[-]?\d+)?)\s*(s\^-1|s(?:\u207b|\u2212|\u2013|-)?1|s-1|min\^-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bkcat(?!\s*/\s*Km)\s*(?:was|=|:|≈|~)\s*([\d.]+(?:\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-|\^)?\s*[-]?\d+)?)\s*(s\^-1|s(?:\u207b|\u2212|\u2013|-)?1|s-1|min\^-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bturnover\s+(?:number|frequency)\s*(?:was|=|:|≈|~)\s*([\d.]+(?:\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-|\^)?\s*[-]?\d+)?)\s*(s\^-1|s(?:\u207b|\u2212|\u2013|-)?1|s-1|min\^-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bkcat(?!\s*/\s*Km)\s*(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)\s*(s\^-1|s(?:\u207b|\u2212|\u2013|-)?1|s-1|min\^-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bkcat(?!\s*/\s*Km)\b[^.=]{0,20}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*[×x\u00d7]?\s*10(?:\u207b|\u2212|\u2013|-|\^)\s*(\d+)\s*(s\^-1|s(?:\u207b|\u2212|\u2013|-)?1|s-1|min\^-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bcatalytic\s+(?:rate\s+)?constant\s*(?:was|=|:|≈|~|\u2248)\s*([\d.]+(?:\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-|\^)?\s*[-]?\d+)?)\s*(s\^-1|s(?:\u207b|\u2212|\u2013|-)?1|s-1|min\^-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bkcat\s*=\s*([\d.]+)\s*(s\^-1|s(?:\u207b|\u2212|\u2013|-)?1|s-1|min\^-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bkcat(?!\s*/\s*Km)\b[^.=]{0,30}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+(?:\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-|\^)?\s*[-]?\d+)?)\s*(s\^-1|s(?:\u207b|\u2212|\u2013|-)?1|s-1|min\^-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bkcat(?!\s*/\s*Km)\b[^.=]{0,15}?([\d.]+)\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-|\^)\s*(\d+)\s*(s\^-1|s(?:\u207b|\u2212|\u2013|-)?1|s-1|min\^-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bkcat(?!\s*/\s*Km)\b[^.=]{0,15}?([\d.]+)\s*[eE][\-−\u2212]?(\d+)\s*(s\^-1|s(?:\u207b|\u2212|\u2013|-)?1|s-1|min\^-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bKcat(?!\s*/\s*Km)\b[^.=]{0,20}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+(?:\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-|\^)?\s*[-]?\d+)?)\s*(s\^-1|s(?:\u207b|\u2212|\u2013|-)?1|s-1|min\^-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bkcat\s*[\(（]\s*(\w[\w\d\-]*)\s*[\)）]\s*=\s*([\d.]+)\s*(s\^-1|s(?:\u207b|\u2212|\u2013|-)?1|s-1|min\^-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bkcat\b[^.=]{0,40}?([\d.]+)\s*[×x\u00d7]\s*10[\u207b\u2212\u2013\-]?\s*(\d+)\s*(s[\u207b\u2212\u2013\-]?1|s-1|min[\u207b\u2212\u2013\-]?1)', re.I),
    re.compile(r'\bturnover\s+frequency\b[^.=]{0,30}?(?:was|=|:|≈|~)\s*([\d.]+)\s*[×x\u00d7]?\s*10[\u207b\u2212\u2013\-]?\s*(\d+)?\s*(s[\u207b\u2212\u2013\-]?1|s-1)', re.I),
    re.compile(r'\bcatalytic\s+rate\b[^.=]{0,30}?(?:was|=|:|≈|~)\s*([\d.]+)\s*[×x\u00d7]?\s*10[\u207b\u2212\u2013\-]?\s*(\d+)?\s*(s[\u207b\u2212\u2013\-]?1|s-1)', re.I),
    re.compile(r'\bkcat\b[^.=]{0,20}?([\d.]+)\s*s\u207b\u00b9', re.I),
    re.compile(r'\bKcat\b[^.]{0,50}?([\d.]+)\s*(s[\u207b\u2212\u2013\-]?1|s-1)', re.I),
    re.compile(r'\bturnover\s+(?:number|frequency)\b[^.]{0,50}?([\d.]+)\s*(s[\u207b\u2212\u2013\-]?1|s-1|min[\u207b\u2212\u2013\-]?1)', re.I),
]

_KCAT_KM_PATTERNS = [
    re.compile(r'\bkcat/Km\s*[\(（]\s*(\w[\w\d\-]*)\s*[\)）]\s*(?:was|=|:|≈|~)\s*([\d.]+(?:\s*[×x]\s*10[\^⁻\-–]?\s*[-]?\d+)?)\s*(M[\^⁻\-–]?1\s*s[\^⁻\-–]?1|mM[\^⁻\-–]?1\s*s[\^⁻\-–]?1|μM[\^⁻\-–]?1\s*s[\^⁻\-–]?1)', re.I),
    re.compile(r'\bkcat/Km\s+(?:for\s+)?(\w[\w\d\-]*)?\s*(?:was|=|:|≈|~)\s*([\d.]+(?:\s*[×x]\s*10[\^⁻\-–]?\s*[-]?\d+)?)\s*(M[\^⁻\-–]?1\s*s[\^⁻\-–]?1|mM[\^⁻\-–]?1\s*s[\^⁻\-–]?1|μM[\^⁻\-–]?1\s*s[\^⁻\-–]?1)', re.I),
    re.compile(r'\bspecificity\s+constant\s*(?:for\s+)?(\w[\w\d\-]*)?\s*(?:was|=|:|≈|~)\s*([\d.]+(?:\s*[×x]\s*10[\^⁻\-–]?\s*[-]?\d+)?)\s*(M[\^⁻\-–]?1\s*s[\^⁻\-–]?1|mM[\^⁻\-–]?1\s*s[\^⁻\-–]?1|μM[\^⁻\-–]?1\s*s[\^⁻\-–]?1)', re.I),
    re.compile(r'\bcatalytic\s+efficiency\s*(?:for\s+)?(\w[\w\d\-]*)?\s*(?:was|=|:|≈|~)\s*([\d.]+(?:\s*[×x]\s*10[\^⁻\-–]?\s*[-]?\d+)?)\s*(M[\^⁻\-–]?1\s*s[\^⁻\-–]?1|mM[\^⁻\-–]?1\s*s[\^⁻\-–]?1|μM[\^⁻\-–]?1\s*s[\^⁻\-–]?1)', re.I),
    re.compile(r'\bkcat/Km\s*(?:was|=|:|≈|~|\u2248)\s*([\d.]+(?:\s*[×x\u00d7]\s*10[\u207b⁻\-–\u2212\u2013]?\s*[-]?\d+)?)\s*(M[\u207b⁻\-–\u2212\u2013]?1\s*[·\u00b7]?\s*s[\u207b⁻\-–\u2212\u2013]?1|M\s*/?\s*s[\u207b⁻\-–\u2212\u2013]?1|M[\^⁻\-–]?1\s*s[\^⁻\-–]?1|mM[\u207b⁻\-–\u2212\u2013]?1\s*[·\u00b7]?\s*s[\u207b⁻\-–\u2212\u2013]?1|M\u207b\u00b9\s*s\u207b\u00b9)', re.I),
    re.compile(r'\bkcat/Km\s*[\(（]\s*(\w[\w\d\-]*)\s*[\)）]\s*=\s*([\d.]+(?:\s*[×x\u00d7]\s*10[\u207b⁻\-–\u2212\u2013]?\s*[-]?\d+)?)\s*(M[\u207b⁻\-–\u2212\u2013]?1\s*[·\u00b7]?\s*s[\u207b⁻\-–\u2212\u2013]?1|M\s*/?\s*s[\u207b⁻\-–\u2212\u2013]?1|M[\^⁻\-–]?1\s*s[\^⁻\-–]?1|M\u207b\u00b9\s*s\u207b\u00b9)', re.I),
    re.compile(r'\bkcat/Km\b[^.=]{0,20}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)\s*(M[\u207b⁻\-–\u2212\u2013]?1\s*[·\u00b7]?\s*s[\u207b⁻\-–\u2212\u2013]?1|M\s*/?\s*s[\u207b⁻\-–\u2212\u2013]?1)', re.I),
    re.compile(r'\bkcat/Km\b[^.=]{0,20}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*[×x\u00d7]\s*10[\u207b⁻\-–\u2212\u2013]\s*(\d+)\s*(M[\u207b⁻\-–\u2212\u2013]?1\s*[·\u00b7]?\s*s[\u207b⁻\-–\u2212\u2013]?1|M\s*/?\s*s[\u207b⁻\-–\u2212\u2013]?1)', re.I),
    re.compile(r'\bcatalytic\s+efficiency\s*(?:of\s+)?(\w[\w\d\-]*)?\s*(?:was|=|:|≈|~|\u2248)\s*([\d.]+(?:\s*[×x\u00d7]\s*10[\u207b⁻\-–\u2212\u2013]?\s*[-]?\d+)?)\s*(M[\u207b⁻\-–\u2212\u2013]?1\s*[·\u00b7]?\s*s[\u207b⁻\-–\u2212\u2013]?1|M\s*/?\s*s[\u207b⁻\-–\u2212\u2013]?1|M[\^⁻\-–]?1\s*s[\^⁻\-–]?1|M\u207b\u00b9\s*s\u207b\u00b9)', re.I),
    re.compile(r'\bspecificity\s+constant\s*(?:of\s+)?(\w[\w\d\-]*)?\s*(?:was|=|:|≈|~|\u2248)\s*([\d.]+(?:\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-)?\s*[-]?\d+)?)\s*(M(?:\u207b|\u2212|\u2013|-)?1\s*[·\u00b7]?\s*s(?:\u207b|\u2212|\u2013|-)?1|M\s*/?\s*s(?:\u207b|\u2212|\u2013|-)?1|M[\^\u207b\u2212\u2013\\-]?1\s*s[\^\u207b\u2212\u2013\\-]?1|M\u207b\u00b9\s*s\u207b\u00b9)', re.I),
    re.compile(r'\bkcat\s*/\s*Km\b[^.=]{0,15}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+(?:\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-)?\s*[-]?\d+)?)\s*(M(?:\u207b|\u2212|\u2013|-)?1\s*[·\u00b7]?\s*s(?:\u207b|\u2212|\u2013|-)?1|M\s*/?\s*s(?:\u207b|\u2212|\u2013|-)?1)', re.I),
    re.compile(r'\bkcat/Km\b[^.=]{0,40}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+(?:\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-)?\s*[-]?\d+)?)\s*(s(?:\u207b|\u2212|\u2013|-)?(?:\^?-)?1\s*[·\u00b7\s]?\s*(?:u|M|m|μ|n)M(?:\u207b|\u2212|\u2013|-)?(?:\^?-)?1|s-1\s*(?:u|M|m|μ|M)-1)', re.I),
    re.compile(r'\bkcat/Km\s*(?:of|for)\s+\S+\s+(?:was|=|:|≈|~|\u2248)\s*([\d.]+(?:\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-)?\s*[-]?\d+)?)\s*(s(?:\u207b|\u2212|\u2013|-)?(?:\^?-)?1\s*[·\u00b7\s]?\s*(?:u|M|m|μ|n)M(?:\u207b|\u2212|\u2013|-)?(?:\^?-)?1|M(?:\u207b|\u2212|\u2013|-)?1\s*[·\u00b7\s]?\s*s(?:\u207b|\u2212|\u2013|-)?1)', re.I),
    re.compile(r'\bcatalytic\s+efficiency\b[^.=]{0,40}?([\d.]+)\s*[×x\u00d7]\s*10[\u207b\u2212\u2013\-]?\s*(\d+)\s*(M[\u207b\u2212\u2013\-]?1\s*s[\u207b\u2212\u2013\-]?1|M/?s)', re.I),
    re.compile(r'\bspecificity\s+constant\b[^.=]{0,40}?([\d.]+)\s*[×x\u00d7]\s*10[\u207b\u2212\u2013\-]?\s*(\d+)\s*(M[\u207b\u2212\u2013\-]?1\s*s[\u207b\u2212\u2013\-]?1)', re.I),
    re.compile(r'\bkcat/Km\b[^.=]{0,30}?([\d.]+)\s*[eE][\-−]?\d+\s*(M[\u207b\u2212\u2013\-]?1\s*s[\u207b\u2212\u2013\-]?1)', re.I),
]

_RE_KM = re.compile(r'\bK\s+m\b', re.I)
_RE_VMAX = re.compile(r'\bV\s+max\b', re.I)
_RE_VM_NOAX = re.compile(r'\bV\s+m\b(?!\s*ax)', re.I)
_RE_KCAT = re.compile(r'\bk\s+cat\b', re.I)
_RE_10_SQ_NUM = re.compile(r'10\s*\u25a1\s*(\d)')
_RE_NUM_SQ_10 = re.compile(r'([\d.]+)\s*\u25a1\s*10')
_RE_ALPHA_SQ_NUM = re.compile(r'([a-zA-Z\u03bc])\s*\u25a1\s*(\d)')
_RE_DIG_SQ_DIG = re.compile(r'(\d)\s*\u25a1\s*(\d)')
_RE_DEG_C = re.compile(r'([\d.]+)\s*[\u02da\u00b0\u00ba\u25e6]\s*C\b', re.I)
_RE_SQ_C = re.compile(r'([\d.]+)\s*\u25a1\s*C\b', re.I)
_RE_DEG_SPACE_C = re.compile(r'([\d.]+)\s*°\s+C\b', re.I)
_RE_WE = re.compile(r'(\w)e(\d)')
_RE_M_S_NEG1 = re.compile(r'\b([m\u03bcunp]?M)\s+(s)\s*[\u207b\u2212\u2013\-]?\s*1\b')
_RE_MS_NEG1 = re.compile(r'\b([m\u03bcunp]?M)(s)\s*[\u207b\u2212\u2013\-]?\s*1\b')
_RE_S_NEG1 = re.compile(r'\b(s)\s+[\-–—]\s*1\b', re.I)
_RE_M_M_NEG1 = re.compile(r'\b(m)\s+(M)\s*[\u207b\u2212\u2013\-]?\s*1\b')
_RE_M_MS_NEG1 = re.compile(r'\b(m)\s+(Ms)\s*[\u207b\u2212\u2013\-]?\s*1\b', re.I)
_RE_M_M = re.compile(r'\b(m)\s+(M)\b')
_RE_NUM_10_NEG = re.compile(r'([\d.]+)\s+10\s*[\u207b\u2212\u2013\-]\s*(\d+)')
_RE_NUM_X10_NEG = re.compile(r'([\d.]+)\s*[x\u00d7]\s*10\s*[\^]?\s*[\u2212\u2013\-]\s*(\d+)')
_RE_NUM_X10_POS = re.compile(r'([\d.]+)\s*[x\u00d7]\s*10\s*[\^]?\s*(\d+)')
_RE_NUM_X10_BARE = re.compile(r'([\d.]+)\s*[x\u00d7]\s*10\s*(\d+)')
_RE_NUM_10_M_S = re.compile(r'(\d+)\s+10\s+(\d+)\s+Ms?\s*[\-–—]?\s*1\b', re.I)
_RE_NUM_10_MS = re.compile(r'(\d+)\s+10\s+(\d+)\s+[Mm]\s*[Ss]\s*[\-–—]?\s*1\b', re.I)
_RE_SCI_X10 = re.compile(r'([\d.]+)\s*[×x\u00d7]\s*10\s*[\^]?\s*([⁻\u207b\-–\u2013−\u2212]?)(\d+)')
_RE_SCI_E = re.compile(r'([\d.]+)\s*[eE]\s*([\-−\u2212]?)(\d+)')
_RE_SCI_BARE = re.compile(r'([\d.]+)\s+10\s*([⁻\u207b\-–\u2013−\u2212]?)(\d+)')
_RE_SCI_X10_LOOSE = re.compile(r'([\d.]+)\s*[×x\u00d7]?\s*10\s*([⁻\u207b\-–\u2013−\u2212]?)(\d+)')
_RE_10_MINUS = re.compile(r'10[\s]*[\-\u207b\u2212\u2013]')
_RE_NON_DIG_MINUS = re.compile(r'[^\d\-\u207b\u2212\u2013]')
_RE_NON_DIG = re.compile(r'[^\d]')
_RE_X10_UNIT = re.compile(r'^[×x\u00d7]\s*10\s*[\^]?\s*[\-−–]?\s*\d+$')
_RE_EXP_DIGITS = re.compile(r'[\-−–]?(\d+)')
_RE_VMAX_TEXT = re.compile(r'\bV\s*max\b', re.I)
_RE_VMAX_FULL = re.compile(r'\bmaximum\s+velocity\b', re.I)
_RE_E_NOTATION = re.compile(r'([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)')
_RE_X10_NOTATION = re.compile(r'([\d.]+)\s*[×x\u00d7]\s*10[\u207b\u207a\u2212\u2013\-–]?\s*(\d+)')
_RE_PLAIN_VM = re.compile(r'(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*(?:\u00b1\s*[\d.]+\s*)?(mM\u207b\u00b9|mM\u00b7s\u207b\u00b9|mM/?s|M\u207b\u00b9s\u207b\u00b9|M\u00b7s\u207b\u00b9|M/?s|mM\s*s\u207b\u00b9|M\s*s\u207b\u00b9)', re.I)
_RE_UPPER_WORD = re.compile(r'[A-Z][a-z]+')
_RE_COMPOSITE_SEP = re.compile(r'[/\\]\s*\w+\s+')
_RE_LEADING_DIGITS = re.compile(r'^\d+\s+')
_RE_RATIO_FORMAT = re.compile(r'^[A-Z]{2,4}/\d+$', re.I)
_RE_RATIO_FORMAT2 = re.compile(r'^[A-Z]{2,4}\d+/\d+$', re.I)
_RE_ION_FORMAT = re.compile(r'^[A-Z][a-z]?\d*[+-]$')
_RE_ELEMENT_FORMAT = re.compile(r'^([A-Z][a-z]?)\d+$')

def _normalize_ocr_scientific(text: str) -> str:
    if not text:
        return text
    t = text
    t = _RE_KM.sub('Km', t)
    t = _RE_VMAX.sub('Vmax', t)
    t = _RE_VM_NOAX.sub('Vmax', t)
    t = _RE_KCAT.sub('kcat', t)
    t = t.replace('\ufffd', '\u25a1')
    t = _RE_10_SQ_NUM.sub(lambda m: '10\u207b' + m.group(1), t)
    t = _RE_NUM_SQ_10.sub(lambda m: m.group(1) + ' \u00d710', t)
    t = _RE_ALPHA_SQ_NUM.sub(lambda m: m.group(1) + '\u207b' + m.group(2), t)
    t = _RE_DIG_SQ_DIG.sub(r'\1-\2', t)
    t = t.replace('\u00bc', '=')
    t = t.replace('\u0006', '\u00b1')
    t = _RE_DEG_C.sub(r'\1 °C', t)
    t = _RE_SQ_C.sub(r'\1 °C', t)
    t = _RE_DEG_SPACE_C.sub(r'\1 °C', t)
    t = _RE_WE.sub(lambda m: m.group(1) + ' \u2248 ' + m.group(2), t)
    t = _RE_M_S_NEG1.sub(lambda m: m.group(1) + '\u00b7' + m.group(2) + '\u207b\u00b9', t)
    t = _RE_MS_NEG1.sub(lambda m: m.group(1) + '\u00b7' + m.group(2) + '\u207b\u00b9', t)
    t = _RE_S_NEG1.sub(lambda m: m.group(1) + '\u207b\u00b9', t)
    t = _RE_M_M_NEG1.sub('mM\u207b\u00b9', t)
    t = _RE_M_MS_NEG1.sub('mM\u00b7s\u207b\u00b9', t)
    t = _RE_M_M.sub('mM', t)
    t = _RE_NUM_10_NEG.sub(lambda m: m.group(1) + ' \u00d7 10\u207b' + m.group(2), t)
    t = _RE_NUM_X10_NEG.sub(lambda m: m.group(1) + ' \u00d7 10\u207b' + m.group(2), t)
    t = _RE_NUM_X10_POS.sub(lambda m: m.group(1) + ' \u00d7 10' + m.group(2), t)
    t = _RE_NUM_X10_BARE.sub(lambda m: m.group(1) + ' \u00d7 10' + m.group(2), t)
    t = _RE_NUM_10_M_S.sub(lambda m: m.group(1) + ' \u00d7 10\u207b' + m.group(2) + ' M/s', t)
    t = _RE_NUM_10_MS.sub(lambda m: m.group(1) + ' \u00d7 10\u207b' + m.group(2) + ' M/s', t)
    t = t.replace('\u25a1', '')
    return t


def _parse_scientific_notation(s):
    try:
        return float(s)
    except (ValueError, TypeError):
        pass
    s = s.strip()
    m = _RE_SCI_X10.match(s)
    if m:
        base = float(m.group(1))
        sign = m.group(2)
        exp = int(m.group(3))
        if sign in ('\u207b', '-', '\u2013', '\u2212', '⁻'):
            return base * (10 ** -exp)
        return base * (10 ** exp)
    m = _RE_SCI_E.match(s)
    if m:
        base = float(m.group(1))
        sign = m.group(2)
        exp = int(m.group(3))
        if sign in ('-', '\u2212', '\u2212'):
            return base * (10 ** -exp)
        return base * (10 ** exp)
    m = _RE_SCI_BARE.match(s)
    if m:
        base = float(m.group(1))
        sign = m.group(2)
        exp = int(m.group(3))
        if sign in ('\u207b', '-', '\u2013', '\u2212', '⁻'):
            return base * (10 ** -exp)
        return base * (10 ** exp)
    m = _RE_SCI_X10_LOOSE.match(s)
    if m:
        base = float(m.group(1))
        sign = m.group(2)
        exp = int(m.group(3))
        if sign in ('\u207b', '-', '\u2013', '\u2212', '⁻'):
            return base * (10 ** -exp)
        return base * (10 ** exp)
    return s

_VMAX_PATTERNS = [
    re.compile(r'\bV\s*max\s*[\(（]\s*(\w[\w\d\-]*)\s*[\)）]\s*(?:was|=|:|≈|~)\s*([\d.]+(?:\s*[×x]\s*10[\^⁻\-–]?\s*[-]?\d+)?)\s*(?:±\s*[\d.]+\s*)?(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s)', re.I),
    re.compile(r'\bV\s*max\s+for\s+(\w[\w\d\-]*)\s+(?:\w+\s+){0,2}(?:was|=|:|≈|~)\s*([\d.]+(?:\s*[×x]\s*10[\^⁻\-–]?\s*[-]?\d+)?)\s*(?:±\s*[\d.]+\s*)?(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s)', re.I),
    re.compile(r'\bV\s*max\s+(?:\w+\s+){0,3}(?:was|=|:|≈|~)\s*([\d.]+(?:\s*[×x]\s*10[\^⁻\-–]?\s*[-]?\d+)?)\s*(?:±\s*[\d.]+\s*)?(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s)', re.I),
    re.compile(r'\bV\s*max\s*=\s*([\d.]+(?:\s*[×x]\s*10[\^⁻\-–]?\s*[-]?\d+)?)\s*(?:±\s*[\d.]+\s*)?(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s)', re.I),
    re.compile(r'\bV\s*max\s*\[([^\]]*)\]\s*([\d.]+(?:\s*[×x]\s*10[\^⁻\-–]?\s*[-]?\d+)?)', re.I),
    re.compile(r'\bV\s*max\s*[\(（]\s*(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s)\s*×?\s*10[\^⁻\-–]?\d*[\)）]\s+([\d.]+(?:\s*[×x]\s*10[\^⁻\-–]?\s*[-]?\d+)?)', re.I),
    re.compile(r'\bV\s*max\s+(?:for\s+\S+\s+)?(?:were|was)\s+([\d.]+(?:\s*[±\+\-]\s*[\d.]+)?)\s*(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s)', re.I),
    re.compile(r'\bKm\b.*?\bV\s*max\b.*?(?:were|was|calculated|found)\s+(?:to\s+be\s+)?([\d.]+)\s*(?:mM|mM|μM|uM|M)\s+and\s+([\d.]+(?:\s*[×x]\s*10[\^⁻\-–]?\s*[-]?\d+)?)\s*(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s)', re.I),
    re.compile(r'\bV\s*max\s+(?:for\s+\S+.*?)?(?:were|was)\s+([\d.]+)\s*[±\+\-]\s*[\d.]+\s*(?:and\s+([\d.]+)\s*[±\+\-]\s*[\d.]+\s+)?(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s)', re.I),
    re.compile(r'\bV\s*max\s+of\s+(\w[\w\d\-]*)\s+(?:was|=|:|≈|~)\s*([\d.]+(?:\s*[×x]\s*10[\^⁻\-–]?\s*[-]?\d+)?)\s*(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s)', re.I),
    re.compile(r'\bmaximum\s+velocity\s*(?:for\s+)?(\w[\w\d\-]*)?\s*(?:was|=|:|≈|~)\s*([\d.]+(?:\s*[×x]\s*10[\^⁻\-–]?\s*[-]?\d+)?)\s*(?:±\s*[\d.]+\s*)?(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s|mM\u00b7s\u207b\u00b9)', re.I),
    re.compile(r'\bmaximum\s+(?:initial\s+)?velocity\s*\)?\s*[^.]{0,40}?(?:was\s+)?(?:calculated\s+to\s+be|found\s+to\s+be)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*|\s+[\d.]+\s+)?(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s|mM\u00b7s\u207b\u00b9)', re.I),
    re.compile(r'\bV\s*max\s*\)?\s*[^.]{0,40}?(?:was\s+)?(?:calculated\s+to\s+be|found\s+to\s+be)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*|\s+[\d.]+\s+)?(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s|mM\u00b7s\u207b\u00b9)', re.I),
    re.compile(r'\bV\s*max\s*=\s*([\d.]+)\s+10\s*[\^⁻\-–]?\s*[-]?\s*(\d+)\s*(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s|mM\s*[sS])', re.I),
    re.compile(r'\bV\s*max\b[^.=]{0,30}?([\d.]+)\s*10\s*[\^⁻\-–]?\s*[-]?\s*(\d+)\s*(?:M\s*[sS]|mM\s*[sS])', re.I),
    re.compile(r'\bV\s*max\b[^.=]{0,20}?=\s*([\d.]+)\s+(mM|M|μM)\s*[sS]\s*[\^⁻\-–]?\s*[-]?\s*1', re.I),
    re.compile(r'\bV\s*max\s+values?\s+of\s+[^.]{0,80}?\b(?:are|were|is|was)\s+([\d.]+(?:[eE][\-]?\d+)?)\s*(?:and|&|,)\s*[\d.]+(?:[eE][\-]?\d+)?\s*(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s|M\s+s-1|M\u00b7s\u207b\u00b9)', re.I),
    re.compile(r'\bV\s*max\s+values?\s+of\s+\S+\s+(?:and|&)\s+\S+\s+(?:are|were)\s+([\d.]+(?:[eE][\-]?\d+)?)\s+(?:and|&|,)\s*[\d.]+(?:[eE][\-]?\d+)?\s*(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s|M\s+s-1|M\u00b7s\u207b\u00b9)', re.I),
    re.compile(r'\bare\s+([\d.]+(?:[eE][\-]?\d+)?)\s+(?:and|&|,)\s*[\d.]+(?:[eE][\-]?\d+)?\s*(M\u00b7s\u207b\u00b9|M\s*s\s*[\-–]\s*1|M/?s|mM/?s|μM/?s)', re.I),
    re.compile(r'\bV\s*max\s+(?:was|is)\s+(?:calculated\s+to\s+be|found\s+to\s+be|determined\s+to\s+be)\s*([\d.]+(?:\s*[×x]\s*10[\^⁻\-–]?\s*[-]?\d+)?)\s*(?:±\s*[\d.]+\s*)?(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s|M\s+s-1|mM\s+min-1)', re.I),
    re.compile(r'\bV\s*max\s+of\s+([\d.]+(?:\s*[×x]\s*10[\^⁻\-–]?\s*[-]?\d+)?)\s*(M\s*[sS][\^⁻\-–]?[\-]?1|M/?s|mM/?s|μM/?s|M\s+s-1|mM\s+min-1)', re.I),
    re.compile(r'\bV\s*max\s*=\s*([\d.]+)\s*(mM\s+min-1|mM/min|M\s+s-1)', re.I),
    re.compile(r'\bV\s*max\b[^.]{0,50}?([\d.]+)\s*(M\s*[sS][\u207b\u2212\u2013\-]?1|M/?s|mM/?s|μM/?s)', re.I),
    re.compile(r'\bV\s*max\b\s*[^.\d]{0,20}?([\d.]+)\s*[×x\u00d7]\s*10[\u207b\u2212\u2013\-](\d+)\s*(M\s*[sS]|mM\s*[sS])', re.I),
    re.compile(r'\bmaximum\s+velocity\b[^.]{0,50}?([\d.]+)\s*(M\s*[sS][\u207b\u2212\u2013\-]?1|M/?s|mM/?s|μM/?s)', re.I),
    re.compile(r'\bV\s*max\b[^.]{0,15}?determined\b[^.]{0,30}?([\d.]+)\s*(M\s*[sS][\u207b\u2212\u2013\-]?1|M/?s|mM/?s|μM/?s)', re.I),
    re.compile(r'\bV\s*max\b[^.]{0,40}?([\d.]+)\s*[eE][\-−]?\d+\s*(M\s*[sS][\u207b\u2212\u2013\-]?1|M/?s|mM/?s|μM/?s)', re.I),
]

_VMAX_OCR_PATTERNS = [
    re.compile(r'\bV\s*max\b[^.=]{0,30}?([\d.]+)\s*[×x\u00d7]?\s*10[\u207b⁻\-–\u2212\u2013]\s*(\d+)\s*(?:M\s*[sS]|mM\s*[sS]|M\u00b7s|mM\u00b7s)', re.I),
    re.compile(r'\bV\s*max\b[^.=]{0,30}?([\d.]+)\s+[×x\u00d7]?\s*10\s*[\u207b⁻\-–\u2212\u2013]\s*(\d+)', re.I),
    re.compile(r'\bV\s*max\b[^.=]{0,20}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*[×x\u00d7]?\s*10[\u207b⁻\-–\u2212\u2013]\s*(\d+)', re.I),
    re.compile(r'\bmaximum\s+velocity\b[^.=]{0,30}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*[×x\u00d7]?\s*10[\u207b⁻\-–\u2212\u2013]\s*(\d+)', re.I),
    re.compile(r'\bV\s*max\s*[\(（\[]\s*10[\u207b⁻\-–\u2212\u2013]\s*(\d+)\s*(?:M\s*[sS]|mM\s*[sS])\s*[\)）\]]\s*([\d.]+)', re.I),
    re.compile(r'\bV\s*max\b[^.=]{0,20}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)', re.I),
    re.compile(r'\bV\s*max\b[^.=]{0,30}?([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)\s*(?:M\s*[sS]|mM\s*[sS]|M/?s|mM/?s)', re.I),
]

_VMAX_UNIT_CONTEXT = re.compile(
    r'(?:M\s*[sS][\u207b⁻\-–\u2212\u2013]?1|M/?s|mM/?s|\u03bcM/?s|M\u00b7s|mM\u00b7s|\u03bcM\u00b7s|M\s*s\u207b\u00b9|mM\s*s\u207b\u00b9)',
    re.I
)

_VMAX_RATE_UNIT_RE = re.compile(
    r'(10[\u207b⁻\-–\u2212\u2013]?\d*\s*)?(mM|M|\u03bcM|uM|nM)\s*[\u00b7/\s]?\s*[sS]\s*[\u207b⁻\-–\u2212\u2013]?\s*[\u00b91]',
    re.I
)

_RATE_UNITS = frozenset({
    "M s⁻¹", "M s-1", "M s–1", "M s^-1", "M/s", "mM/s", "μM/s", "nM/s",
    "M S⁻¹", "M S-1", "mM·s⁻¹", "mM\u00b7s\u207b\u00b9",
    "M·s⁻¹", "μM·s⁻¹", "nM·s⁻¹", "M\u00b7s\u207b\u00b9",
    "M s⁻¹", "mM s⁻¹", "μM s⁻¹", "nM s⁻¹",
})


_SUPERSCRIPT_TO_ASCII = str.maketrans('⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾', '0123456789+-=()')


def _validate_and_assign_kinetics_unit(record_kinetics: dict, param: str, raw_unit: str) -> None:
    if not raw_unit:
        return
    _norm_fn = _normalize_unit_fn
    _conc_fn = _is_concentration_unit_fn
    _rate_fn = _is_rate_unit_fn
    if param == "Km":
        if _conc_fn and _conc_fn(raw_unit):
            record_kinetics["Km_unit"] = _norm_fn(raw_unit) if _norm_fn else raw_unit
        elif _rate_fn and _rate_fn(raw_unit):
            logger.warning(f"[SMN] Km_unit='{raw_unit}' is a rate unit, not concentration. Skipping.")
        else:
            record_kinetics["Km_unit"] = _norm_fn(raw_unit) if _norm_fn else raw_unit
    elif param == "Vmax":
        if _rate_fn and _rate_fn(raw_unit):
            norm_unit = _norm_fn(raw_unit) if _norm_fn else raw_unit
            vmax_val = record_kinetics.get("Vmax")
            if norm_unit in ("M/s", "M s^-1", "M s-1") and isinstance(vmax_val, (int, float)) and abs(vmax_val) < 1.0:
                new_val = vmax_val * 1e6
                record_kinetics["Vmax"] = new_val
                record_kinetics["Vmax_unit"] = "μM/s"
                logger.info(f"[SMN] Vmax auto-converted: {vmax_val} M/s -> {new_val} μM/s")
            elif norm_unit in ("mM/s", "mM s^-1", "mM s-1") and isinstance(vmax_val, (int, float)) and abs(vmax_val) < 1.0:
                new_val = vmax_val * 1e3
                record_kinetics["Vmax"] = new_val
                record_kinetics["Vmax_unit"] = "μM/s"
                logger.info(f"[SMN] Vmax auto-converted: {vmax_val} mM/s -> {new_val} μM/s")
            else:
                record_kinetics["Vmax_unit"] = norm_unit
        elif _conc_fn and _conc_fn(raw_unit):
            logger.warning(f"[SMN] Vmax_unit='{raw_unit}' is a concentration unit, not rate. Skipping.")
        else:
            record_kinetics["Vmax_unit"] = _norm_fn(raw_unit) if _norm_fn else raw_unit
    elif param in ("kcat", "kcat_Km"):
        record_kinetics[f"{param}_unit"] = _norm_fn(raw_unit) if _norm_fn else raw_unit


def _parse_unit_scientific_prefix(value: float, raw_unit: str) -> Tuple[float, str]:
    if not raw_unit or not isinstance(raw_unit, str):
        return value, raw_unit or ""
    _SUPERSCRIPT_MAP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")
    normalized_unit = raw_unit.translate(_SUPERSCRIPT_MAP)
    prefix_m = re.match(r'^[\s]*[×x\u00d7]\s*10[\^]?[\-]?\s*(\d+)\s+', normalized_unit.strip())
    if not prefix_m:
        return value, raw_unit
    exp_str = prefix_m.group(1)
    remaining_unit = normalized_unit[prefix_m.end():].strip()
    has_minus = bool(re.search(r'10[\^]?[\-]', normalized_unit[:prefix_m.end()]))
    try:
        exp_int = int(exp_str)
        if has_minus:
            adjusted = value * (10 ** -exp_int)
        else:
            adjusted = value * (10 ** exp_int)
        logger.info(f"[SMN] Parsed scientific prefix from unit: {value} * 10^{('-' if has_minus else '')}{exp_int} = {adjusted}, unit='{remaining_unit}'")
        return adjusted, remaining_unit
    except (ValueError, TypeError):
        return value, raw_unit


def _extract_vmax_fallback(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    norm = _normalize_ocr_scientific(text)
    norm = norm.translate(_SUPERSCRIPT_TO_ASCII)
    for pat in _VMAX_OCR_PATTERNS:
        m = pat.search(norm)
        if m:
            groups = m.groups()
            full_match = m.group(0)
            match_has_minus = bool(_RE_10_MINUS.search(full_match))
            if len(groups) == 2:
                base_str, exp_str = groups
                try:
                    base = float(base_str)
                    exp_clean = _RE_NON_DIG_MINUS.sub('', exp_str)
                    has_minus = match_has_minus or any(c in exp_clean for c in ('-', '\u207b', '\u2212', '\u2013', '⁻'))
                    exp_digits = _RE_NON_DIG.sub('', exp_clean)
                    exp_int = int(exp_digits) if exp_digits else 0
                    if has_minus:
                        vmax_val = base * (10 ** -exp_int)
                    else:
                        vmax_val = base * (10 ** exp_int)
                    unit_m = _VMAX_RATE_UNIT_RE.search(norm[m.end():m.end() + 30])
                    unit = unit_m.group(0).strip() if unit_m else None
                    return {"value": vmax_val, "unit": unit, "source": "text_ocr_fallback"}
                except (ValueError, TypeError):
                    continue
            elif len(groups) == 3:
                base_str, exp_str, unit = groups
                try:
                    base = float(base_str)
                    exp_clean = _RE_NON_DIG_MINUS.sub('', exp_str)
                    has_minus = match_has_minus or any(c in exp_clean for c in ('-', '\u207b', '\u2212', '\u2013', '⁻'))
                    exp_digits = _RE_NON_DIG.sub('', exp_clean)
                    exp_int = int(exp_digits) if exp_digits else 0
                    if has_minus:
                        vmax_val = base * (10 ** -exp_int)
                    else:
                        vmax_val = base * (10 ** exp_int)
                    return {"value": vmax_val, "unit": unit, "source": "text_ocr_fallback"}
                except (ValueError, TypeError):
                    continue
    vm = _RE_VMAX_TEXT.search(norm)
    if not vm:
        vm = _RE_VMAX_FULL.search(norm)
    if vm:
        after = norm[vm.end():vm.end() + 150]
        e_notation_m = _RE_E_NOTATION.search(after)
        if e_notation_m:
            try:
                parsed = _parse_scientific_notation(e_notation_m.group(0))
                if isinstance(parsed, (int, float)):
                    unit_m = _VMAX_RATE_UNIT_RE.search(after[e_notation_m.end():e_notation_m.end() + 30])
                    unit = unit_m.group(0).strip() if unit_m else None
                    return {"value": parsed, "unit": unit, "source": "text_ocr_fallback"}
            except (ValueError, TypeError):
                pass
        num_m = _RE_X10_NOTATION.search(after)
        if num_m:
            try:
                base = float(num_m.group(1))
                exp_str = num_m.group(2)
                full_match = num_m.group(0)
                has_minus = bool(_RE_10_MINUS.search(full_match))
                exp_int = int(exp_str)
                if has_minus:
                    vmax_val = base * (10 ** -exp_int)
                else:
                    vmax_val = base * (10 ** exp_int)
                unit_m = _VMAX_RATE_UNIT_RE.search(after[num_m.end():num_m.end() + 30])
                unit = unit_m.group(0).strip() if unit_m else None
                return {"value": vmax_val, "unit": unit, "source": "text_ocr_fallback"}
            except (ValueError, TypeError):
                pass
        plain_m = _RE_PLAIN_VM.search(after)
        if plain_m:
            try:
                vmax_val = float(plain_m.group(1))
                unit = plain_m.group(2).strip() if plain_m.lastindex >= 2 else None
                return {"value": vmax_val, "unit": unit, "source": "text_ocr_fallback"}
            except (ValueError, TypeError):
                pass
    return None
_LOD_PATTERNS = [
    re.compile(
        r'(?:LOD|limit\s+of\s+detection|detection\s+limit)\s*(?:of|=|:|≈|~|was|is)\s*([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm|U/L|mU/L|U/mL|ng/L|μg/L|mg/mL|pM|fM)',
        re.I,
    ),
    re.compile(
        r'(?:LOD|limit\s+of\s+detection|detection\s+limit)\s*[\(（]\s*([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm|U/L|mU/L|U/mL|ng/L|μg/L|mg/mL|pM|fM)\s*[\)）]',
        re.I,
    ),
    re.compile(
        r'(?:LOD|detection\s+limit)\s+(?:was\s+|is\s+)?(?:calculated\s+to\s+be\s+|found\s+to\s+be\s+)?([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm|U/L|mU/L|U/mL|ng/L|μg/L|mg/mL|pM|fM)',
        re.I,
    ),
    re.compile(
        r'(?:LOD|detection\s+limit)\s+(?:was\s+|is\s+)?(?:calculated\s+to\s+be\s+|found\s+to\s+be\s+)?([\d.]+)\s*(?:×\s*10[⁻\-–](\d))?\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm|U/L|mU/L|U/mL)',
        re.I,
    ),
    re.compile(
        r'(?:LOD|detection\s+limit)\s*(?:for|of)\s+\S+\s*(?:was|is|=|:|≈|~)\s*([\d.]+)\s*[×x\u00d7]\s*10[\u207b\u2212\u2013\-]?\s*(\d+)?\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm)',
        re.I,
    ),
    re.compile(
        r'(?:as\s+low\s+as)\s*([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm)',
        re.I,
    ),
    re.compile(
        r'(?:detect(?:ed|ion|ing))\s+(?:down\s+to|at)\s*([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm)',
        re.I,
    ),
    re.compile(
        r'(?:LOD|detection\s+limit)\s*[\(（\[]\s*([\d.]+)\s*[×x\u00d7]?\s*10[\u207b\u2212\u2013\-]?\s*(\d+)?\s*(nM|μM|uM|mM|M|pg/mL|ng/mL)\s*[\)）\]]',
        re.I,
    ),
    re.compile(
        r'(?:minimum\s+detect(?:able|ion))\s*(?:of|=|:|~)?\s*([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm)',
        re.I,
    ),
    re.compile(
        r'(?:sensitivity)\s*(?:of|=|:|~)?\s*([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm)',
        re.I,
    ),
    re.compile(
        r'(?:could\s+detect|can\s+detect|able\s+to\s+detect)\s+(?:down\s+to\s+)?([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm)',
        re.I,
    ),
    re.compile(
        r'(?:LOD|detection\s+limit)\s*(?:of|was|is|=|:|≈|~)\s*([\d.]+)\s*[×x\u00d7]\s*10[\u207b\u2212\u2013\-](\d+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm|pM|fM)',
        re.I,
    ),
    re.compile(
        r'(?:detectable|determined|achieved)\s+(?:at|down\s+to|as\s+low\s+as)\s*([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm|pM|fM)',
        re.I,
    ),
    re.compile(
        r'(?:LOD|detection\s+limit)\s*(?:reached|obtained|calculated)\s*(?:was\s+)?([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm|pM|fM)',
        re.I,
    ),
    re.compile(
        r'(?:limit\s+of\s+quantitation|LOQ)\s*(?:of|=|:|≈|~|was|is)\s*([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm|pM|fM)',
        re.I,
    ),
    re.compile(
        r'(?:the\s+)?(?:lowest\s+)?(?:detect(?:able|ed))\s+(?:concentration|level|amount)\s*(?:was|is|=|:)\s*([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm)',
        re.I,
    ),
]
_LINEAR_RANGE_PATTERNS = [
    re.compile(
        r'(?:linear\s+range|linear\s+detection\s+range|calibration\s+range)\s*(?:of|=|:|≈|~|was|is)\s*([\d.]+\s*[-–—~to]+\s*[\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|U/L|mU/L|U/mL)',
        re.I,
    ),
    re.compile(
        r'(?:linear\s+range|calibration\s+range)\s*[\(（]\s*([\d.]+\s*[-–—~to]+\s*[\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|U/L|mU/L|U/mL)\s*[\)）]',
        re.I,
    ),
    re.compile(
        r'(?:in|within)\s+(?:the\s+)?(?:range\s+of\s+)?([\d.]+\s*[-–—~to]+\s*[\d.]+)\s*(U/L|mU/L|U/mL|nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L)',
        re.I,
    ),
    re.compile(
        r'(?:range|concentration\s+range)\s*(?:of|=|:)\s*([\d.]+\s*[-–—~to]+\s*[\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L)',
        re.I,
    ),
    re.compile(
        r'([\d.]+)\s*[-–—~]\s*([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L)\s+(?:linear|calibration)',
        re.I,
    ),
    re.compile(
        r'(?:working\s+range|dynamic\s+range)\s*(?:of|=|:|~)?\s*([\d.]+\s*[-–—~to]+\s*[\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|U/L|mU/L)',
        re.I,
    ),
    re.compile(
        r'(?:linear|calibration)\s+(?:from|between)\s*([\d.]+)\s*(?:to|[-–—~])\s*([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L)',
        re.I,
    ),
    re.compile(
        r'(?:linear\s+)?(?:response|relationship|calibration)\s+(?:from|between|in\s+the\s+range\s+of)\s*([\d.]+)\s*(?:to|[-–—~])\s*([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|U/L|mU/L|U/mL)',
        re.I,
    ),
    re.compile(
        r'(?:concentration\s+range|range\s+of\s+concentration)\s*(?:of|=|:|was|from)\s*([\d.]+)\s*(?:to|[-–—~])\s*([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L)',
        re.I,
    ),
    re.compile(
        r'(?:quantif|determin|measur)\s+(?:from|between|in\s+the\s+range)\s*([\d.]+)\s*(?:to|[-–—~])\s*([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L)',
        re.I,
    ),
]

_BUCKET_KEYWORDS = {
    "material": re.compile(
        r"(?:composition|morpholog|size|element|dopan|defect|stability|"
        r"synthes|prepar|fabricat|nanoparticle|nanosheet|nanotube|nanorod|"
        r"core-shell|yolk-shell|hollow|mesoporous|"
        r"crystal|amorphous|spinel|perovskite|anatase|rutile|"
        r"calcination|annealing|carbonization|pyrolysis|"
        r"dopan|incorporat|substitut|alloy|bimetal|trimetal|"
        r"composite|hybrid|heterostructur|core@shell|"
        r"nanocluster|nanoflower|nanowire|nanocube|nanoprism|"
        r"nanodot|quantum\s+dot|nanoframe|nanocage)", re.I),
    "synthesis": re.compile(
        r"(?:synthes|prepar|fabricat|hydrothermal|calcination|annealing|"
        r"solvothermal|co-precipitation|sol-gel|precursor|"
        r"temperature|heated|furnace|reaction\s+time|"
        r"one-pot|two-step|in-situ|ex-situ|"
        r"microwave|ultrasoni|electrospinn|sputter|"
        r"magnetron|plasma|laser\s+ablat|ball\s+mil|"
        r"freeze-dry|lyophiliz|solvent|atmosphere|"
        r"aging|stirring|centrifug|washed|dried|"
        r"carboniz|pyrolyz|calcined|annealed|"
        r"impregnat|graft|immobiliz|load)", re.I),
    "characterization": re.compile(
        r"(?:SEM|TEM|XRD|XPS|Raman|FTIR|EPR|AFM|EDX|EDS|SAED|"
        r"HAADF|HRTEM|XAFS|XANES|EXAFS|BET|TG|DTA|ICP|"
        r"zeta\s+potential|surface\s+area|pore\s+size|BJH|"
        r"lattice|d-spacing|crystallite|"
        r"XRF|ICP-MS|TGA|DSC|DTG|Mössbauer|"
        r"UV-vis|PL|FL|photoluminesc|fluorescen|"
        r"ESR|ENDOR|NMR|MALDI|TOF|"
        r"mapping|elemental\s+map|line\s+scan|"
        r"selected\s+area|diffraction|fringe)", re.I),
    "activity": re.compile(
        r"(?:peroxidase-like|oxidase-like|catalase-like|SOD-like|"
        r"enzyme-like|catalytic\s+activ|substrate|assay|TMB|ABTS|OPD|"
        r"DCFH|pH|buffer|reaction\s+time|temperature|"
        r"optimal\s+pH|optimal\s+temperature|pH\s+dependent|temperature\s+dependent|"
        r"pH\s+range|pH\s+stability|thermal\s+stability|"
        r"enzyme-mimick|enzyme\s+mimet|nanozyme\s+activ|"
        r"catalytic\s+perform|catalytic\s+efficien|"
        r"specific\s+activ|turnover|TOF|TOFN|"
        r"Michaelis|Mentent|steady.state|"
        r"colorimetric|spectrophotometr|absorbance|"
        r"oxidat|reduct|degrad|decomposit)", re.I),
    "kinetics": re.compile(
        r"(?:Km|K\s*m|Vmax|V\s*m|Michaelis|Lineweaver|"
        r"mM|M\s*s[−\-–]1|Ms[⁻\-–]1|M[·\s]s[⁻\-–]1|M/?s|"
        r"[mμunp]?M/?s[⁻\-–]?1|[mμunp]?M[·\s]s[⁻\-–]¹|"
        r"×10|kinetic|kcat|specificity\s+constant|"
        r"steady\s+state|catalytic\s+efficiency|"
        r"affinity|binding\s+constant|Kd|"
        r"Lineweaver.Burk|double.reciprocal|Eadie.Hofstee|"
        r"Hanes.Woolf|Scatchard|Hill\s+plot|"
        r"substrate\s+concentr|initial\s+rate|V0|v0|"
        r"apparent\s+Km|apparent\s+Vmax|"
        r"Km\s*value|Vmax\s*value|Kcat\s*value)", re.I),
    "application": re.compile(
        r"(?:detection|sensing|sensor|LOD|linear\s+range|recovery|"
        r"sample|serum|water|food|limit\s+of\s+detection|calibrat|"
        r"biosensor|colorimetric|fluorescent|electrochem|"
        r"diagnos|theranost|therapeutic|antitumor|antibacterial|"
        r"wound\s+heal|cytoprotect|neuroprotect|anti.?inflammator|"
        r"biofilm|disinfect|steriliz|degrad|pollutant|"
        r"heavy\s+metal|pesticide|organophosph|endocrine|"
        r"glucose|cholesterol|uric\s+acid|lactate|ascorbic|"
        r"dopamine|cysteine|glutathione|bilirubin|"
        r"cancer|tumor|xenograft|in\s+vivo|in\s+vitro|"
        r"cell\s+viabil|apoptosis|ROS.?scaveng|oxidative\s+stress|"
        r"environmental|drinking\s+water|waste\s+water|"
        r"river|lake|tap\s+water|sea\s+water|"
        r"selectiv|interfer|real\s+sample|spike|recover|"
        r"RSD|reproducib|reusab|recycl|"
        r"point.of.care|POCT|paper.based|microfluid|"
        r"wearab|implant|stent|coating)", re.I),
    "mechanism": re.compile(
        r"(?:ROS|O2[•\-\*]|•OH|1O2|electron\s+transfer|oxygen\s+vacancy|"
        r"active\s+site|radical|scaveng|mechanism|Fenton|Haber-Weiss|"
        r"superoxide|hydroxyl|singlet\s+oxygen|"
        r"photocataly|sonocataly|piezocataly|electrocataly|"
        r"Schottky|band\s+gap|conduction\s+band|valence\s+band|"
        r"charge\s+separat|recombinat|exciton|"
        r"catalytic\s+mechan|reaction\s+pathway|"
        r"radical\s+trapp|EPR\s+signal|DMPO|TEMP|"
        r"quench|scavenger|isopropanol|p-benzoquinone|EDTA|"
        r"density\s+functional|DFT|computational|adsorption\s+energy|"
        r"d.band|charge\s+density|density\s+of\s+states)", re.I),
}

_SYNTHESIS_METHODS = {
    "hydrothermal": re.compile(r'\bhydrothermal\b', re.I),
    "solvothermal": re.compile(r'\bsolvothermal\b', re.I),
    "co-precipitation": re.compile(r'\bco-?precipitat', re.I),
    "sol-gel": re.compile(r'\bsol-?gel\b', re.I),
    "calcination": re.compile(r'\bcalcina|calcined\b', re.I),
    "annealing": re.compile(r'\banneal', re.I),
    "spray_pyrolysis": re.compile(r'\bspray\s+pyrolys', re.I),
    "pyrolysis": re.compile(r'\bpyrolys', re.I),
    "chemical_vapor_deposition": re.compile(r'\bchemical\s+vapor\s+deposition\b|\bCVD\b', re.I),
    "atomic_layer_deposition": re.compile(r'\batomic\s+layer\s+deposition\b|\bALD\b', re.I),
    "pulsed_laser_deposition": re.compile(r'\bpulsed\s+laser\s+deposition\b|\bPLD\b', re.I),
    "electrospinning": re.compile(r'\belectrospinn', re.I),
    "microwave": re.compile(r'\bmicrowave', re.I),
    "ultrasonic": re.compile(r'\bultrasoni', re.I),
    "sacrificial_template": re.compile(r'\bsacrificial\s+template', re.I),
    "template_method": re.compile(r'\btemplate[-\s]?assist|\btemplate\s+method', re.I),
    "self-assembly": re.compile(r'\bself[-\s]?assembl', re.I),
    "wet_chemical": re.compile(r'\bwet\s+chemical', re.I),
    "solid_state": re.compile(r'\bsolid[-\s]?state\s+(?:reaction|method|synthesis)', re.I),
    "biomimetic_mineralization": re.compile(r'\bbiomimetic\s+mineraliz', re.I),
    "dealloying": re.compile(r'\bdealloy', re.I),
    "laser_ablation": re.compile(r'\blaser\s+ablat', re.I),
    "green_synthesis": re.compile(r'\bgreen\s+synthesis', re.I),
    "reverse_microemulsion": re.compile(r'\breverse\s+microemuls', re.I),
    "microemulsion": re.compile(r'\bmicroemuls', re.I),
    "polyol_method": re.compile(r'\bpolyol\s+method', re.I),
    "thermal_decomposition": re.compile(r'\bthermal\s+decompos', re.I),
    "carbonization": re.compile(r'\bcarbonizat', re.I),
    "dopamine_polymerization": re.compile(r'\bdopamine\s+polymeriz|\bpolydopamine', re.I),
    "impregnation": re.compile(r'\bimpregnat', re.I),
    "copolymerization": re.compile(r'\bcopolymeriz', re.I),
    "ion_exchange": re.compile(r'\bion\s+exchange', re.I),
    "etching": re.compile(r'\betch', re.I),
    "sintering": re.compile(r'\bsinter', re.I),
    "magnetron_sputtering": re.compile(r'\bmagnetron\s+sputter', re.I),
    "electrodeposition": re.compile(r'\belectrodepos', re.I),
    "coordination": re.compile(r'\bcoordination\s+(?:polymer|complex|compound)', re.I),
    "anchoring": re.compile(r'\banchor', re.I),
    "doping": re.compile(r'\bdop(?:ed|ing)\b', re.I),
    "general_synthesis": re.compile(r'\b(?:synthesized|prepared|fabricated|obtained)\b', re.I),
    "striping": re.compile(r'\bstrip(?:e|ing)\s+(?:off|from|away|out)\b', re.I),
    "nitrogen_coordination": re.compile(r'\bnitrogen[-\s]?coordinated\b', re.I),
    "carbon_support": re.compile(r'\bcarbon[-\s]?supported\b', re.I),
    "immobilization": re.compile(r'\bimmobiliz', re.I),
    "encapsulation": re.compile(r'\bencapsulat', re.I),
    "deposition": re.compile(r'\bdeposit', re.I),
    "reduction": re.compile(r'\breduc(?:ed|tion)\s+(?:by|with|using|via|through)\b', re.I),
    "freeze_drying": re.compile(r'\bfreeze[-\s]?dry', re.I),
    "ball_milling": re.compile(r'\bball[-\s]?mill', re.I),
    "3d_printing": re.compile(r'\b3D\s+print', re.I),
    "supercritical_drying": re.compile(r'\bsupercritical\s+dry', re.I),
}

_PH_PATTERNS = {
    "optimal_pH": [
        re.compile(r'\boptimal\s+pH\s*(?:was|=|:|≈|~|of|at)\s*([\d.]+)', re.I),
        re.compile(r'\boptimum\s+pH\s*(?:was|=|:|≈|~|of|at)\s*([\d.]+)', re.I),
        re.compile(r'\bpH\s+optimum\s*(?:was|=|:|≈|~)\s*([\d.]+)', re.I),
        re.compile(r'\boptimal\s+(?:reaction\s+)?pH\s+(?:for|of)\s+\w+\s+(?:was|=|:|≈|~)\s*([\d.]+)', re.I),
        re.compile(r'\bpH\s*([\d.]+)\s+was\s+(?:the\s+)?(?:optimal|optimum|best)', re.I),
        re.compile(r'\boptimal\s+pH\s+of\s*([\d.]+)', re.I),
        re.compile(r'\bpH\s*([\d.]+)\s+(?:gave|yielded|produced)\s+(?:the\s+)?(?:highest|maximum|optimal|best)', re.I),
        re.compile(r'\bactivity\s+(?:peaked|maximum|highest)\s+(?:at|under)\s+pH\s*([\d.]+)', re.I),
        re.compile(r'\bpH\s*([\d.]+)\s+(?:is|was)\s+(?:the\s+)?(?:most\s+)?(?:active|efficient|effective|favorable)', re.I),
        re.compile(r'\bpH\s*([\d.]+)\s+(?:showed|exhibited|displayed|demonstrated)\s+(?:the\s+)?(?:highest|maximum|max|best|greatest)\s+(?:catalytic\s+)?activity', re.I),
        re.compile(r'\b(?:highest|maximum|max|best|greatest)\s+(?:catalytic\s+)?activity\s+(?:was\s+)?(?:observed|found|achieved|measured|obtained|recorded)\s+at\s+pH\s*([\d.]+)', re.I),
        re.compile(r'\bpH\s*([\d.]+)\s+(?:was|is)\s+(?:the\s+)?(?:most\s+)?(?:favorable|suitable|preferred)', re.I),
        re.compile(r'\bpH\s*(?:value\s+)?(?:of\s+)?([\d.]+)\s+(?:gave|showed|had)\s+(?:the\s+)?(?:highest|maximum|best)', re.I),
        re.compile(r'\b(?:at|under)\s+pH\s*([\d.]+)[,.]?\s*(?:the\s+)?(?:activity\s+)?(?:was\s+)?(?:the\s+)?(?:highest|maximum|best|optimal)', re.I),
        re.compile(r'\b(?:the\s+)?activity\s+(?:of\s+)?(?:the\s+)?(?:nanozyme|catalyst|enzyme|material)\s+(?:reached|attained)\s+(?:its\s+)?(?:maximum|peak|highest)\s+(?:at|under)\s+pH\s*([\d.]+)', re.I),
        re.compile(r'\bpH\s*([\d.]+)\s*\([^)]*optimal[^)]*\)', re.I),
        re.compile(r'\bpH\s*([\d.]+)\s*\([^)]*max[^)]*\)', re.I),
        re.compile(r'\b(?:the\s+)?(?:relative|nanozyme|catalytic)\s+activity\s+(?:reached|was)\s+(?:the\s+)?(?:highest|maximum)\s+at\s+pH\s*([\d.]+)', re.I),
        re.compile(r'\bpH\s*([\d.]+)\s*\)[^)]*(?:optimal|maximum|highest)', re.I),
        re.compile(r'\bpH\s+optimum\s*(?:was|=|:|≈|~)\s*([\d.]+)', re.I),
        re.compile(r'\bmaximum\s+activity\s*(?:at|was\s+observed\s+at)\s*pH\s*([\d.]+)', re.I),
        re.compile(r'\b(?:best|highest)\s+(?:catalytic\s+)?activity\s*(?:at|was)\s*pH\s*([\d.]+)', re.I),
    ],
    "pH_range": [
        re.compile(r'\bpH\s+range\s*(?:of|=|:|≈|~|was|from)\s*([\d.]+)\s*[-–—~to]+\s*([\d.]+)', re.I),
        re.compile(r'\bactive\s+pH\s+range\s*([\d.]+)\s*[-–—~to]+\s*([\d.]+)', re.I),
        re.compile(r'\bpH\s*([\d.]+)\s*[-–—~to]+\s*([\d.]+)\s+(?:was|showed|exhibited)\s+(?:the\s+)?(?:highest|maximum|optimal)', re.I),
        re.compile(r'\bpH\s+range\s+of\s*([\d.]+)\s*[\u2013\-–—]\s*([\d.]+)', re.I),
        re.compile(r'\bpH\s+([\d.]+)\s*[\u2013\-–—]\s*([\d.]+)\s+(?:with|showed)', re.I),
        re.compile(r'\bpH\s*([\d.]+)\s*[-–—~to]+\s*([\d.]+)\s*,?\s*(?:with|and|showing)\s+(?:the\s+)?(?:highest|maximum|optimal|best)', re.I),
        re.compile(r'\b(?:within|over|in)\s+(?:the\s+)?pH\s+(?:range\s+)?(?:of\s+)?([\d.]+)\s*[-–—~to]+\s*([\d.]+)', re.I),
        re.compile(r'\bpH\s+([\d.]+)\s*[-–—]\s*([\d.]+)\s+was\s+(?:the\s+)?(?:optimal|active)', re.I),
    ],
}

_TEMPERATURE_PATTERNS = {
    "optimal_temperature": [
        re.compile(r'\boptimal\s+(?:reaction\s+)?temperature\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\boptimum\s+(?:reaction\s+)?temperature\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\btemperature\s+optimum\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\boptimal\s+temperature\s+of\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\b(?:highest|maximum|max|best)\s+(?:catalytic\s+)?activity\s+(?:was\s+)?(?:observed|found|achieved|measured|obtained|recorded)\s+at\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\bactivity\s+(?:peaked|peak|reached\s+(?:its\s+)?(?:maximum|peak|highest))\s+at\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\b([\d.]+)\s*°?\s*C\s+(?:was|is)\s+(?:the\s+)?(?:optimal|optimum|best|most\s+favorable)\s+temperature', re.I),
        re.compile(r'\b(?:at|under)\s*([\d.]+)\s*°?\s*C[,.]?\s*(?:the\s+)?(?:activity\s+)?(?:was\s+)?(?:the\s+)?(?:highest|maximum|best|optimal)', re.I),
        re.compile(r'\btemperature\s*(?:of\s+)?([\d.]+)\s*°?C\s+(?:gave|showed|yielded|produced|had)\s+(?:the\s+)?(?:highest|maximum|best|optimal)\s+(?:activity|performance)', re.I),
        re.compile(r'\b(?:the\s+)?(?:relative|nanozyme|catalytic)\s+activity\s+(?:reached|was)\s+(?:the\s+)?(?:highest|maximum)\s+at\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\b([\d.]+)\s*°?\s*C\s*\([^)]*optimal[^)]*\)', re.I),
        re.compile(r'\b([\d.]+)\s*°?\s*C\s*\([^)]*max[^)]*\)', re.I),
        re.compile(r'\boptimal\s+temperature\s*(?:of|was|=|:|≈|~|at)\s*([\d.]+)\s*[\u02da\u00b0\u00ba\u25e6]\s*C', re.I),
        re.compile(r'\boptimum\s+temperature\s*(?:of|was|=|:|≈|~|at)\s*([\d.]+)\s*[\u02da\u00b0\u00ba\u25e6]\s*C', re.I),
        re.compile(r'\btemperature\s+optimum\b[^.]{0,20}?([\d.]+)\s*[\u02da\u00b0\u00ba\u25e6]\s*C', re.I),
        re.compile(r'\bmaximum\s+activity\s*(?:at|was\s+observed\s+at)\s*([\d.]+)\s*[\u02da\u00b0\u00ba\u25e6]\s*C', re.I),
        re.compile(r'\b(?:best|highest)\s+(?:catalytic\s+)?activity\s*(?:at|was)\s*([\d.]+)\s*[\u02da\u00b0\u00ba\u25e6]\s*C', re.I),
    ],
    "temperature_range": [
        re.compile(r'\btemperature\s+range\s*(?:of|=|:|≈|~|was|from)\s*([\d.]+)\s*[-–—~to]+\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\bactive\s+temperature\s+range\s*([\d.]+)\s*[-–—~to]+\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\btemperature\s+([\d.]+)\s*[-–—~to]+\s*([\d.]+)\s*°C\s+(?:with|showed)', re.I),
        re.compile(r'\b(?:within|over|in)\s+(?:the\s+)?temperature\s+(?:range\s+)?(?:of\s+)?([\d.]+)\s*[-–—~to]+\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\b([\d.]+)\s*[-–—]\s*([\d.]+)\s*°C\s+(?:was|were)\s+(?:the\s+)?(?:optimal|active|best)', re.I),
    ],
}

_SIZE_PATTERNS = [
    re.compile(r'\b(?:average\s+)?(?:particle\s+)?size\s*(?:of|was|=|:|≈|~)\s*(?:about\s+|approximately\s+|around\s+|ca\.?\s*)?([\d.]+)\s*[-–—~to]+\s*([\d.]+)\s*(nm|μm|um|mm|Å)', re.I),
    re.compile(r'\b(?:average\s+)?(?:particle\s+)?size\s*(?:of|was|=|:|≈|~)\s*(?:about\s+|approximately\s+|around\s+|ca\.?\s*)?([\d.]+)\s*(nm|μm|um|mm|Å)', re.I),
    re.compile(r'\bdiameter\s*(?:of|was|=|:|≈|~)\s*(?:about\s+|approximately\s+|around\s+|ca\.?\s*)?([\d.]+)\s*(nm|μm|um|mm|Å)', re.I),
    re.compile(r'\b(?:with|having)\s+(?:a\s+)?(?:size|diameter)\s+(?:of\s+)?([\d.]+)\s*[-–—~to]+\s*([\d.]+)\s*(nm|μm|um|mm)', re.I),
    re.compile(r'\b(?:with|having)\s+(?:a\s+)?(?:size|diameter)\s+(?:of\s+)?([\d.]+)\s*(nm|μm|um|mm)', re.I),
    re.compile(r'\bsize\s+distribution\s*(?:of|was|=|:|≈|~)\s*([\d.]+)\s*[-–—~to]+\s*([\d.]+)\s*(nm|μm|um)', re.I),
    re.compile(r'\bDLS\s+(?:analysis|measurement|result)\s+showed\s+(?:an?\s+)?(?:average\s+)?(?:size|diameter)\s+(?:of\s+)?([\d.]+)\s*(nm|μm|um)', re.I),
    re.compile(r'\bhydrodynamic\s+(?:size|diameter)\s*(?:of|was|=|:|≈|~)\s*([\d.]+)\s*(nm|μm|um)', re.I),
    re.compile(r'\b([\d.]+)\s*[-–—~to]+\s*([\d.]+)\s*(nm|μm|um)\s+in\s+(?:size|diameter)\b', re.I),
    re.compile(r'\b([\d.]+)\s*(nm|μm|um)\s+in\s+(?:size|diameter)\b', re.I),
    re.compile(r'\b(?:d|diameter|size)\s*(?:=|≈|~|was|of)\s*(?:about\s+|ca\.?\s*)?([\d.]+)\s*(nm|μm|um)\b', re.I),
    re.compile(r'\b(?:uniform\s+)?(?:size|diameter)\s*[\(=]\s*[\w.]*\s*[:=]?\s*([\d.]+)\s*(nm|μm|um)\b', re.I),
    re.compile(r'\b([\d.]+)\s*(nm|μm|um)\s*(?:in\s+)?(?:size|diameter|length|thickness|width)\b', re.I),
    re.compile(r'\blength\s*(?:of|was|=|:|≈|~)\s*(?:about\s+|ca\.?\s*)?([\d.]+)\s*(nm|μm|um|mm)\b', re.I),
    re.compile(r'\bthickness\s*(?:of|was|=|:|≈|~)\s*(?:about\s+|ca\.?\s*)?([\d.]+)\s*(nm|μm|um|mm|Å)\b', re.I),
    re.compile(r'\bwidth\s*(?:of|was|=|:|≈|~)\s*(?:about\s+|ca\.?\s*)?([\d.]+)\s*(nm|μm|um|mm)\b', re.I),
    re.compile(r'\b(?:lattice|crystallite)\s+(?:size|parameter|spacing)\s*(?:of|was|=|:|≈|~)\s*([\d.]+)\s*(nm|Å|Å)\b', re.I),
    re.compile(r'\baverage\s+([\d.]+)\s*[-–—~]\s*([\d.]+)\s*(nm|μm|um)\b', re.I),
    re.compile(r'\b(?:approximately|about|around|ca\.?|~|≈)\s*([\d.]+)\s*[-–—~]\s*([\d.]+)\s*(nm|μm|um)\b', re.I),
]

_SURFACE_AREA_PATTERNS = [
    re.compile(r'\b(?:specific\s+)?surface\s+area\s*(?:of|was|=|:|≈|~)\s*([\d.]+)\s*(m2/g|m²/g|m2\s*g[-−]1)', re.I),
    re.compile(r'\bBET\s+surface\s+area\s*(?:of|was|=|:|≈|~)\s*([\d.]+)\s*(m2/g|m²/g)', re.I),
    re.compile(r'\bBET\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*(m2/g|m²/g)', re.I),
]

_ZETA_POTENTIAL_PATTERNS = [
    re.compile(r'\bzeta\s+potential\s*(?:of|was|=|:|≈|~)\s*[-−]?([\d.]+)\s*(mV)', re.I),
    re.compile(r'\bsurface\s+charge\s*(?:of|was|=|:|≈|~)\s*[-−]?([\d.]+)\s*(mV)', re.I),
    re.compile(r'\bsurface\s+potential\s*(?:of|was|=|:|≈|~)\s*[-−]?([\d.]+)\s*(mV)', re.I),
    re.compile(r'\bζ\s*[-−]?\s*potential\s*(?:of|was|=|:|≈|~)\s*[-−]?([\d.]+)\s*(mV)', re.I),
    re.compile(r'\b(?:showed|exhibited|measured)\s+(?:a\s+)?zeta\s+potential\s+(?:of\s+)?[-−]?([\d.]+)\s*(mV)', re.I),
]

_PORE_SIZE_PATTERNS = [
    re.compile(r'\bpore\s+(?:size|diameter|width)\s*(?:of|was|=|:|≈|~)\s*([\d.]+)\s*(nm|Å|μm|um)', re.I),
    re.compile(r'\baverage\s+pore\s+(?:size|diameter)\s*(?:of|was|=|:|≈|~)\s*([\d.]+)\s*(nm|Å)', re.I),
    re.compile(r'\bBJH\s+pore\s+(?:size|diameter)\s*(?:of|was|=|:|≈|~)\s*([\d.]+)\s*(nm|Å)', re.I),
]

_CRYSTAL_STRUCTURE_PATTERNS = [
    re.compile(r'\b(?:spinel|perovskite|fluorite|rock\s*salt|zinc\s*blende|wurtzite|rutile|anatase|brookite)\s+structure\b', re.I),
    re.compile(r'\bcubic\s+(?:phase|structure)', re.I),
    re.compile(r'\btetragonal\s+(?:phase|structure)', re.I),
    re.compile(r'\bhexagonal\s+(?:phase|structure)', re.I),
    re.compile(r'\borthorhombic\s+(?:phase|structure)', re.I),
    re.compile(r'\bmonoclinic\s+(?:phase|structure)', re.I),
    re.compile(r'\bamorphous\s+(?:phase|structure|nature|carbon|matrix|framework|material)', re.I),
    re.compile(r'\bcrystalline\s+(?:phase|structure|nature|material)', re.I),
    re.compile(r'\bXRD\s+(?:pattern|analysis|result)\s+(?:confirmed|showed|revealed|indicated)\s+(?:the\s+)?(\w+)', re.I),
    re.compile(r'\bgraphitic\s+(?:carbon|structure|phase)', re.I),
    re.compile(r'\b(?:face-centered|body-centered)\s+cubic\b', re.I),
    re.compile(r'\bXRD\s+(?:confirmed|showed)\s+(?:a\s+)?(\w+)\s+(?:phase|structure)', re.I),
    re.compile(r'\bSAED\s+(?:pattern|analysis)\s+(?:confirmed|showed|indicated)\s+(?:the\s+)?(\w+)', re.I),
    re.compile(r'\((\d{3})\)\s*,\s*\((\d{3})\)\s*,\s*(?:and\s+)?\((\d{3})\)\s+planes?\b', re.I),
    re.compile(r'\((\d{3})\)\s+(?:and|&)\s*\((\d{3})\)\s+planes?\b', re.I),
    re.compile(r'\b(?:ascribed|assigned|indexed|attributed)\s+to\s+(?:the\s+)?\((\d{3})\)\s+planes?\b', re.I),
    re.compile(r'\bd\s*[\s-]?\s*spacing\s+(?:values?\s+)?(?:of\s+)?(?:approximately\s+)?([\d.]+)\s*(?:,|and|&|\s)\s*([\d.]+)\s*(?:,|and|&|\s)\s*([\d.]+)\s*(nm|Å)', re.I),
    re.compile(r'\bd\s*[\s-]?\s*spacing\s+(?:value\s+)?(?:of\s+)?(?:approximately\s+)?([\d.]+)\s*(nm|Å)', re.I),
]

_SYNTHESIS_CONDITION_PATTERNS = {
    "temperature": [
        re.compile(r'\b(?:synthesized|prepared|calcined|annealed|heated|carbonized|pyrolyzed|sintered|treated)\s+(?:at|under)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\b(?:hydrothermal|solvothermal)\s+(?:treatment|reaction|synthesis)\s+(?:at|under)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\bfurnace\s+(?:at|under)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\b(?:calcination|annealing|pyrolysis|carbonization|sintering)\s+(?:temperature|temp)\s*(?:of|was|=|:)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\b(?:calcined|annealed|carbonized|pyrolyzed|sintered)\s+in\s+(?:air|N2|Ar|nitrogen|argon|vacuum)\s+(?:at\s+)?([\d.]+)\s*°?C', re.I),
        re.compile(r'\b(?:subsequent|followed\s+by)\s+(?:calcination|annealing|pyrolysis|carbonization)\s+(?:at|under)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\b(?:heated|calcined|annealed|carbonized|pyrolyzed)\s+(?:to|up\s+to)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\b([\d.]+)\s*°C\s*(?:for|during)\s+[\d.]+\s*(?:h|hr|min)\b', re.I),
        re.compile(r'\b(?:calcined|annealed|heated|sintered)\s+at\s*([\d.]+)\s*[°º˚]?\s*C', re.I),
        re.compile(r'\b(?:calcination|annealing|sintering)\s+(?:temperature|temp)\s*(?:of|was|=|:|≈|~)\s*([\d.]+)\s*[°º˚]?\s*C', re.I),
        re.compile(r'\b(?:dried|dry)\s+at\s*([\d.]+)\s*[°º˚]?\s*C', re.I),
        re.compile(r'\b(?:maintained|kept|held)\s+at\s*([\d.]+)\s*[°º˚]?\s*C\s+for\b', re.I),
        re.compile(r'\b(?:reaction|synthesis)\s+(?:temperature|temp)\s*(?:of|was|=|:)\s*([\d.]+)\s*[°º˚]?\s*C', re.I),
        re.compile(r'\b(\d{2,4})\s*[°º˚]?\s*C\s+(?:for|under)\s+\d+\s*h\b', re.I),
    ],
    "time": [
        re.compile(r'\bfor\s+([\d.]+)\s*(h|hr|hrs|hour|hours|min|minutes?)\b', re.I),
        re.compile(r'\b(?:reaction|synthesis|annealing|calcination|pyrolysis|carbonization)\s+(?:time|duration)\s*(?:of|was|=|:)\s*([\d.]+)\s*(h|hr|hrs|hour|hours|min|minutes?)', re.I),
        re.compile(r'\b(?:maintained|kept|held)\s+(?:at|for)\s*[\d.]+\s*°?C\s+(?:for\s+)?([\d.]+)\s*(h|hr|hrs|hour|hours|min|minutes?)', re.I),
        re.compile(r'\bfor\s*([\d.]+)\s*[-–—~to]+\s*([\d.]+)\s*(h|hour|hours|min|minutes?)\b', re.I),
        re.compile(r'\b(?:aged|stirred|incubated|refluxed)\s+for\s*([\d.]+)\s*(h|hr|hrs|hour|hours|min|minutes?)\b', re.I),
        re.compile(r'\bovernight\b', re.I),
    ],
    "pH": [
        re.compile(r'\bpH\s*(?:of|was|=|:|≈|~)\s*([\d.]+)\s*(?:was|in|under|at)\s+the\s+synthesis', re.I),
        re.compile(r'\bsynthesis\s+(?:was\s+)?(?:carried\s+out|performed|conducted)\s+(?:at|under)\s+pH\s*([\d.]+)', re.I),
        re.compile(r'\bpH\s*([\d.]+)\s+(?:was|is)\s+(?:adjusted|maintained)\s+(?:to|at)\s+(?:during|in|for)\s+(?:the\s+)?synthesis', re.I),
        re.compile(r'\b(?:reaction|synthesis)\s+pH\s*(?:of|was|=|:)\s*([\d.]+)', re.I),
    ],
    "solvent": [
        re.compile(r'\b(?:dissolved|dispersed)\s+in\s+([\w\-]+(?:\s[\w\-]+){0,2})\b', re.I),
        re.compile(r'\b(?:using|with|in)\s+([\w\-]+(?:\s[\w\-]+){0,2})\s+as\s+(?:the\s+)?solvent\b', re.I),
        re.compile(r'\bsolvent\s*(?:was|:|=)\s*([\w\-]+(?:\s[\w\-]+){0,2})\b', re.I),
    ],
    "precursors": [
        re.compile(r'\busing\s+([\w\d]+(?:\s*[\(（][^)）]*[\)）])?(?:\s*,\s*[\w\d]+(?:\s*[\(（][^)）]*[\)）])?)*)\s+as\s+(?:the\s+)?(?:precursor|starting\s+material|reactant)', re.I),
        re.compile(r'\b(?:precursor|starting\s+material|reactant)s?:\s*([\w\d]+(?:\s*,\s*[\w\d]+)*)', re.I),
        re.compile(r'\b(?:prepared|synthesized)\s+(?:from|by|with|using)\s+([\w\d\-]+(?:\s*,\s*[\w\d\-]+)*)', re.I),
    ],
}

_TABLE_TYPE_PATTERNS = {
    "kinetics_table": re.compile(r'\bKm\b.*\bVmax\b|\bMichaelis\b|\bkinetic', re.I),
    "sensing_table": re.compile(r'\bLOD\b|\bdetection\s+limit\b|\blinear\s+range\b|\bsensor', re.I),
    "comparison_table": re.compile(r'\bcompar\w+\b|\bvs\.?\b|\bdifferent\s+nanozyme', re.I),
    "recovery_table": re.compile(r'\brecovery\b|\bspiked\b|\bRSD\b', re.I),
    "characterization_table": re.compile(r'\bXRD\b|\bXPS\b|\bBET\b|\bTEM\b|\bSEM\b|\bFTIR\b|\bRaman\b|\bUV.?vis\b|\bXRF\b|\bICP\b|\bEDS\b|\bTGA\b|\bDLS\b|\bXAS\b', re.I),
}

_PREPROCESSOR_TO_SMN_TYPE = {
    "kinetics_parameters": "kinetics_table",
    "sensing_performance": "sensing_table",
    "composition": "characterization_table",
    "material_surface_properties": "characterization_table",
    "electronic_structure": "characterization_table",
    "application_performance": "general_table",
}

_THIS_WORK_RE = re.compile(
    r'\bthis\s+work\b|\bcurrent\s+work\b|\bpresent\s+work\b|\bour\s+(?:nanozyme|catalyst|material|system)\b'
    r'|\bthis\s+study\b|\bpresent\s+study\b|\bcurrent\s+study\b'
    r'|\bas[-\s]?prepared\b|\bas[-\s]?synthesized\b|\bherein\b'
    r'|\bproposed\s+(?:nanozyme|catalyst|material|sensor|system)\b'
    r'|\bnewly\s+(?:synthesized|prepared|developed|designed)\b',
    re.I,
)

_LLM_SYSTEM_PROMPT = """\
You are a nanozyme literature extraction engine. Output ONE JSON object only — no markdown, no comments, no text.

HARD RULES:
1. Only extract explicitly stated data. Use null for missing/uncertain values. Never guess.
2. Extract ONLY ONE main nanozyme — the most important, most complete one.
3. Do NOT extract from comparison tables or references to other work.
4. Distinguish substrate (consumed in reaction: TMB, H2O2, GSH) from analyte (detected: glucose, Hg2+, cancer cells).
5. VLM figure values → important_values only, NOT kinetics.
6. morphology = physical shape (nanoparticle, nanosheet, nanorod, nanosphere, cubic, spherical, core-shell, etc.), NOT figure descriptions.
7. Keep the material name as given in "Selected main nanozyme" — do NOT rename or simplify it.
8. Extract ALL applications mentioned — do not merge or reduce them.
9. For kinetics, extract BOTH Km AND Vmax if both appear. Look carefully for Vmax — it often appears near Km. If multiple substrates have Km/Vmax pairs, list each in kinetics_list.
10. size = numeric value only (e.g. 50), size_unit = unit only (e.g. "nm"). Do NOT combine them.

APPLICATION EXTRACTION — SEMANTIC ROLE DISTINCTION:
You MUST correctly distinguish three semantic roles in nanozyme sensing applications:
- **substrate**: molecule consumed in the catalytic reaction (TMB, ABTS, OPD, H2O2, DCFH-DA)
- **probe molecule**: molecule used as a signal indicator to verify activity or SERS sensitivity (crystal violet/CV, methylene blue/MB, Rhodamine B, R6G). These are NOT target analytes!
- **target_analyte**: the molecule the sensing platform is designed to DETECT (glucose, dopamine, ascorbic acid, Hg2+, cancer cells)

Decision rule: "Is this molecule the REASON for building the sensing platform, or just a TOOL?"
- REASON → target_analyte
- TOOL (signal indicator, probe, calibration agent) → NOT target_analyte

Special case — inhibition-based sensing: if a molecule INHIBITS the catalytic reaction and this inhibition enables detection of that molecule, it IS the target_analyte (e.g., ascorbic acid inhibiting oxidase-like activity → AA is the analyte).

OUTPUT STRUCTURE:
{
  "selected_nanozyme": {
    "name": null, "composition": null,
    "morphology": null, "size": null, "size_unit": null,
    "metal_elements": [],
    "synthesis_method": null,
    "synthesis_conditions": {"temperature": null, "time": null, "precursors": []},
    "crystal_structure": null, "surface_area": null,
    "characterization": []
  },
  "main_activity": {
    "enzyme_like_type": null, "substrates": [],
    "conditions": {"pH": null, "temperature": null},
    "pH_profile": {"optimal_pH": null, "pH_range": null},
    "temperature_profile": {"optimal_temperature": null, "temperature_range": null},
    "kinetics": {
      "Km": null, "Km_unit": null, "Vmax": null, "Vmax_unit": null,
      "kcat": null, "kcat_unit": null, "kcat_Km": null, "kcat_Km_unit": null,
      "substrate": null, "source": null, "needs_review": false
    },
    "kinetics_list": [
      {"Km": null, "Km_unit": null, "Vmax": null, "Vmax_unit": null, "substrate": null, "source": null}
    ],
    "mechanism": null
  },
  "applications": [
    {"application_type": null, "target_analyte": null, "method": null,
     "linear_range": null, "detection_limit": null, "sample_type": null, "notes": null}
  ],
  "important_values": [
    {"name": null, "value": null, "unit": null, "context": null, "source": null, "needs_review": false}
  ]
}

KEY EXTRACTION RULES:
- Kinetics: Extract BOTH Km AND Vmax. source="text"|"table". Look for: "Km = X mM", "Km(TMB) = X", "Vmax = X M/s", "Vmax = X mM/s", "kcat = X s⁻¹", "kcat/Km = X M⁻¹s⁻¹". Vmax often appears as: "Vmax = 30×10⁻⁸ M·s⁻¹", "Vmax = 25.7 mM·s⁻¹", "maximum velocity", "Vmax(TMB)". If multiple substrates, pick primary (TMB/H2O2).
- Synthesis: method name + conditions (temp/time/precursors). Common: hydrothermal, solvothermal, co-precipitation, sol-gel, calcination, pyrolysis, CVD, self-assembly, carbonization, stripping, electrospinning, NaBH4 reduction.
- pH_profile: optimal_pH = pH at maximum activity. pH_range = active range (e.g. "3-7"). Look for "optimal pH", "pH optimum", "maximum activity at pH X", "pH-dependent activity".
- Temperature_profile: optimal_temperature = temp at maximum activity. temperature_range = active range. Look for "optimal temperature", "maximum activity at X°C".
- Size: size = number only, size_unit = unit. crystal_structure = phase (spinel/perovskite/amorphous/graphitic). surface_area = BET value.
- Morphology: ONLY physical shape words (cubic, spherical, nanosheet, nanorod, core-shell, etc.). NOT figure captions or descriptions.
- Applications: Extract EACH distinct application separately. target_analyte ≠ substrate. If none, output [].
- Important values: capture key numbers not fitting elsewhere (e.g. specific activity, photothermal conversion efficiency, laser wavelength). If none, output []."""

_LLM_USER_TEMPLATE = """\
Selected main nanozyme material: {selected_material}

Evidence buckets for this material:

[MATERIAL EVIDENCE]
{material_evidence}

[SYNTHESIS EVIDENCE]
{synthesis_evidence}

[CHARACTERIZATION EVIDENCE]
{characterization_evidence}

[ACTIVITY EVIDENCE]
{activity_evidence}

[KINETICS EVIDENCE]
{kinetics_evidence}

[APPLICATION EVIDENCE]
{application_evidence}

[MECHANISM EVIDENCE]
{mechanism_evidence}

[RELEVANT TABLE SUMMARIES]
{table_summaries}

[RELEVANT FIGURE SUMMARIES]
{figure_summaries}

Based on the selected material and evidence above, fill the JSON schema. Remember:
- Only extract ONE main nanozyme
- Do not guess missing fields — use null
- Distinguish substrate from analyte
- VLM figure values go to important_values only, NOT kinetics
- application_type must be one of: "sensing", "therapeutic", "antibacterial", "environmental", "antioxidant", "biofilm_inhibition", "other"
- Output only JSON, no markdown"""


class SMNConfig:
    def __init__(self, **kwargs):
        self.extraction_mode = kwargs.get("extraction_mode", EXTRACTION_MODE)
        self.enable_llm = kwargs.get("enable_llm", True)
        self.enable_vlm = kwargs.get("enable_vlm", True)
        self.max_evidence_sentences_per_bucket = kwargs.get("max_evidence_sentences_per_bucket", 20)
        self.material_candidate_top_k = kwargs.get("material_candidate_top_k", 5)
        self.allow_supplementary_full_record = kwargs.get("allow_supplementary_full_record", False)
        self.numeric_validation_strict = kwargs.get("numeric_validation_strict", True)
        self.figure_values_to_important_values = kwargs.get("figure_values_to_important_values", True)
        self.output_schema_version = kwargs.get("output_schema_version", SCHEMA_VERSION)
        self.enable_llm_refinement = kwargs.get("enable_llm_refinement", True)
        self.llm_refinement_max_iterations = kwargs.get("llm_refinement_max_iterations", 3)
        self.enable_agentic_guard = kwargs.get("enable_agentic_guard", True)
        self.enable_llm_conflict_resolution = kwargs.get("enable_llm_conflict_resolution", True)

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "SMNConfig":
        if not d:
            return cls()
        smn = d.get("single_main_nanozyme", d)
        return cls(**smn)


def make_empty_record() -> Dict[str, Any]:
    return deepcopy(EMPTY_RECORD)


_VALID_ENZYME_TYPES = frozenset({
    "peroxidase-like", "oxidase-like", "catalase-like",
    "superoxide-dismutase-like", "superoxide dismutase-like", "SOD-like",
    "glutathione-peroxidase-like", "glutathione peroxidase-like", "GPx-like",
    "haloperoxidase-like", "nitric-oxide-synthase-like",
    "laccase-like", "tyrosinase-like",
    "phosphatase-like", "nitroreductase-like", "hydrolase-like",
    "esterase-like", "glucose-oxidase-like", "nuclease-like",
    "glutathione-oxidase-like", "cascade-enzymatic",
})


def validate_schema(record: Dict[str, Any]) -> Dict[str, Any]:
    warnings = record.get("diagnostics", {}).get("warnings", [])
    auto_fixed = False

    for top_key in EMPTY_RECORD:
        if top_key not in record:
            record[top_key] = deepcopy(EMPTY_RECORD[top_key])
            auto_fixed = True

    for field in FORBIDDEN_OLD_FIELDS:
        if field in record:
            del record[field]
            auto_fixed = True

    def _clean_dict(d: Dict) -> None:
        nonlocal auto_fixed
        if not isinstance(d, dict):
            return
        for k in list(d.keys()):
            if k in FORBIDDEN_OLD_FIELDS:
                del d[k]
                auto_fixed = True

    for sub in record.values():
        if isinstance(sub, dict):
            _clean_dict(sub)
            for nested in sub.values():
                if isinstance(nested, dict):
                    _clean_dict(nested)
        elif isinstance(sub, list):
            for item in sub:
                if isinstance(item, dict):
                    _clean_dict(item)

    kinetics = record.get("main_activity", {}).get("kinetics", {})
    for k in _KINETICS_KEYS:
        if k not in kinetics:
            kinetics[k] = None if k != "needs_review" else False
            auto_fixed = True

    conditions = record.get("main_activity", {}).get("conditions", {})
    for k in _CONDITIONS_KEYS:
        if k not in conditions:
            conditions[k] = None
            auto_fixed = True

    ph_profile = record.get("main_activity", {}).get("pH_profile", {})
    if not isinstance(ph_profile, dict):
        ph_profile = {}
        record["main_activity"]["pH_profile"] = ph_profile
        auto_fixed = True
    for k in _PH_PROFILE_KEYS:
        if k not in ph_profile:
            ph_profile[k] = None
            auto_fixed = True

    temp_profile = record.get("main_activity", {}).get("temperature_profile", {})
    if not isinstance(temp_profile, dict):
        temp_profile = {}
        record["main_activity"]["temperature_profile"] = temp_profile
        auto_fixed = True
    for k in _TEMP_PROFILE_KEYS:
        if k not in temp_profile:
            temp_profile[k] = None
            auto_fixed = True

    synth_cond = record.get("selected_nanozyme", {}).get("synthesis_conditions", {})
    if not isinstance(synth_cond, dict):
        synth_cond = {}
        record["selected_nanozyme"]["synthesis_conditions"] = synth_cond
        auto_fixed = True
    for k in _SYNTHESIS_COND_KEYS:
        if k not in synth_cond:
            synth_cond[k] = [] if k == "precursors" else None
            auto_fixed = True

    sel_nano = record.get("selected_nanozyme", {})
    for new_key in ("size_unit", "crystal_structure", "surface_area"):
        if new_key not in sel_nano:
            sel_nano[new_key] = None
            auto_fixed = True

    rst = record.get("raw_supporting_text", {})
    for k in _RST_KEYS:
        if k not in rst:
            rst[k] = []
            auto_fixed = True
        elif not isinstance(rst[k], list):
            rst[k] = []
            auto_fixed = True

    diag = record.get("diagnostics", {})
    if diag.get("status") not in _VALID_STATUSES:
        diag["status"] = "partial"
        auto_fixed = True
    if diag.get("confidence") not in _VALID_CONFIDENCES:
        diag["confidence"] = "low"
        auto_fixed = True
    if not isinstance(record.get("applications"), list):
        record["applications"] = []
        auto_fixed = True
    if not isinstance(record.get("important_values"), list):
        record["important_values"] = []
        auto_fixed = True

    etype_raw = record.get("main_activity", {}).get("enzyme_like_type")
    if etype_raw and isinstance(etype_raw, str):
        try:
            from nanozyme_models import EnzymeType
            canonical = EnzymeType.normalize_canonical(etype_raw)
            valid_values = {e.value for e in EnzymeType}
            if canonical not in valid_values and canonical == etype_raw:
                if "unknown_enzyme_type" not in warnings:
                    warnings.append(f"unknown_enzyme_type: {etype_raw}")
        except ImportError:
            pass

    for app in record.get("applications", []):
        if not isinstance(app, dict):
            continue
        atype = app.get("application_type")
        if atype and isinstance(atype, str):
            try:
                from nanozyme_models import ApplicationType
                canonical = ApplicationType.normalize_canonical(atype)
                valid_values = {e.value for e in ApplicationType}
                if canonical not in valid_values and canonical == atype:
                    if "unknown_application_type" not in warnings:
                        warnings.append(f"unknown_application_type: {atype}")
            except ImportError:
                pass

    act = record.get("main_activity", {})
    if not isinstance(act.get("kinetics_list"), list):
        act["kinetics_list"] = []
        auto_fixed = True

    if auto_fixed and "schema_auto_fixed" not in warnings:
        warnings.append("schema_auto_fixed")
    diag["warnings"] = warnings
    record["diagnostics"] = diag

    if _normalize_unit_fn:
        kinetics = record.get("main_activity", {}).get("kinetics", {})
        for ukey in ("Km_unit", "Vmax_unit", "kcat_unit", "kcat_Km_unit"):
            raw_u = kinetics.get(ukey)
            if raw_u and isinstance(raw_u, str):
                normed = _normalize_unit_fn(raw_u)
                if normed != raw_u:
                    kinetics[ukey] = normed
        sel_nano = record.get("selected_nanozyme", {})
        for ukey in ("size_unit",):
            raw_u = sel_nano.get(ukey)
            if raw_u and isinstance(raw_u, str):
                normed = _normalize_unit_fn(raw_u)
                if normed != raw_u:
                    sel_nano[ukey] = normed

        for app in record.get("applications", []):
            if not isinstance(app, dict):
                continue
            for ukey in ("detection_limit_unit", "linear_range_unit"):
                raw_u = app.get(ukey)
                if raw_u and isinstance(raw_u, str):
                    normed = _normalize_unit_fn(raw_u)
                    if normed != raw_u:
                        app[ukey] = normed

        for ukey in ("Km_unit", "Vmax_unit", "kcat_unit", "kcat_Km_unit"):
            raw_u = kinetics.get(ukey)
            if raw_u and isinstance(raw_u, str):
                if _RE_X10_UNIT.match(raw_u):
                    val = kinetics.get(ukey.replace("_unit", ""))
                    if val is not None and isinstance(val, (int, float)):
                        exp_m = _RE_EXP_DIGITS.search(raw_u)
                        if exp_m:
                            exp = int(exp_m.group(0).replace('−', '-').replace('–', '-'))
                            kinetics[ukey.replace("_unit", "")] = val * (10 ** exp)
                            kinetics[ukey] = None

    etype = record.get("main_activity", {}).get("enzyme_like_type")
    _FINAL_APP_TYPE_NORMALIZE = {
        "detection": "sensing",
        "colorimetric detection": "sensing",
        "biosensing": "sensing",
        "determination": "sensing",
        "monitoring": "sensing",
        "assay": "sensing",
        "diagnostic": "sensing",
        "diagnosis": "sensing",
        "imaging": "sensing",
        "therapy": "therapeutic",
        "antitumor": "therapeutic",
    }
    for app in record.get("applications", []):
        if isinstance(app, dict) and app.get("application_type"):
            atype = app["application_type"].strip().lower()
            canonical = _FINAL_APP_TYPE_NORMALIZE.get(atype)
            if canonical:
                app["application_type"] = canonical

    if etype and isinstance(etype, str):
        etype_lower = etype.lower().strip()
        matched = False
        for valid in _VALID_ENZYME_TYPES:
            if valid.lower() == etype_lower or etype_lower in valid.lower():
                matched = True
                break
        if not matched:
            warnings.append(f"unknown_enzyme_type: {etype}")

    sel_name = record.get("selected_nanozyme", {}).get("name")
    if sel_name and isinstance(sel_name, str):
        _NAME_SUBSTRATE_PATTERN = re.compile(
            r'\s*/\s*(?:H2O2|H₂O₂|TMB|ABTS|OPD|L-ascorbic|glucose|DA|H2O|NADH)',
            re.I
        )
        _NAME_SYSTEM_SUFFIX = re.compile(
            r'\s+(?:system|solution|mixture|reaction|catalyst|composite\s+system)$',
            re.I
        )
        cleaned = sel_name
        sub_match = _NAME_SUBSTRATE_PATTERN.search(cleaned)
        if sub_match:
            cleaned = cleaned[:sub_match.start()].strip()
            warnings.append(f"name_cleaned_substrate_removed: '{sel_name}' -> '{cleaned}'")
        sys_match = _NAME_SYSTEM_SUFFIX.search(cleaned)
        if sys_match:
            cleaned = cleaned[:sys_match.start()].strip()
            warnings.append(f"name_cleaned_system_suffix_removed: '{sel_name}' -> '{cleaned}'")
        if cleaned != sel_name and cleaned:
            record["selected_nanozyme"]["name"] = cleaned

    for app in record.get("applications", []):
        if not isinstance(app, dict):
            continue
        if not app.get("application_type"):
            warnings.append("application_missing_type")
            app["application_type"] = "other"

    valid_apps = []
    for app in record.get("applications", []):
        if isinstance(app, dict) and app.get("application_type"):
            valid_apps.append(app)
    record["applications"] = valid_apps

    for iv in record.get("important_values", []):
        if not isinstance(iv, dict):
            continue
        if not iv.get("name") or iv.get("value") is None:
            warnings.append("important_value_missing_name_or_value")

    _NUMERIC_SCHEMA_FIELDS = [
        ("main_activity", "kinetics", "Km"),
        ("main_activity", "kinetics", "Vmax"),
        ("main_activity", "kinetics", "kcat"),
        ("main_activity", "kinetics", "kcat_Km"),
        ("main_activity", "conditions", "pH"),
        ("main_activity", "conditions", "temperature"),
        ("main_activity", "pH_profile", "optimal_pH"),
        ("main_activity", "temperature_profile", "optimal_temperature"),
        ("selected_nanozyme", "size"),
    ]
    for path in _NUMERIC_SCHEMA_FIELDS:
        if len(path) == 3:
            val = record.get(path[0], {}).get(path[1], {}).get(path[2])
        else:
            val = record.get(path[0], {}).get(path[1])
        if val is not None and isinstance(val, str):
            try:
                float_val = float(val)
                if len(path) == 3:
                    record[path[0]][path[1]][path[2]] = float_val
                else:
                    record[path[0]][path[1]] = float_val
                auto_fixed = True
            except ValueError:
                pass

    return record


class PreprocessedDocument:
    _SENTENCE_TAG_RE = re.compile(r'\[S\d{4}\|')
    _MAX_CHUNK_CHARS = 3000

    def __init__(self, mid_json: Dict[str, Any]):
        self._raw = mid_json
        self.metadata = mid_json.get("metadata", {})
        raw_chunks = mid_json.get("llm_task", {}).get("chunks", [])
        self.chunks = self._split_oversized_chunks(raw_chunks)
        self.chunk_contexts = mid_json.get("llm_task", {}).get("chunk_contexts", [])
        if len(self.chunk_contexts) < len(self.chunks):
            self.chunk_contexts.extend([{}] * (len(self.chunks) - len(self.chunk_contexts)))
        self.vlm_tasks = mid_json.get("vlm_tasks", [])
        self.hints = mid_json.get("extracted_hints", {})
        self.table_task = mid_json.get("table_extraction_task", {})

    def _split_oversized_chunks(self, chunks: List[str]) -> List[str]:
        if not chunks:
            return chunks
        result = []
        for chunk in chunks:
            if len(chunk) <= self._MAX_CHUNK_CHARS:
                result.append(chunk)
                continue
            if not self._SENTENCE_TAG_RE.search(chunk):
                sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', chunk) if s.strip()]
            else:
                parts = re.split(r'(?=\[S\d{4}\|)', chunk)
                sentences = [p.strip() for p in parts if p.strip()]
            if len(sentences) <= 1:
                result.append(chunk)
                continue
            current = ""
            for s in sentences:
                if current and len(current) + len(s) + 1 > self._MAX_CHUNK_CHARS:
                    result.append(current)
                    current = s
                else:
                    current = current + "\n" + s if current else s
            if current:
                result.append(current)
        if len(result) > len(chunks):
            logger.info(f"[SMN] Split {len(chunks)} oversized chunks into {len(result)} chunks")
        return result

    @property
    def parse_status(self) -> str:
        return self.metadata.get("parse_status", "unknown")

    @property
    def source_file(self) -> str:
        return self.metadata.get("source_file", "")

    @property
    def document_kind(self) -> str:
        return self.metadata.get("document_kind", "unknown")

    def to_preprocessed_output(self) -> Dict[str, Any]:
        return {
            "paper_metadata": self.metadata,
            "sentences": self.chunks,
            "captions": [t.get("caption", "") for t in self.vlm_tasks if t.get("caption")],
            "tables": self.table_task.get("tables", []),
            "figures": self.vlm_tasks,
            "candidate_materials": [],
            "evidence_buckets": {
                "material": [], "activity": [], "kinetics": [],
                "application": [], "synthesis": [], "characterization": [], "mechanism": [],
            },
            "diagnostics": {},
        }


class PaperMetadataExtractor:
    _DOI_RE = re.compile(r'\b10\.\d{4,9}/[^\s\]"\',;>]+')
    _YEAR_RE = re.compile(r'\b(19|20)\d{2}\b')
    _CITE_THIS_RE = re.compile(r'(?i)\bcite\s+this\b|\bcite\b.*?(?:article|paper|as)\b')
    _JOURNAL_META_RE = re.compile(r'(?i)\b(?:received|accepted|published|available\s+online|doi|vol\.|pp\.|pages)\b')
    _AFFILIATION_RE = re.compile(r'(?i)\b(?:department|college|university|institute|laboratory|school\s+of|faculty\s+of)\b')

    def extract(self, doc: PreprocessedDocument) -> Dict[str, Any]:
        meta = doc.metadata
        title = meta.get("title") or ""
        if not title and doc.chunks:
            title = self._extract_title(doc.chunks)

        authors = meta.get("author") or meta.get("authors") or ""
        if not authors and doc.chunks:
            authors = self._extract_authors(doc.chunks)

        doi = meta.get("doi") or ""
        if not doi:
            doi = self._extract_doi(doc.chunks)

        year = meta.get("year") or ""
        if not year:
            year = self._extract_year(doc.chunks)
        if isinstance(year, str) and year:
            try:
                year = int(year)
            except (ValueError, TypeError):
                year = None

        return {
            "title": title or None,
            "authors": authors or None,
            "journal": meta.get("journal") or None,
            "year": year or None,
            "doi": doi or None,
            "source_file": meta.get("source_file") or meta.get("file_name") or None,
            "document_kind": meta.get("document_kind") or "unknown",
        }

    def _extract_title(self, chunks: List[str]) -> str:
        if not chunks:
            return ""
        for line in chunks[0].strip().split("\n")[:5]:
            line = line.strip()
            if line and not line.startswith("[Hint:") and len(line) > 15 and not self._CITE_THIS_RE.search(line):
                return line
        return ""

    def _extract_authors(self, chunks: List[str]) -> str:
        if not chunks:
            return ""
        for line in chunks[0].strip().split("\n")[1:8]:
            line = line.strip()
            if not line or line.startswith("[Hint:"):
                continue
            if self._CITE_THIS_RE.search(line) or self._JOURNAL_META_RE.search(line) or self._AFFILIATION_RE.search(line):
                continue
            if 8 < len(line) < 300 and ("," in line or " and " in line.lower()) and _RE_UPPER_WORD.search(line):
                return line
        return ""

    def _extract_doi(self, chunks: List[str]) -> str:
        for chunk in chunks[:2]:
            m = self._DOI_RE.search(chunk)
            if m:
                return m.group(0).rstrip(".")
        return ""

    def _extract_year(self, chunks: List[str]) -> str:
        for chunk in chunks[:2]:
            for y in self._YEAR_RE.findall(chunk):
                if 1950 <= int(y) <= 2030:
                    return y
        return ""


class CandidateRecaller:
    _OCR_FIXES = [
        (re.compile(r'Fee(?=[A-Z])'), 'Fe'),
        (re.compile(r'Coo(?=[A-Z\d])'), 'Co'),
        (re.compile(r'Nii(?=[A-Z\d])'), 'Ni'),
        (re.compile(r'Mnn(?=[A-Z\d])'), 'Mn'),
        (re.compile(r'Cuu(?=[A-Z\d])'), 'Cu'),
        (re.compile(r'Znn(?=[A-Z\d])'), 'Zn'),
        (re.compile(r'Auu(?=[A-Z\d])'), 'Au'),
        (re.compile(r'Ptt(?=[A-Z\d])'), 'Pt'),
        (re.compile(r'Pdd(?=[A-Z\d])'), 'Pd'),
        (re.compile(r'O(?=\d)'), 'O'),
        (re.compile(r'(?<=[A-Z])e(?=[A-Z][a-z])'), ''),
        (re.compile(r'(?<=[A-Z])NeC\b'), 'N-C'),
        (re.compile(r'(?<=[A-Z])SaC\b'), 'S-C'),
        (re.compile(r'(?<=[A-Z])CaC\b'), 'C-C'),
        (re.compile(r'FeBNC'), 'FeBNC'),
        (re.compile(r'(?<=[A-Z])BNC'), 'BNC'),
        (re.compile(r'Cee(?=[A-Z])', re.I), 'Ce'),
        (re.compile(r'Agg(?=[A-Z\d])', re.I), 'Ag'),
        (re.compile(r'Tii(?=[A-Z\d])', re.I), 'Ti'),
        (re.compile(r'Vv(?=[A-Z\d])', re.I), 'V'),
        (re.compile(r'Crr(?=[A-Z\d])', re.I), 'Cr'),
        (re.compile(r'Moo(?=[A-Z\d])', re.I), 'Mo'),
        (re.compile(r'Ww(?=[A-Z\d])', re.I), 'W'),
        (re.compile(r'Ruu(?=[A-Z\d])', re.I), 'Ru'),
        (re.compile(r'Rhh(?=[A-Z\d])', re.I), 'Rh'),
        (re.compile(r'Irr(?=[A-Z\d])', re.I), 'Ir'),
        (re.compile(r'Laa(?=[A-Z\d])', re.I), 'La'),
        (re.compile(r'Zrr(?=[A-Z\d])', re.I), 'Zr'),
        (re.compile(r'All(?=[A-Z\d])', re.I), 'Al'),
        (re.compile(r'Snn(?=[A-Z\d])', re.I), 'Sn'),
        (re.compile(r'Bii(?=[A-Z\d])', re.I), 'Bi'),
        (re.compile(r'Inn(?=[A-Z\d])', re.I), 'In'),
        (re.compile(r'0(?=[A-Z][a-z])'), 'O'),
        (re.compile(r'(?<=[A-Z])0(?=[a-z])'), 'O'),
    ]

    _OCR_COMPOUND_FIXES = [
        (re.compile(r'(\w)e([A-Z])C\b'), r'\1-\2-C'),
        (re.compile(r'(\w)e([A-Z])N\b'), r'\1-\2-N'),
        (re.compile(r'(\w)Ne([A-Z])\b'), r'\1-N-\2'),
        (re.compile(r'([A-Z][a-z]?)e([A-Z][a-z]?)e([A-Z])C\b'), r'\1-\2-\3-C'),
        (re.compile(r'([A-Z][a-z]?)e([A-Z][a-z]?)e([A-Z])N\b'), r'\1-\2-\3-N'),
        (re.compile(r'CuFe'), 'Cu-Fe'),
        (re.compile(r'FeCu'), 'Fe-Cu'),
        (re.compile(r'CoFe'), 'Co-Fe'),
        (re.compile(r'FeCo'), 'Fe-Co'),
        (re.compile(r'NiFe'), 'Ni-Fe'),
        (re.compile(r'FeNi'), 'Fe-Ni'),
        (re.compile(r'MnFe'), 'Mn-Fe'),
        (re.compile(r'FeMn'), 'Fe-Mn'),
        (re.compile(r'CuCo'), 'Cu-Co'),
        (re.compile(r'CoCu'), 'Co-Cu'),
        (re.compile(r'ZrO'), 'Zr-O'),
    ]

    def __init__(self, top_k: int = 5):
        self.top_k = top_k

    def _fix_ocr_name(self, name: str) -> str:
        if not name:
            return name
        fixed = name
        for pat, repl in self._OCR_FIXES:
            fixed = pat.sub(repl, fixed)
        for pat, repl in self._OCR_COMPOUND_FIXES:
            prev = fixed
            fixed = pat.sub(repl, fixed)
            if fixed == prev:
                break
        if fixed != name:
            logger.debug(f"[SMN] OCR fix: '{name}' -> '{fixed}'")
        return fixed

    def recall(self, doc: PreprocessedDocument) -> List[Dict[str, Any]]:
        candidates: Dict[str, Dict[str, Any]] = {}

        title = doc.metadata.get("title", "")
        if title:
            self._extract_material_names(title, "title", candidates)
            title_candidates = self._extract_title_material(title)
            for tc in title_candidates:
                if self._is_valid_candidate(tc):
                    candidates.setdefault(tc, {"name": tc, "sources": set(), "evidence": []})
                    candidates[tc]["sources"].add("title")
                    candidates[tc]["evidence"].append(f"[title] {title}")

        for chunk in doc.chunks:
            lower = chunk.lower()[:200]
            if "abstract" in lower:
                self._extract_material_names(chunk[:2000], "abstract", candidates)
                break

        for mention in doc.hints.get("candidate_system_mentions", []):
            cleaned = self._clean_candidate_name(mention)
            if cleaned and self._is_valid_candidate(cleaned):
                candidates.setdefault(cleaned, {"name": cleaned, "sources": set(), "evidence": []})
                candidates[cleaned]["sources"].add("hints_system")
                candidates[cleaned]["evidence"].append(mention)

        for mention in doc.hints.get("candidate_enzyme_mentions", []):
            cleaned = self._clean_candidate_name(mention)
            if cleaned and self._is_valid_candidate(cleaned):
                candidates.setdefault(cleaned, {"name": cleaned, "sources": set(), "evidence": []})
                candidates[cleaned]["sources"].add("hints_enzyme")

        for idx, chunk in enumerate(doc.chunks):
            ctx = doc.chunk_contexts[idx] if idx < len(doc.chunk_contexts) else {}
            section = self._infer_section(ctx, chunk)
            self._extract_material_names(chunk, section, candidates)

        for vlm_task in doc.vlm_tasks:
            caption = vlm_task.get("caption", "")
            if caption:
                self._extract_material_names(caption, "characterization_caption", candidates)

        compound_subcandidates: Dict[str, Dict[str, Any]] = {}
        for name, info in list(candidates.items()):
            subparts = self._split_compound_name(name)
            for sub in subparts:
                if sub == name:
                    continue
                if not self._is_valid_candidate(sub):
                    continue
                compound_subcandidates.setdefault(sub, {"name": sub, "sources": set(), "evidence": []})
                compound_subcandidates[sub]["sources"] |= info["sources"]
                compound_subcandidates[sub]["evidence"].extend(info.get("evidence", []))
        for sub_name, sub_info in compound_subcandidates.items():
            if sub_name in candidates:
                candidates[sub_name]["sources"] |= sub_info["sources"]
                candidates[sub_name]["evidence"].extend(sub_info["evidence"])
            else:
                candidates[sub_name] = sub_info

        deduped = self._deduplicate(candidates)
        return deduped[:self.top_k] if self.top_k > 0 else deduped

    def _extract_title_material(self, title: str) -> List[str]:
        results = []
        for m in _MATERIAL_PATTERN_RE.finditer(title):
            name = m.group(0).strip()
            name = self._fix_ocr_name(name)
            if self._is_valid_candidate(name):
                results.append(name)
        for m in _COMPOSITE_PATTERN_RE.finditer(title):
            name = m.group(0).strip()
            if self._is_valid_candidate(name):
                results.append(name)
        for m in re.finditer(r'\b(?:MIL|UiO|HKUST|PCN|NU|NOTT|DUT|MOF|COF|ZIF)[-\s]?\d+(?:\([A-Z][a-z]?(?:[A-Z][a-z]?\d*)*\))?\b', title, re.I):
            name = m.group(0).strip()
            if self._is_valid_candidate(name):
                results.append(name)
        for m in re.finditer(
            r'\b(?:Fe|Co|Ni|Mn|Cu|Zn|Ce|Au|Ag|Pt|Pd|Ti|V|Cr|Mo|W|Ru|Rh|Ir|La|Zr|Al|Sn|Bi|In|Ga|Ge|Sb|Te|Hf|Ta|Re|Os|Y|Sc|Cd|Hg|Tl|Pb|Nb)'
            r'-(?:[A-Z][a-z]*-?)+(?=\s|$|[^A-Za-z0-9-])',
            title,
        ):
            name = m.group(0).strip()
            if self._is_valid_candidate(name):
                results.append(name)
        for m in re.finditer(
            r'\b\w+@\w+(?:/\w+)?\b',
            title,
        ):
            name = m.group(0).strip()
            if self._is_valid_candidate(name):
                results.append(name)
        for m in re.finditer(
            r'\b(?:Fe|Co|Ni|Mn|Cu|Zn|Ce|Au|Ag|Pt|Pd|Ti|V|Cr|Mo|W|Ru|Rh|Ir|La|Zr|Al|Sn|Bi|In|Ga|Ge|Sb|Te|Hf|Ta|Re|Os|Y|Sc|Cd|Hg|Tl|Pb|Nb)\d*[-/]?(?:SA|SAN|SAC|SAzyme|SAEs)\b',
            title, re.I,
        ):
            name = m.group(0).strip()
            if self._is_valid_candidate(name):
                results.append(name)
        for m in re.finditer(
            r'\b(?:Fe|Co|Ni|Mn|Cu|Zn|Ce|Au|Ag|Pt|Pd|Ti|V|Cr|Mo|W|Ru|Rh|Ir|La|Zr|Al|Sn|Bi|In|Ga|Ge|Sb|Te|Hf|Ta|Re|Os|Y|Sc|Cd|Hg|Tl|Pb|Nb)\d*\s+Single[-\s]?Atom\b',
            title, re.I,
        ):
            raw = m.group(0).strip()
            metal_m = re.match(r'([A-Z][a-z]?\d*)', raw)
            if metal_m:
                sa_name = f"{metal_m.group(1)}-SAN"
                if self._is_valid_candidate(sa_name):
                    results.append(sa_name)
                if self._is_valid_candidate(raw):
                    results.append(raw)
                ldh_m = re.search(r'(\w+[- ]?(?:LDH|LDHs))\s+Supported', title, re.I)
                if ldh_m:
                    ldh_name = ldh_m.group(1).strip()
                    combined = f"{metal_m.group(1)}/{ldh_name}"
                    if self._is_valid_candidate(combined):
                        results.append(combined)
        for m in re.finditer(
            r'\b(?:Fe|Co|Ni|Mn|Cu|Zn|Ce|Au|Ag|Pt|Pd|Ti|V|Cr|Mo|W|Ru|Rh|Ir|La|Zr|Al|Sn|Bi|In|Ga|Ge|Sb|Te|Hf|Ta|Re|Os|Y|Sc|Cd|Hg|Tl|Pb|Nb)\d*/(?:LDH|LDHs|MOF|COF|ZIF)\b',
            title, re.I,
        ):
            name = m.group(0).strip()
            if self._is_valid_candidate(name):
                results.append(name)
        for m in re.finditer(
            r'\b\w+-doped\s+\w+\s+\w+\b',
            title, re.I,
        ):
            name = m.group(0).strip()
            if self._is_valid_candidate(name):
                results.append(name)
        for mw in _MORPHOLOGY_WORDS:
            idx = title.lower().find(mw)
            if idx >= 0:
                prefix = title[:idx].strip()
                for m in _MATERIAL_PATTERN_RE.finditer(prefix[-40:]):
                    name = m.group(0).strip()
                    if self._is_valid_candidate(name):
                        results.append(name)
        return list(dict.fromkeys(results))

    def _clean_candidate_name(self, name: str) -> Optional[str]:
        if not name:
            return None
        cleaned = name.strip()
        cleaned = self._fix_ocr_name(cleaned)
        for _ in range(3):
            prev = cleaned
            cleaned = _LEADING_JUNK_RE.sub("", cleaned).strip()
            cleaned = _RE_COMPOSITE_SEP.sub("", cleaned).strip()
            cleaned = _RE_LEADING_DIGITS.sub("", cleaned).strip()
            if cleaned == prev:
                break
        m = _MATERIAL_PATTERN_RE.search(cleaned)
        _SA_PATTERN = re.compile(r'(?:Single[-\s]?Atom|SA[NCE]?|SAzyme)', re.I)
        if _SA_PATTERN.search(cleaned):
            pass
        elif len(cleaned) > 60:
            if m:
                core = m.group(0).strip()
                if self._is_valid_candidate(core):
                    cleaned = core
        if len(cleaned) > 40 and not _SA_PATTERN.search(cleaned):
            if m:
                cleaned = m.group(0).strip()
            else:
                return None
        if not self._is_valid_candidate(cleaned):
            return None
        return cleaned

    def _infer_section(self, ctx: Dict, chunk: str) -> str:
        cl = chunk.lower()[:500]
        if any(kw in cl for kw in ["synthesis", "preparation", "fabrication", "synthesized"]):
            return "synthesis"
        if any(kw in cl for kw in ["characteriz", "sem ", "tem ", "xrd", "xps", "raman", "ftir"]):
            return "characterization"
        if any(kw in cl for kw in ["peroxidase-like", "oxidase-like", "catalase-like", "enzyme-like", "catalytic activity"]):
            return "activity"
        if any(kw in cl for kw in ["michaelis", "kinetic", "km ", "vmax", "lineweaver"]):
            return "kinetics"
        if any(kw in cl for kw in ["detection", "sensing", "sensor", "lod", "linear range"]):
            return "application"
        if any(kw in cl for kw in ["conclusion", "conclud", "summary"]):
            return "conclusion"
        if any(kw in cl for kw in ["introduction", "background", "prior work"]):
            return "introduction"
        return "unknown"

    def _extract_material_names(self, text: str, section: str, candidates: Dict[str, Dict[str, Any]]):
        for m in _MATERIAL_PATTERN_RE.finditer(text):
            name = m.group(0).strip()
            name = self._fix_ocr_name(name)
            if self._is_valid_candidate(name):
                candidates.setdefault(name, {"name": name, "sources": set(), "evidence": []})
                candidates[name]["sources"].add(section)
                candidates[name]["evidence"].append(text[max(0, m.start()-40):m.end()+40])

        for m in re.finditer(
            r'\b[A-Z][a-z]?\d*(?:[- ][A-Z][a-z]?\d*)*(?:[- ]?(?:LDH|LDHs|MOF|COF|ZIF|SAN|SAC|SAzyme)\b)?'
            r'(?:@[A-Z][a-z]?\d*(?:[- ][A-Z][a-z]?\d*)*(?:[- ]?(?:LDH|LDHs|MOF|COF|ZIF|SAN|SAC|SAzyme)\b)?)+',
            text, re.I,
        ):
            name = m.group(0).strip()
            if len(name) >= 5 and self._is_valid_candidate(name):
                candidates.setdefault(name, {"name": name, "sources": set(), "evidence": []})
                candidates[name]["sources"].add(section)
                candidates[name]["evidence"].append(text[max(0, m.start()-40):m.end()+40])

        for word in _MORPHOLOGY_WORDS:
            idx = text.lower().find(word)
            if idx >= 0:
                ctx = text[max(0, idx-30):idx+len(word)+30]
                for mm in _MATERIAL_PATTERN_RE.finditer(ctx[:30]):
                    name = mm.group(0).strip()
                    if self._is_valid_candidate(name):
                        candidates.setdefault(name, {"name": name, "sources": set(), "evidence": []})
                        candidates[name]["sources"].add(section)
                        candidates[name]["evidence"].append(ctx)

        for m in re.finditer(
            r'\b(?:MIL|UiO|HKUST|PCN|NU|NOTT|DUT|MOF|COF|ZIF|ZIF-L|BIF|CPO|FMOF|SOF|HOF)[-\s]?\d+(?:\([A-Z][a-z]?(?:[A-Z][a-z]?\d*)*\))?\b',
            text, re.I,
        ):
            name = m.group(0).strip()
            if self._is_valid_candidate(name):
                candidates.setdefault(name, {"name": name, "sources": set(), "evidence": []})
                candidates[name]["sources"].add(section)
                candidates[name]["evidence"].append(text[max(0, m.start()-40):m.end()+40])

        for m in re.finditer(
            r'\b(?:Fe|Co|Ni|Mn|Cu|Zn|Ce|Au|Ag|Pt|Pd|Ti|V|Cr|Mo|W|Ru|Rh|Ir|La|Zr|Al|Sn|Bi|In|Ga|Ge|Sb|Te|Hf|Ta|Re|Os|Y|Sc|Cd|Hg|Tl|Pb|Nb)\d*\s+Single[-\s]?Atom\b',
            text, re.I,
        ):
            name = m.group(0).strip()
            if self._is_valid_candidate(name):
                candidates.setdefault(name, {"name": name, "sources": set(), "evidence": []})
                candidates[name]["sources"].add(section)
                candidates[name]["evidence"].append(text[max(0, m.start()-40):m.end()+40])

        for m in re.finditer(
            r'\b(?:Fe|Co|Ni|Mn|Cu|Zn|Ce|Au|Ag|Pt|Pd|Ti|V|Cr|Mo|W|Ru|Rh|Ir|La|Zr|Al|Sn|Bi|In)\d*[-/]?(?:SA|SAN|SAC|SAzyme|SAEs|SACs|SA-N|SAC-N)\b',
            text, re.I,
        ):
            name = m.group(0).strip()
            if self._is_valid_candidate(name):
                candidates.setdefault(name, {"name": name, "sources": set(), "evidence": []})
                candidates[name]["sources"].add(section)
                candidates[name]["evidence"].append(text[max(0, m.start()-40):m.end()+40])

        for m in re.finditer(
            r'\b(?:Prussian\s+blue|PB|PBA|PBAs?|LDH|LDHs|MXene|g-C3N4|g-C\dN\d|CN|CNFs?|CNTs?|rGO|GO|N-GO|N-rGO|B,N-GO|S,N-GO)\b',
            text, re.I,
        ):
            name = m.group(0).strip()
            if self._is_valid_candidate(name):
                candidates.setdefault(name, {"name": name, "sources": set(), "evidence": []})
                candidates[name]["sources"].add(section)
                candidates[name]["evidence"].append(text[max(0, m.start()-40):m.end()+40])

        for m in re.finditer(
            r'\b(?:Fe|Co|Ni|Mn|Cu|Zn|Ce|Au|Ag|Pt|Pd|Ti|V|Cr|Mo|W|Ru|Rh|Ir|La|Zr|Al|Sn|Bi|In|Ga|Ge|Sb|Te|Hf|Ta|Re|Os|Y|Sc|Cd|Hg|Tl|Pb|Nb)\d*(?:[-/](?:Fe|Co|Ni|Mn|Cu|Zn|Ce|Au|Ag|Pt|Pd|Ti|V|Cr|Mo|W|Ru|Rh|Ir|La|Zr|Al|Sn|Bi|In)\d*)+\s+(?:alloy|alloyed|bimetal|intermetal)\b',
            text, re.I,
        ):
            name = m.group(0).strip()
            if self._is_valid_candidate(name):
                candidates.setdefault(name, {"name": name, "sources": set(), "evidence": []})
                candidates[name]["sources"].add(section)
                candidates[name]["evidence"].append(text[max(0, m.start()-40):m.end()+40])

        for m in re.finditer(
            r'\b(?:N|B|S|P|F|Cl|Br|I|Se|Si|P|As)\s*,\s*(?:N|B|S|P|F|Cl|Br|I|Se|Si|P|As)(?:\s*,\s*(?:N|B|S|P|F|Cl|Br|I|Se|Si|P|As))*[-\s]*(?:co-?)?doped\s+(?:C|carbon|graphene|CNT|rGO|NC|BC)\b',
            text, re.I,
        ):
            name = m.group(0).strip()
            if self._is_valid_candidate(name):
                candidates.setdefault(name, {"name": name, "sources": set(), "evidence": []})
                candidates[name]["sources"].add(section)
                candidates[name]["evidence"].append(text[max(0, m.start()-40):m.end()+40])

        for m in re.finditer(
            r'\b(?:N|B|S|P|F|Se|Si)\s*[-–]\s*(?:C|carbon|CN|C\dN\d|NC|graphene|rGO|CNT|carbon\s+dot)\b',
            text, re.I,
        ):
            name = m.group(0).strip()
            if self._is_valid_candidate(name):
                candidates.setdefault(name, {"name": name, "sources": set(), "evidence": []})
                candidates[name]["sources"].add(section)
                candidates[name]["evidence"].append(text[max(0, m.start()-40):m.end()+40])

        for m in re.finditer(
            r'\b(?:PPy|PANI|PEDOT|PDA|polydopamine|polypyrrole|polyaniline|chitosan|CS|cellulose|starch|alginate|gelatin|PVA|PVP|PEG|PCL|PLGA)\b',
            text, re.I,
        ):
            name = m.group(0).strip()
            if self._is_valid_candidate(name):
                candidates.setdefault(name, {"name": name, "sources": set(), "evidence": []})
                candidates[name]["sources"].add(section)
                candidates[name]["evidence"].append(text[max(0, m.start()-40):m.end()+40])

        for m in re.finditer(
            r'\b(?:CDs?|CQDs?|GQDs?|carbon\s+dots?|carbon\s+quantum\s+dots?|graphene\s+quantum\s+dots?|NDs?|nanodiamond)\b',
            text, re.I,
        ):
            name = m.group(0).strip()
            if self._is_valid_candidate(name):
                candidates.setdefault(name, {"name": name, "sources": set(), "evidence": []})
                candidates[name]["sources"].add(section)
                candidates[name]["evidence"].append(text[max(0, m.start()-40):m.end()+40])

    def _is_valid_candidate(self, name: str) -> bool:
        if not name or len(name) < 2:
            return False
        lower = name.lower().strip()
        if lower in _GENERIC_PHRASES:
            return False
        if lower in _TECHNIQUE_ABBREVIATIONS or name in _TECHNIQUE_ABBREVIATIONS:
            return False
        if lower in _SUBSTRATE_NAMES or name in _SUBSTRATE_NAMES:
            return False
        if lower in _REAGENT_NAMES or name in _REAGENT_NAMES:
            return False
        if lower in _SMALL_MOLECULE_NAMES or name in _SMALL_MOLECULE_NAMES:
            return False
        if lower in _DISEASE_NAMES or name in _DISEASE_NAMES:
            return False
        if lower in _NON_MATERIAL_PHRASES or name in _NON_MATERIAL_PHRASES:
            return False
        if _SUBSTRATE_PLUS_RE.match(name):
            return False
        if _SENTENCE_ID_RE.match(name):
            return False
        if _RE_RATIO_FORMAT.match(name):
            return False
        if _RE_RATIO_FORMAT2.match(name):
            return False
        if lower.startswith("the ") or lower.startswith("a "):
            return False
        if _RE_ION_FORMAT.match(name):
            return False
        if _RE_ELEMENT_FORMAT.match(name) and not any(w in lower for w in _MORPHOLOGY_WORDS):
            elem = _RE_ELEMENT_FORMAT.match(name)
            if elem and elem.group(1) in {"Fe", "Co", "Ni", "Mn", "Cu", "Zn", "Ce", "Au",
                                           "Ag", "Pt", "Pd", "Ti", "V", "Cr", "Mo", "W",
                                           "Ru", "Rh", "Ir", "La", "Zr", "Al", "Sn", "Bi",
                                           "In", "Ga", "Ge", "Sb", "Te", "Hf", "Ta", "Re",
                                           "Os", "Y", "Sc", "Cd", "Hg", "Tl", "Pb", "Nb"}:
                return False
        if re.match(r'^[a-z]{1,3}-[a-z]{1,3}$', name, re.I):
            if not re.match(r'^(?:Fe|Co|Ni|Mn|Cu|Zn|Ce|Au|Ag|Pt|Pd|Ti|V|Cr|Mo|W|Ru|Rh|Ir|La|Zr|Al|Sn|Bi|In|Ga|Ge|Sb|Te|Hf|Ta|Re|Os|Y|Sc|Cd|Hg|Tl|Pb|Nb)-', name, re.I):
                return False
        for sub in _SUBSTRATE_NAMES:
            if sub.lower() in lower.split("/") and len(lower.split("/")) > 1:
                return False
        if re.search(r'\b(?:POD|OXD|CAT|SOD|GPx|GOx)[-\s]?like\s+nanozyme', name, re.I):
            return False
        has_chemical = bool(_MATERIAL_PATTERN_RE.search(name))
        has_morphology = any(w in lower for w in _MORPHOLOGY_WORDS)
        has_composite = bool(_COMPOSITE_PATTERN_RE.search(name))
        if not (has_chemical or has_morphology or has_composite):
            return False
        if len(name) <= 3 and not any(c.isdigit() for c in name) and not has_morphology and not has_composite:
            m = re.match(r'^([A-Z][a-z]?)([A-Z][a-z]?)$', name.strip())
            if not m:
                return False
            known_elements = {"Fe", "Co", "Ni", "Mn", "Cu", "Zn", "Ce", "Au", "Ag",
                              "Pt", "Pd", "Ti", "V", "Cr", "Mo", "W", "Ru", "Rh",
                              "Ir", "La", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy",
                              "Ho", "Er", "Tm", "Yb", "Lu", "Al", "Si", "C", "N",
                              "O", "S", "P", "Se", "Te", "B", "As", "Sb", "Bi",
                              "Sn", "Pb", "Ge", "Ga", "In", "Li", "Na", "K", "Ca",
                              "Mg", "Ba", "Sr", "Zr", "Hf", "Nb", "Ta", "Y", "Sc"}
            if m.group(1) not in known_elements or m.group(2) not in known_elements:
                return False
        return True

    def _split_compound_name(self, name: str) -> List[str]:
        parts = []
        if '@' in name:
            parts = [p.strip() for p in name.split('@') if p.strip()]
        elif '/' in name:
            parts = [p.strip() for p in name.split('/') if p.strip()]
        elif '-' in name:
            segments = name.split('-')
            if len(segments) == 2:
                chem_re = re.compile(r'[A-Z][a-z]?\d*')
                if chem_re.search(segments[0]) and chem_re.search(segments[1]):
                    parts = [s.strip() for s in segments if s.strip()]
        if len(parts) <= 1:
            return []
        return parts

    def _deduplicate(self, candidates: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = []
        seen = {}
        for name, info in candidates.items():
            lower = name.lower().strip()
            if lower in seen:
                result[seen[lower]]["sources"] |= info["sources"]
                result[seen[lower]]["evidence"].extend(info["evidence"])
                continue
            merged_into = None
            for existing_lower, existing_idx in seen.items():
                if lower in existing_lower or existing_lower in lower:
                    existing_name = result[existing_idx]["name"]
                    shorter, shorter_lower = (name, lower) if len(name) <= len(existing_name) else (existing_name, existing_lower)
                    longer, longer_lower = (existing_name, existing_lower) if len(name) <= len(existing_name) else (name, lower)
                    shorter_has_composite = bool(re.search(r'[@/]', shorter))
                    longer_has_composite = bool(re.search(r'[@/]', longer))
                    shorter_digit_count = sum(c.isdigit() for c in shorter)
                    longer_digit_count = sum(c.isdigit() for c in longer)
                    longer_has_mof = bool(re.search(r'\b(?:MIL|UiO|ZIF|MOF|COF|HKUST|NU|PCN|NOTT|DUT)\b', longer, re.I))
                    shorter_has_mof = bool(re.search(r'\b(?:MIL|UiO|ZIF|MOF|COF|HKUST|NU|PCN|NOTT|DUT)\b', shorter, re.I))
                    if longer_has_mof and not shorter_has_mof:
                        keep_name, keep_lower = longer, longer_lower
                    elif longer_has_composite and not shorter_has_composite:
                        keep_name, keep_lower = longer, longer_lower
                    elif longer_digit_count > shorter_digit_count:
                        keep_name, keep_lower = longer, longer_lower
                    elif longer_lower == shorter_lower + "s" or longer_lower == shorter_lower + "es":
                        keep_name, keep_lower = longer, longer_lower
                    else:
                        keep_name, keep_lower = shorter, shorter_lower
                    if keep_name == name:
                        keep_info = {"name": name, "sources": info["sources"] | result[existing_idx]["sources"],
                                     "evidence": (info["evidence"] + result[existing_idx]["evidence"])[:5]}
                    else:
                        keep_info = {"name": keep_name, "sources": result[existing_idx]["sources"] | info["sources"],
                                     "evidence": (result[existing_idx]["evidence"] + info["evidence"])[:5]}
                    result[existing_idx] = keep_info
                    if keep_lower != (existing_lower if keep_name == existing_name else lower):
                        seen[keep_lower] = existing_idx
                    merged_into = existing_idx
                    break
            if merged_into is not None:
                continue
            seen[lower] = len(result)
            result.append({"name": name, "sources": info["sources"], "evidence": info["evidence"][:5]})
        return result


class NanozymeScorer:
    def score(self, candidates: List[Dict[str, Any]], doc: PreprocessedDocument) -> List[Dict[str, Any]]:
        title = doc.metadata.get("title", "")
        title_lower = title.lower()
        abstract_text = self._get_abstract(doc)

        for cand in candidates:
            if not cand.get("name"):
                continue
            score = sum(_SECTION_SCORE_MAP.get(s, 0) for s in cand.get("sources", set()))
            name_lower = cand["name"].lower().strip()

            is_generic = name_lower in _GENERIC_PHRASES or bool(_SHORT_GENERIC_RE.match(cand["name"]))
            is_substrate = name_lower in {s.lower() for s in _SUBSTRATE_NAMES} or bool(_SUBSTRATE_PLUS_RE.match(cand["name"]))
            is_technique = name_lower in {t.lower() for t in _TECHNIQUE_ABBREVIATIONS}
            is_ion = bool(re.match(r'^[A-Z][a-z]?\d*[+-]$', cand["name"]))
            is_reagent = name_lower in {r.lower() for r in _REAGENT_NAMES}
            is_small_mol = name_lower in {m.lower() for m in _SMALL_MOLECULE_NAMES}
            is_disease = name_lower in {d.lower() for d in _DISEASE_NAMES}
            is_non_material = name_lower in {p.lower() for p in _NON_MATERIAL_PHRASES}
            is_ratio = bool(_RATIO_PATTERN.match(cand["name"]))

            if is_generic:
                score += _GENERIC_PENALTY
            if is_substrate:
                score += -30
            if is_technique:
                score += -30
            if is_ion:
                score += -25
            if is_reagent:
                score += -25
            if is_small_mol:
                score += -30
            if is_disease:
                score += -40
            if is_non_material:
                score += -40
            if is_ratio:
                score += -50

            if not is_generic and not is_substrate and not is_technique and not is_reagent and not is_small_mol and not is_disease and not is_non_material and not is_ratio:
                if cand["name"] in title or name_lower in title_lower:
                    score += 10
                if "title" in cand.get("sources", set()):
                    score += 5
                if any(mw in title_lower and mw in name_lower for mw in _MORPHOLOGY_WORDS):
                    score += 3
                if _METAL_ELEMENTS_RE.search(cand["name"]):
                    score += 5
                if "/" in cand["name"] or "@" in cand["name"]:
                    score += 5
                if re.search(r'\d', cand["name"]):
                    score += 2
                if re.search(r'(?:SA|SAN|SAC|SAzyme)$', cand["name"], re.I):
                    score += 8
                if re.search(r'Single[-\s]?Atom$', cand["name"], re.I):
                    score -= 3
                if re.search(r'/(?:LDH|LDHs|MOF|COF|ZIF)$', cand["name"], re.I):
                    score += 5
                title_metals = set(_METAL_ELEMENTS_RE.findall(title))
                name_metals = set(_METAL_ELEMENTS_RE.findall(cand["name"]))
                if title_metals and name_metals and name_metals & title_metals:
                    score += 8
                supported_m = re.search(
                    r'\b(\w[\w@/\-]*)\s+Supported\s+(\w[\w@/\-]*)\b',
                    title, re.I,
                )
                if supported_m:
                    supported_name = supported_m.group(2).strip()
                    if name_lower in supported_name.lower() or supported_name.lower() in name_lower:
                        score += 10
                    carrier_name = supported_m.group(1).strip()
                    if name_lower in carrier_name.lower() or carrier_name.lower() in name_lower:
                        score -= 5
                _nanozyme_name_match = re.search(
                    r'\b' + re.escape(cand["name"]) + r'\s+nanozyme',
                    title, re.I
                )
                if _nanozyme_name_match:
                    score += 12
                _sa_in_title = re.search(
                    r'\b' + re.escape(cand["name"].split('-')[0] if '-' in cand["name"] else cand["name"]) + r'\s+Single[-\s]?Atom\s+Nanozyme',
                    title, re.I
                )
                if _sa_in_title and re.search(r'(?:SA|SAN|SAC|SAzyme)$', cand["name"], re.I):
                    score += 12
                _based_match = re.search(
                    re.escape(cand["name"]) + r'-based',
                    title, re.I
                )
                if _based_match:
                    score += 5
                if '@' in cand["name"]:
                    at_parts = cand["name"].split('@')
                    if len(at_parts) >= 3:
                        score += 4
                    elif len(at_parts) >= 2:
                        score += 2
                if re.search(r'\b(?:MIL|UiO|HKUST|PCN|NU|NOTT|DUT|ZIF|MOF|COF)[-\s]?\d+', cand["name"], re.I):
                    score += 6
                if re.search(r'\b(?:Fe|Co|Ni|Mn|Cu|Zn|Ce|Au|Ag|Pt|Pd)\s*-\s*(?:N|C|NC|S|P|B)\b', cand["name"], re.I):
                    score += 4
                if re.search(r'\b(?:Fe|Co|Ni|Mn|Cu|Zn|Ce)\d*O\d+', cand["name"]):
                    score += 4
                if re.search(r'\b(?:Prussian\s+blue|PB|PBA|LDH|MXene|g-C\dN\d|rGO|GO)\b', cand["name"], re.I):
                    score += 5
                if re.search(r'\b(?:CDs?|CQDs?|GQDs?|CNFs?|CNTs?)\b', cand["name"], re.I):
                    score += 3
                if re.search(r'\b\w+@\w+(?:@\w+)?\b', cand["name"]):
                    score += 3
                if re.search(r'\b\w+[-/]\w+(?:[-/]\w+)*\b', cand["name"]) and not re.search(r'^[A-Z]/[A-Z]$', cand["name"]):
                    score += 2

            score += self._score_data_richness(cand, doc)
            score += self._score_narrative_importance(cand, title, abstract_text)

            if cand.get("llm_identified"):
                score += 25
                logger.debug(f"[SMN] LLM-identified bonus +25 for '{cand['name']}'")
            if cand.get("llm_related"):
                score += 5

            cand["score"] = score

        scored = sorted(candidates, key=lambda x: x["score"], reverse=True)

        if len(scored) >= 2:
            top_name = scored[0]["name"]
            for i in range(1, min(len(scored), 5)):
                other_name = scored[i]["name"]
                if (other_name in top_name and len(other_name) < len(top_name)
                        and re.search(r'[@/]', top_name)):
                    pass
                elif (top_name in other_name and len(top_name) < len(other_name)
                      and re.search(r'[@/]', other_name)
                      and scored[i]["score"] >= scored[0]["score"] - 8):
                    scored[0], scored[i] = scored[i], scored[0]
                    logger.info(f"[SMN] Composite name preferred: '{other_name}' over '{top_name}'")
                    break

        if len(scored) >= 2 and scored[0]["score"] - scored[1]["score"] <= 4:
            top_tas = bool(scored[0]["sources"] & {"title", "abstract", "synthesis"})
            sec_tas = bool(scored[1]["sources"] & {"title", "abstract", "synthesis"})
            if sec_tas and not top_tas:
                scored[0], scored[1] = scored[1], scored[0]
            elif top_tas == sec_tas:
                resolved = self._resolve_ambiguity(scored[0], scored[1], doc)
                if resolved:
                    if resolved["name"] == scored[1]["name"]:
                        scored[0], scored[1] = scored[1], scored[0]
                    scored[0]["selection_ambiguous"] = False
                    scored[0]["ambiguity_resolved_by"] = resolved.get("resolution_method", "tiebreaker")
                else:
                    scored[0]["selection_ambiguous"] = True

        return scored

    def _get_abstract(self, doc: PreprocessedDocument) -> str:
        for chunk in doc.chunks[:3]:
            if "abstract" in chunk.lower()[:200]:
                return chunk[:2000]
        return ""

    def _score_data_richness(self, cand: Dict[str, Any], doc: PreprocessedDocument) -> int:
        bonus = 0
        if not cand.get("name"):
            return bonus
        name_lower = cand["name"].lower().strip()

        if name_lower in _GENERIC_PHRASES:
            return 0
        if name_lower in {s.lower() for s in _SUBSTRATE_NAMES} or bool(_SUBSTRATE_PLUS_RE.match(cand["name"])):
            return 0
        if name_lower in {t.lower() for t in _TECHNIQUE_ABBREVIATIONS}:
            return 0
        if name_lower in {r.lower() for r in _REAGENT_NAMES}:
            return 0
        if name_lower in {m.lower() for m in _SMALL_MOLECULE_NAMES}:
            return 0
        if name_lower in {d.lower() for d in _DISEASE_NAMES}:
            return 0
        if name_lower in {p.lower() for p in _NON_MATERIAL_PHRASES}:
            return 0
        if _RATIO_PATTERN.match(cand["name"]):
            return 0

        variants = {name_lower}
        if "@" in name_lower:
            variants.update(p.strip() for p in name_lower.split("@") if p.strip())
        if "/" in name_lower:
            variants.update(p.strip() for p in name_lower.split("/") if p.strip())

        has_kinetics = False
        has_activity = False
        has_synthesis = False
        has_application = False

        for chunk in doc.chunks:
            cl = chunk.lower()
            mentions = any(v in cl for v in variants if len(v) >= 2)
            if not mentions:
                continue
            if not has_kinetics and any(kw in cl for kw in ("km ", "vmax", "michaelis", "kinetic parameter")):
                has_kinetics = True
            if not has_activity and any(kw in cl for kw in ("peroxidase-like", "oxidase-like", "catalase-like", "enzyme-like")):
                has_activity = True
            if not has_synthesis and any(kw in cl for kw in ("synthesized", "prepared", "hydrothermal", "calcination")):
                has_synthesis = True
            if not has_application and any(kw in cl for kw in ("detection", "sensing", "sensor", "lod")):
                has_application = True

        if has_kinetics:
            bonus += 8
        if has_activity:
            bonus += 5
        if has_synthesis:
            bonus += 3
        if has_application:
            bonus += 3

        if "kinetics" in cand.get("sources", set()):
            bonus += 3

        evidence_count = len(cand.get("evidence", []))
        bonus += min(evidence_count, 5)

        return bonus

    def _score_narrative_importance(self, cand: Dict[str, Any], title: str, abstract: str) -> int:
        bonus = 0
        if not cand.get("name"):
            return bonus
        name_lower = cand["name"].lower().strip()

        if name_lower in _GENERIC_PHRASES:
            return 0

        title_lower = title.lower()
        abstract_lower = abstract.lower()
        combined = title_lower + " " + abstract_lower

        if name_lower in title_lower:
            title_words = title_lower.split()
            for word in title_words:
                if name_lower in word and len(word) < len(name_lower) + 5:
                    bonus += 6
                    break
            else:
                bonus += 3

        if name_lower in abstract_lower:
            count = abstract_lower.count(name_lower)
            bonus += min(count * 2, 8)

        this_work_proximity = 0
        for chunk_text in [title, abstract]:
            cl = chunk_text.lower()
            if name_lower in cl and ("this work" in cl or "our nanozyme" in cl or "proposed" in cl):
                this_work_proximity += 4
        bonus += this_work_proximity

        return bonus

    def _resolve_ambiguity(
        self,
        top: Dict[str, Any],
        second: Dict[str, Any],
        doc: PreprocessedDocument,
    ) -> Optional[Dict[str, Any]]:
        title = doc.metadata.get("title", "").lower()
        abstract = self._get_abstract(doc).lower()
        combined = title + " " + abstract

        top_name = top["name"].lower().strip()
        sec_name = second["name"].lower().strip()

        top_in_title = top_name in title
        sec_in_title = sec_name in title
        if top_in_title and not sec_in_title:
            return {**top, "resolution_method": "title_mention"}
        if sec_in_title and not top_in_title:
            return {**second, "resolution_method": "title_mention"}

        top_count = combined.count(top_name)
        sec_count = combined.count(sec_name)
        if top_count > sec_count + 2:
            return {**top, "resolution_method": "abstract_frequency"}
        if sec_count > top_count + 2:
            return {**second, "resolution_method": "abstract_frequency"}

        top_richness = self._score_data_richness(top, doc)
        sec_richness = self._score_data_richness(second, doc)
        if top_richness > sec_richness + 3:
            return {**top, "resolution_method": "data_richness"}
        if sec_richness > top_richness + 3:
            return {**second, "resolution_method": "data_richness"}

        top_evidence = len(top.get("evidence", []))
        sec_evidence = len(second.get("evidence", []))
        if top_evidence > sec_evidence + 2:
            return {**top, "resolution_method": "evidence_count"}
        if sec_evidence > top_evidence + 2:
            return {**second, "resolution_method": "evidence_count"}

        if len(top_name) > len(sec_name):
            has_composite = bool(re.search(r'[@/]', top_name))
            if has_composite:
                return {**top, "resolution_method": "composite_name_preferred"}

        return None


class EvidenceBucketBuilder:
    def __init__(self, max_sentences: int = 30, consistency_guard=None):
        self.max_sentences = max_sentences
        self.consistency_guard = consistency_guard
        self.warnings = []

    _SECTION_KEYWORDS_PRIORITY = {
        "synthesis": ["synthesis", "preparation", "fabrication", "experimental", "materials and methods", "materials & methods", "methodology", "chemicals and reagents"],
        "characterization": ["characterization", "instrumentation", "measurements", "analytical methods", "apparatus"],
        "activity": ["catalytic activity", "enzyme-like activity", "enzyme activity", "activity assay", "catalytic performance", "activity evaluation"],
        "kinetics": ["kinetics", "kinetic analysis", "michaelis-menten", "steady-state kinetics", "enzyme kinetics", "kinetic study", "kinetic parameters"],
        "application": ["application", "sensing", "detection", "biosensor", "analytical application", "practical application", "real sample"],
        "mechanism": ["mechanism", "catalytic mechanism", "reaction mechanism", "mechanistic", "mechanism study", "mechanism investigation"],
        "results": ["results and discussion", "results", "discussion", "results & discussion"],
    }

    def build(self, doc: PreprocessedDocument, selected_name: str,
              all_candidates: Optional[List[str]] = None) -> Dict[str, List[str]]:
        if self.consistency_guard is None:
            from consistency_guard import ConsistencyGuard
            self.consistency_guard = ConsistencyGuard(selected_name, all_candidates, text_chunks=doc.chunks)

        buckets: Dict[str, List[str]] = {k: [] for k in _BUCKET_KEYWORDS}

        all_sentences: List[Tuple[str, str]] = []
        chunk_sections: Dict[int, str] = {}
        for idx, chunk in enumerate(doc.chunks):
            section = self._infer_section(doc.chunk_contexts, idx, chunk)
            chunk_sections[idx] = section
            for line in chunk.split("\n"):
                line = line.strip()
                if line:
                    all_sentences.append((line, section))
        for vlm_task in doc.vlm_tasks:
            caption = vlm_task.get("caption", "")
            if caption:
                all_sentences.append((caption, "characterization_caption"))

        name_lower = (selected_name or "").lower()
        variants = {name_lower}
        if "@" in name_lower:
            variants.update(p.strip() for p in name_lower.split("@") if p.strip())
        if "/" in name_lower:
            variants.update(p.strip() for p in name_lower.split("/") if p.strip())
        for prefix in ("nano", "the ", "a "):
            if name_lower.startswith(prefix):
                variants.add(name_lower[len(prefix):])

        self.consistency_guard._discover_aliases([c for c in doc.chunks[:30]])
        alias_set = self.consistency_guard.aliases if hasattr(self.consistency_guard, 'aliases') else set()
        all_name_variants = variants | {a.lower() for a in alias_set if len(a) >= 2}

        for text, section in all_sentences:
            text_lower = text.lower()
            name_matched = any(v in text_lower for v in all_name_variants)
            for bucket_name, pattern in _BUCKET_KEYWORDS.items():
                if not pattern.search(text):
                    continue
                if name_matched:
                    buckets[bucket_name].append(text)
                elif bucket_name in ("kinetics", "application", "mechanism"):
                    attr = self.consistency_guard.check_sentence_attribution(text)
                    if attr["belongs_to_selected"]:
                        buckets[bucket_name].append(text)
                    elif section in ("results", "discussion", "kinetics", "application", "mechanism") and attr["confidence"] != "high":
                        buckets[bucket_name].append(text)
                    elif self._nearby_name_mention(text, all_sentences, all_name_variants):
                        buckets[bucket_name].append(text)
                elif bucket_name in ("activity", "synthesis", "characterization"):
                    attr = self.consistency_guard.check_sentence_attribution(text)
                    if attr["belongs_to_selected"]:
                        buckets[bucket_name].append(text)
                    elif any(kw in text_lower for kw in ("nanozyme", "enzyme-like", "catalytic",
                                                          "peroxidase", "oxidase", "catalase",
                                                          "synthesized", "prepared", "hydrothermal",
                                                          "solvothermal", "calcination")):
                        if attr["confidence"] != "high" or attr["reason"] not in (
                            "previous_work_reference", "mentions_other_only"
                        ):
                            buckets[bucket_name].append(text)
                    elif bucket_name == "synthesis" and attr["confidence"] == "low":
                        buckets[bucket_name].append(text)
                    elif self._nearby_name_mention(text, all_sentences, all_name_variants):
                        buckets[bucket_name].append(text)

        for key in buckets:
            seen = set()
            unique = []
            for s in buckets[key]:
                norm = s.strip().lower()
                if norm not in seen:
                    seen.add(norm)
                    unique.append(s)
            buckets[key] = unique[:self.max_sentences]

        for fb_bucket in ("kinetics", "application", "mechanism"):
            if buckets[fb_bucket]:
                continue
            for text, section in all_sentences:
                text_lower = text.lower()
                name_matched = any(v in text_lower for v in all_name_variants)
                pattern = _BUCKET_KEYWORDS.get(fb_bucket)
                if not pattern or not pattern.search(text):
                    continue
                if name_matched:
                    buckets[fb_bucket].append(text)
                else:
                    attr = self.consistency_guard.check_sentence_attribution(text)
                    if attr["belongs_to_selected"]:
                        buckets[fb_bucket].append(text)
                    elif attr["confidence"] != "high" or attr["reason"] not in (
                        "previous_work_reference", "mentions_other_only"
                    ):
                        buckets[fb_bucket].append(text)
            if buckets[fb_bucket]:
                self.warnings.append(f"{fb_bucket}_bucket_fallback_applied")

        for fb_bucket in ("activity", "synthesis", "characterization", "material"):
            if buckets[fb_bucket]:
                continue
            for text, section in all_sentences:
                pattern = _BUCKET_KEYWORDS.get(fb_bucket)
                if not pattern or not pattern.search(text):
                    continue
                buckets[fb_bucket].append(text)
            if buckets[fb_bucket]:
                self.warnings.append(f"{fb_bucket}_bucket_loose_fallback_applied")

        for key in buckets:
            seen = set()
            unique = []
            for s in buckets[key]:
                norm = s.strip().lower()
                if norm not in seen:
                    seen.add(norm)
                    unique.append(s)
            buckets[key] = unique[:self.max_sentences]

        return buckets

    def _nearby_name_mention(self, text: str, all_sentences: List[Tuple[str, str]],
                              name_variants: set, window: int = 3) -> bool:
        target_norm = text.strip().lower()[:80]
        for i, (sent, sec) in enumerate(all_sentences):
            if sent.strip().lower()[:80] == target_norm:
                start = max(0, i - window)
                end = min(len(all_sentences), i + window + 1)
                for j in range(start, end):
                    if j == i:
                        continue
                    nearby_lower = all_sentences[j][0].lower()
                    if any(v in nearby_lower for v in name_variants if len(v) >= 2):
                        return True
                break
        return False

    def _infer_section(self, contexts: List[Dict], idx: int, chunk: str) -> str:
        if idx < len(contexts):
            ctx = contexts[idx]
            section_type = ctx.get("section_type", "")
            if section_type in ("results", "experimental", "methods", "discussion"):
                signal_types = ctx.get("signal_types", [])
                if "kinetics" in signal_types:
                    return "kinetics"
                if "activity" in signal_types:
                    return "activity"
                if "application" in signal_types or "sensing" in signal_types:
                    return "application"
                if "material" in signal_types:
                    return "characterization"
                if section_type == "experimental":
                    return "synthesis"
            elif section_type == "abstract":
                return "activity"
        cl = chunk.lower()[:800]
        best_section = "unknown"
        best_count = 0
        for section_name, keywords in self._SECTION_KEYWORDS_PRIORITY.items():
            count = sum(1 for kw in keywords if kw in cl)
            if count > best_count:
                best_count = count
                best_section = section_name
        if best_count > 0:
            return best_section
        if any(kw in cl for kw in ["peroxidase-like", "oxidase-like", "catalytic activity"]):
            return "activity"
        if any(kw in cl for kw in ["michaelis", "kinetic", "km ", "vmax"]):
            return "kinetics"
        if any(kw in cl for kw in ["detection", "sensing", "sensor", "lod"]):
            return "application"
        return "unknown"


class TableProcessor:
    def classify_and_summarize(self, tables: List[Dict], selected_name: str) -> Dict[str, Any]:
        result = {
            "kinetics_tables": [], "sensing_tables": [], "comparison_tables": [],
            "recovery_tables": [], "characterization_tables": [], "general_tables": [],
        }
        for tbl in tables:
            headers = " ".join(str(h) for h in tbl.get("headers", tbl.get("columns", [])))
            rows = tbl.get("rows", [])
            rows_text = " ".join(str(cell) for row in rows for cell in row) if rows else ""
            content_text = tbl.get("content_text", "")
            markdown = tbl.get("markdown", "")
            caption = tbl.get("caption", "")
            full_text = f"{headers} {rows_text} {content_text} {markdown} {caption}"

            preprocessor_type = tbl.get("table_type", "")
            tbl_type = _PREPROCESSOR_TO_SMN_TYPE.get(preprocessor_type, "")
            if not tbl_type:
                for tt, pattern in _TABLE_TYPE_PATTERNS.items():
                    if pattern.search(full_text):
                        tbl_type = tt
                        break
            if not tbl_type:
                tbl_type = "general_table"

            entry = {"table_type": tbl_type, "headers": tbl.get("headers", tbl.get("columns", [])),
                     "row_count": len(rows), "text": full_text[:500],
                     "rows": rows, "content_text": content_text, "markdown": markdown, "caption": caption}

            if tbl_type == "comparison_table":
                this_work_rows = self._filter_this_work(tbl, selected_name)
                entry["this_work_rows"] = this_work_rows
                entry["other_rows_count"] = len(rows) - len(this_work_rows)
            elif tbl_type in ("kinetics_table", "sensing_table"):
                entry["this_work_rows"] = self._filter_this_work(tbl, selected_name)

            result[f"{tbl_type}s"].append(entry)

        return result

    def _filter_this_work(self, tbl: Dict, selected_name: str) -> List[Dict]:
        this_work_rows = []
        name_lower = selected_name.lower()
        name_variants = [name_lower]
        if "@" in name_lower:
            name_variants.extend(p.strip() for p in name_lower.split("@") if p.strip())
        if "/" in name_lower:
            name_variants.extend(p.strip() for p in name_lower.split("/") if p.strip())
        for suffix in (" nanoparticles", " nanosheets", " nanorods",
                       " nanotubes", " nanospheres", " nanozyme",
                       " nanocomposite", " nanocatalyst"):
            if name_lower.endswith(suffix):
                name_variants.append(name_lower[:-len(suffix)])
        name_variants = [v for v in name_variants if len(v) >= 2]

        rows = tbl.get("rows", [])
        if not rows:
            return this_work_rows

        headers = [str(h).lower() for h in rows[0]] if rows else []
        material_col = None
        for i, h in enumerate(headers):
            if any(kw in h for kw in ("material", "catalyst", "nanozyme", "sample", "compound")):
                material_col = i
                break

        for row in rows[1:] if len(rows) > 1 else []:
            if not isinstance(row, (list, tuple)):
                continue
            row_text = " ".join(str(cell) for cell in row).lower()
            row_compact = row_text.replace(" ", "").replace("-", "")

            if _THIS_WORK_RE.search(row_text):
                this_work_rows.append({"cells": row, "source": "this_work"})
                continue

            if any(v in row_compact for v in [nv.replace(" ", "").replace("-", "") for nv in name_variants]):
                this_work_rows.append({"cells": row, "source": "name_match"})
                continue

            if material_col is not None and material_col < len(row):
                cell_text = str(row[material_col]).lower().strip()
                cell_compact = cell_text.replace(" ", "").replace("-", "")
                if any(nv.replace(" ", "").replace("-", "") in cell_compact for nv in name_variants):
                    this_work_rows.append({"cells": row, "source": "material_col_match"})
                    continue

            if material_col is not None and material_col < len(row):
                cell_text = str(row[material_col]).lower().strip()
                if cell_text in ("1", "1a", "a") and len(rows) <= 5:
                    this_work_rows.append({"cells": row, "source": "first_entry_guess"})
                    continue

        return this_work_rows

    def _find_column_indices(self, headers: List[str], keywords_map: Dict[str, str]) -> Dict[str, int]:
        col_map: Dict[str, int] = {}
        for i, h in enumerate(headers):
            h_lower = str(h).lower().strip()
            for param, kw in keywords_map.items():
                if param not in col_map and kw in h_lower:
                    col_map[param] = i
        return col_map

    def _extract_kinetics_from_structured_rows(
        self, tbl: Dict, selected_name: str
    ) -> List[Dict]:
        rows = tbl.get("rows", [])
        if not rows or len(rows) < 2:
            return []
        headers = [str(h) for h in rows[0]]
        col_map = self._find_column_indices(headers, {
            "Km": "km", "Km_unit": "km(", "Vmax": "vmax", "Vmax_unit": "vmax(",
            "kcat": "kcat", "kcat_Km": "kcat/km", "substrate": "substrate",
            "material": "material",
        })
        if "Km" not in col_map and "Vmax" not in col_map and "kcat" not in col_map:
            return []
        name_lower = selected_name.lower() if selected_name else ""
        values: List[Dict] = []
        for row in rows[1:]:
            if not isinstance(row, (list, tuple)) or len(row) == 0:
                continue
            row_text = " ".join(str(c) for c in row).lower()
            is_target = (
                _THIS_WORK_RE.search(row_text) or
                (name_lower and name_lower in row_text) or
                ("material" not in col_map)
            )
            if not is_target:
                continue
            material_variant = None
            if "material" in col_map and col_map["material"] < len(row):
                mat_cell = str(row[col_map["material"]]).strip()
                if mat_cell and mat_cell.lower() != "material":
                    material_variant = mat_cell
            if "Km" in col_map and col_map["Km"] < len(row):
                km_val = row[col_map["Km"]]
                km_unit = row[col_map["Km_unit"]] if "Km_unit" in col_map and col_map["Km_unit"] < len(row) else None
                if km_val is not None and str(km_val).strip():
                    sub = row[col_map["substrate"]] if "substrate" in col_map and col_map["substrate"] < len(row) else None
                    entry = {"parameter": "Km", "value": str(km_val).strip(),
                                   "unit": str(km_unit).strip() if km_unit else None,
                                   "substrate": str(sub).strip() if sub else None,
                                   "source": "table_structured"}
                    if material_variant:
                        entry["material_variant"] = material_variant
                    values.append(entry)
            if "Vmax" in col_map and col_map["Vmax"] < len(row):
                vmax_val = row[col_map["Vmax"]]
                vmax_unit = row[col_map["Vmax_unit"]] if "Vmax_unit" in col_map and col_map["Vmax_unit"] < len(row) else None
                if vmax_val is not None and str(vmax_val).strip():
                    entry = {"parameter": "Vmax", "value": str(vmax_val).strip(),
                                   "unit": str(vmax_unit).strip() if vmax_unit else None,
                                   "substrate": None, "source": "table_structured"}
                    if material_variant:
                        entry["material_variant"] = material_variant
                    values.append(entry)
            if "kcat" in col_map and col_map["kcat"] < len(row):
                kcat_val = row[col_map["kcat"]]
                if kcat_val is not None and str(kcat_val).strip():
                    entry = {"parameter": "kcat", "value": str(kcat_val).strip(),
                                   "unit": "s⁻¹", "substrate": None, "source": "table_structured"}
                    if material_variant:
                        entry["material_variant"] = material_variant
                    values.append(entry)
            if "kcat_Km" in col_map and col_map["kcat_Km"] < len(row):
                kcat_km_val = row[col_map["kcat_Km"]]
                if kcat_km_val is not None and str(kcat_km_val).strip():
                    entry = {"parameter": "kcat_Km", "value": str(kcat_km_val).strip(),
                                   "unit": "M⁻¹s⁻¹", "substrate": None, "source": "table_structured"}
                    if material_variant:
                        entry["material_variant"] = material_variant
                    values.append(entry)
        return values

    def get_kinetics_values(self, classified: Dict[str, Any], selected_name: str) -> List[Dict]:
        values = []
        name_lower = selected_name.lower() if selected_name else ""
        for tbl in classified.get("kinetics_tables", []):
            structured = self._extract_kinetics_from_structured_rows(tbl, selected_name)
            if structured:
                values.extend(structured)
                continue
            this_work_rows = tbl.get("this_work_rows", [])
            rows = tbl.get("rows", [])
            content_text = tbl.get("content_text", "")
            markdown = tbl.get("markdown", "")

            if this_work_rows:
                for row_dict in this_work_rows:
                    cells = row_dict.get("cells", [])
                    row_text = " ".join(str(c) for c in cells)
                    self._extract_kinetics_from_row(row_text, values)
            elif rows:
                for row in rows:
                    row_text = " ".join(str(c) for c in row)
                    row_lower = row_text.lower()
                    if _THIS_WORK_RE.search(row_lower) or name_lower in row_lower:
                        self._extract_kinetics_from_row(row_text, values)

            if not this_work_rows and not rows:
                fallback_texts = []
                if content_text:
                    fallback_texts.append(content_text)
                if markdown:
                    for line in markdown.split("\n"):
                        line = line.strip()
                        if line and not line.startswith("|---") and not line.startswith("| ---"):
                            fallback_texts.append(line)
                for text in fallback_texts:
                    text_lower = text.lower()
                    if name_lower and name_lower in text_lower:
                        self._extract_kinetics_from_row(text, values)
                    elif _THIS_WORK_RE.search(text_lower):
                        self._extract_kinetics_from_row(text, values)
                    elif any(kw in text_lower for kw in ("km", "vmax", "kcat")):
                        self._extract_kinetics_from_row(text, values)

        for tbl in classified.get("comparison_tables", []):
            for row_dict in tbl.get("this_work_rows", []):
                cells = row_dict.get("cells", [])
                row_text = " ".join(str(c) for c in cells)
                self._extract_kinetics_from_row(row_text, values)

        for tbl in classified.get("general_tables", []):
            structured = self._extract_kinetics_from_structured_rows(tbl, selected_name)
            if structured:
                values.extend(structured)

        if not values:
            for tbl in (classified.get("kinetics_tables", [])
                        + classified.get("comparison_tables", [])
                        + classified.get("general_tables", [])):
                rows = tbl.get("rows", [])
                for row in rows:
                    if not isinstance(row, (list, tuple)):
                        continue
                    row_text = " ".join(str(c) for c in row)
                    row_lower = row_text.lower()
                    if any(kw in row_lower for kw in ("km", "vmax", "kcat")):
                        self._extract_kinetics_from_row(row_text, values)
                if values:
                    break
                content_text = tbl.get("content_text", "")
                markdown = tbl.get("markdown", "")
                for text_source in [content_text, markdown]:
                    if text_source and any(kw in text_source.lower() for kw in ("km", "vmax", "kcat")):
                        for line in text_source.split("\n"):
                            line = line.strip()
                            if line and not line.startswith("|---") and not line.startswith("| ---"):
                                self._extract_kinetics_from_row(line, values)
                        if values:
                            break
                if values:
                    break

        return values

    def _extract_kinetics_from_row(self, row_text: str, values: List[Dict]) -> None:
        for pat in _KM_PATTERNS:
            km_m = pat.search(row_text)
            if km_m:
                groups = km_m.groups()
                if len(groups) == 3:
                    values.append({"parameter": "Km", "value": groups[1], "unit": groups[2],
                                   "substrate": groups[0], "source": "table"})
                elif len(groups) == 2:
                    values.append({"parameter": "Km", "value": groups[0], "unit": groups[1],
                                   "substrate": None, "source": "table"})
                break
        for pat in _VMAX_PATTERNS:
            vmax_m = pat.search(row_text)
            if vmax_m:
                groups = vmax_m.groups()
                if len(groups) == 3:
                    values.append({"parameter": "Vmax", "value": groups[1], "unit": groups[2],
                                   "substrate": groups[0], "source": "table"})
                elif len(groups) == 2:
                    g0, g1 = groups
                    g0_is_unit = g0 in _RATE_UNITS or bool(re.match(r'10[−\-–]?\d*\s*M\s*[sS]', g0)) or bool(re.match(r'[mμunp]?M[·\s]*s[⁻\-–]1', g0))
                    g1_is_unit = g1 in _RATE_UNITS or bool(re.match(r'10[−\-–]?\d*\s*M\s*[sS]', g1)) or bool(re.match(r'[mμunp]?M[·\s]*s[⁻\-–]1', g1))
                    if g1_is_unit and not g0_is_unit:
                        values.append({"parameter": "Vmax", "value": g0, "unit": g1,
                                       "substrate": None, "source": "table"})
                    elif g0_is_unit:
                        values.append({"parameter": "Vmax", "value": g1, "unit": g0,
                                       "substrate": None, "source": "table"})
                    else:
                        values.append({"parameter": "Vmax", "value": g1, "unit": None,
                                       "substrate": g0, "source": "table"})
                break

    def get_sensing_values(self, classified: Dict[str, Any], selected_name: str = "") -> List[Dict]:
        values = []
        name_lower = selected_name.lower() if selected_name else ""
        for tbl in classified.get("sensing_tables", []) + classified.get("general_tables", []):
            rows = tbl.get("rows", [])
            if rows and len(rows) >= 2:
                headers = [str(h) for h in rows[0]]
                col_map = self._find_column_indices(headers, {
                    "LOD": "lod", "LOD_unit": "lod(", "linear_range_low": "linear",
                    "linear_range_high": "linear", "linear_range_unit": "unit",
                    "target_analyte": "analyte", "material": "material",
                    "method": "method", "sample": "sample",
                })
                if "LOD" in col_map or "linear_range_low" in col_map:
                    for row in rows[1:]:
                        if not isinstance(row, (list, tuple)):
                            continue
                        row_text = " ".join(str(c) for c in row).lower()
                        is_target = (
                            _THIS_WORK_RE.search(row_text) or
                            (name_lower and name_lower in row_text) or
                            ("material" not in col_map)
                        )
                        if not is_target:
                            continue
                        if "LOD" in col_map and col_map["LOD"] < len(row):
                            lod_val = row[col_map["LOD"]]
                            lod_unit = row[col_map["LOD_unit"]] if "LOD_unit" in col_map and col_map["LOD_unit"] < len(row) else None
                            if lod_val is not None and str(lod_val).strip():
                                values.append({"parameter": "LOD", "value": str(lod_val).strip(),
                                               "unit": str(lod_unit).strip() if lod_unit else None,
                                               "source": "table_structured"})
                        if "linear_range_low" in col_map and col_map["linear_range_low"] < len(row):
                            lr_val = row[col_map["linear_range_low"]]
                            lr_unit = row[col_map["linear_range_unit"]] if "linear_range_unit" in col_map and col_map["linear_range_unit"] < len(row) else None
                            if lr_val is not None and str(lr_val).strip():
                                lr_high = row[col_map["linear_range_high"]] if "linear_range_high" in col_map and col_map["linear_range_high"] < len(row) else None
                                lr_str = str(lr_val).strip()
                                if lr_high is not None and str(lr_high).strip():
                                    lr_str = f"{lr_val}–{lr_high}"
                                values.append({"parameter": "linear_range", "value": lr_str,
                                               "unit": str(lr_unit).strip() if lr_unit else None,
                                               "source": "table_structured"})
                        if "target_analyte" in col_map and col_map["target_analyte"] < len(row):
                            analyte_val = row[col_map["target_analyte"]]
                            if analyte_val is not None and str(analyte_val).strip():
                                values.append({"parameter": "target_analyte", "value": str(analyte_val).strip(),
                                               "unit": None, "source": "table_structured"})
                        if "method" in col_map and col_map["method"] < len(row):
                            method_val = row[col_map["method"]]
                            if method_val is not None and str(method_val).strip():
                                values.append({"parameter": "method", "value": str(method_val).strip(),
                                               "unit": None, "source": "table_structured"})
                        if "sample" in col_map and col_map["sample"] < len(row):
                            sample_val = row[col_map["sample"]]
                            if sample_val is not None and str(sample_val).strip():
                                values.append({"parameter": "sample_type", "value": str(sample_val).strip(),
                                               "unit": None, "source": "table_structured"})
                    continue
            for row_dict in tbl.get("this_work_rows", []):
                cells = row_dict.get("cells", [])
                row_text = " ".join(str(c) for c in cells)
                for pat in _LOD_PATTERNS:
                    lod_m = pat.search(row_text)
                    if lod_m:
                        values.append({"parameter": "LOD", "value": lod_m.group(1), "unit": lod_m.group(2), "source": "table"})
                        break
                for pat in _LINEAR_RANGE_PATTERNS:
                    lr_m = pat.search(row_text)
                    if lr_m:
                        values.append({"parameter": "linear_range", "value": lr_m.group(1), "unit": lr_m.group(2), "source": "table"})
                        break
                for pat in _ANALYTE_PATTERNS:
                    an_m = pat.search(row_text)
                    if an_m:
                        candidate = an_m.group(1).strip() if an_m.lastindex else an_m.group(0).strip()
                        if len(candidate) > 2:
                            values.append({"parameter": "target_analyte", "value": candidate, "unit": None, "source": "table"})
                            break

        if not values:
            for tbl in classified.get("sensing_tables", []) + classified.get("general_tables", []):
                content_text = tbl.get("content_text", "")
                markdown = tbl.get("markdown", "")
                for text_source in [content_text, markdown]:
                    if text_source and any(kw in text_source.lower() for kw in ("lod", "detection limit", "linear range")):
                        for line in text_source.split("\n"):
                            line = line.strip()
                            if line and not line.startswith("|---") and not line.startswith("| ---"):
                                for pat in _LOD_PATTERNS:
                                    m = pat.search(line)
                                    if m:
                                        values.append({"parameter": "LOD", "value": m.group(1), "unit": m.group(2), "source": "table_fallback"})
                                        break
                                for pat in _LINEAR_RANGE_PATTERNS:
                                    m = pat.search(line)
                                    if m:
                                        values.append({"parameter": "linear_range", "value": m.group(1), "unit": m.group(2), "source": "table_fallback"})
                                        break
                        if values:
                            break
                if values:
                    break

        return values

    def get_characterization_values(self, classified: Dict[str, Any], selected_name: str) -> List[Dict]:
        values = []
        name_lower = selected_name.lower() if selected_name else ""
        for tbl in classified.get("characterization_tables", []) + classified.get("general_tables", []):
            rows = tbl.get("rows", [])
            if not rows or len(rows) < 2:
                continue
            headers = [str(h) for h in rows[0]]
            col_map = self._find_column_indices(headers, {
                "surface_area": "surface area",
                "surface_area_unit": "m²/g",
                "particle_size": "particle size",
                "particle_size_unit": "particle size (",
                "material": "material",
            })
            for row in rows[1:]:
                if not isinstance(row, (list, tuple)) or len(row) == 0:
                    continue
                row_text = " ".join(str(c) for c in row).lower()
                is_target = (
                    _THIS_WORK_RE.search(row_text) or
                    (name_lower and name_lower in row_text) or
                    ("material" not in col_map)
                )
                if not is_target:
                    continue
                for param in ("surface_area", "particle_size"):
                    if param in col_map and col_map[param] < len(row):
                        val = row[col_map[param]]
                        if val is not None and str(val).strip():
                            unit_key = f"{param}_unit"
                            unit = row[col_map[unit_key]] if unit_key in col_map and col_map[unit_key] < len(row) else None
                            values.append({
                                "parameter": param, "value": str(val).strip(),
                                "unit": str(unit).strip() if unit else None,
                                "source": "table_structured",
                            })
        return values


_KM_RANGES = (1e-9, 0.5)

_PARAM_KEYWORDS = {
    "Km": ["km", "Km", "michaelis constant", "michaelis-menten constant", "apparent km", "km value"],
    "Vmax": ["vmax", "Vmax", "maximum velocity", "maximal velocity", "vmax value"],
    "kcat": ["kcat", "turnover", "catalytic constant", "turnover number", "turnover frequency"],
    "kcat_Km": ["kcat/km", "catalytic efficiency", "specificity constant", "kcat_km"],
}

_UNIT_HINTS = {
    "Km": frozenset({"mM", "μM", "uM", "M", "nM", "µM", "mmol", "umol"}),
    "Vmax": frozenset({"M/s", "mM/s", "μM/s", "uM/s", "nM/s", "M/min", "M h", "nM min", "M·s"}),
    "kcat": frozenset({"s⁻¹", "s-1", "min⁻¹", "min-1", "/s", "/min", "s^−1", "s−1"}),
    "kcat_Km": frozenset({"M⁻¹s⁻¹", "M-1s-1", "M⁻¹min⁻¹", "M-1min-1", "mM⁻¹s⁻¹"}),
}


def _extract_all_numbers_from_source(full_text: str):
    results = []
    chunks = re.split(r'(?<=[.!?])\s+', full_text)
    for chunk in chunks:
        if len(chunk) < 20:
            continue
        for m in re.finditer(r'([\d.]+)\s*[×x\u00d7]\s*10[\u207b\u2212\u2013\-]?\s*(\d+)', chunk):
            try:
                base = float(m.group(1))
                exp = int(m.group(2))
                neg = bool(re.search(r'10[\u207b\u2212\u2013\-]', m.group(0)))
                val = base * (10 ** -exp) if neg else base * (10 ** exp)
                results.append((val, chunk[:300]))
            except (ValueError, IndexError):
                pass
        for m in re.finditer(r'([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)', chunk):
            try:
                base = float(m.group(1))
                exp = int(m.group(2).replace('−', '-').replace('\u2212', '-'))
                val = base * (10 ** exp)
                results.append((val, chunk[:300]))
            except (ValueError, IndexError):
                pass
        for m in re.finditer(r'(?<!\d)(\d+\.?\d*)(?!\d)', chunk):
            try:
                val = float(m.group(1))
                results.append((val, chunk[:300]))
            except ValueError:
                pass
    return results


def _guess_unit_from_snippet(snippet: str, param: str) -> Optional[str]:
    hints = _UNIT_HINTS.get(param, set())
    sl = snippet.lower()
    for hint in sorted(hints, key=len, reverse=True):
        if hint.lower() in sl:
            return hint
    if param == "Km":
        m = re.search(r'(mM|μM|uM|M|nM|µM)', snippet)
        if m:
            return m.group(1)
    elif param == "Vmax":
        m = re.search(r'(M/s|mM/s|μM/s|uM/s|nM/s|M·s)', snippet, re.I)
        if m:
            return m.group(1)
    elif param in ("kcat", "kcat_Km"):
        m = re.search(r'(s⁻¹|s-1|min⁻¹|min-1|M⁻¹s⁻¹|M-1s-1)', snippet)
        if m:
            return m.group(1)
    return None


class FigureProcessor:
    def summarize(self, vlm_tasks: List[Dict], selected_name: str) -> Dict[str, Any]:
        summaries = []
        for vlm_task in vlm_tasks:
            caption = vlm_task.get("caption", "")
            fig_type = self._infer_figure_type(caption)
            mentions_selected = (selected_name or "").lower() in caption.lower()
            summaries.append({
                "caption": caption[:200],
                "figure_type": fig_type,
                "mentions_selected": mentions_selected,
            })
        return {
            "total": len(summaries),
            "summaries": summaries,
            "kinetics_figures": sum(1 for s in summaries if s["figure_type"] == "kinetics"),
            "morphology_figures": sum(1 for s in summaries if s["figure_type"] == "morphology"),
            "application_figures": sum(1 for s in summaries if s["figure_type"] == "application"),
        }

    def _infer_figure_type(self, caption: str) -> str:
        cl = caption.lower()
        if any(kw in cl for kw in ["kinetic", "michaelis", "lineweaver", "km", "vmax"]):
            return "kinetics"
        if any(kw in cl for kw in ["sem", "tem", "xrd", "morphology", "afm"]):
            return "morphology"
        if any(kw in cl for kw in ["detection", "sensing", "sensor", "lod", "calibration"]):
            return "application"
        return "other"


class LanguageRuleAdapter:
    def __init__(self, language: str = "en"):
        self.language = language

    def get_patterns(self, category: str):
        if self.language == "zh":
            return self._zh_patterns().get(category, [])
        return []

    def _zh_patterns(self):
        return {
            "enzyme_type": [
                ("类过氧化物酶", "peroxidase-like"),
                ("类氧化酶", "oxidase-like"),
                ("类过氧化氢酶", "catalase-like"),
                ("类超氧化物歧化酶", "superoxide-dismutase-like"),
            ],
            "kinetics": [
                ("Km", "Km", "mM"),
                ("米氏常数", "Km", "mM"),
                ("Vmax", "Vmax", "M/s"),
                ("最大反应速率", "Vmax", "M/s"),
            ],
        }


class RuleExtractor:
    def extract_from_evidence(self, record: Dict[str, Any], buckets: Dict[str, List[str]],
                              table_values: List[Dict], selected_name: str,
                              doc: PreprocessedDocument = None) -> Dict[str, Any]:
        if record["main_activity"]["enzyme_like_type"] is None:
            if doc and doc.hints:
                detected = doc.hints.get("detected_enzyme_types", [])
                if detected and isinstance(detected, list):
                    record["main_activity"]["enzyme_like_type"] = detected[0]
            if record["main_activity"]["enzyme_like_type"] is None:
                search_texts = (buckets.get("activity", []) + buckets.get("mechanism", [])
                                + buckets.get("kinetics", [])[:5]
                                + buckets.get("application", [])[:3])
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
            search_buckets = (buckets.get("activity", [])
                              + buckets.get("kinetics", [])[:10]
                              + buckets.get("mechanism", [])[:3])
            for text in search_buckets:
                for sub in _SUBSTRATE_KEYWORDS:
                    if sub.lower() in text.lower():
                        found.add(sub)
            if found:
                record["main_activity"]["substrates"] = sorted(found)

        all_kinetics_texts = buckets.get("kinetics", [])
        table_like_texts = []
        inline_texts = []
        for text in all_kinetics_texts:
            lines = text.strip().split('\n')
            pipe_count = sum(1 for line in lines if line.strip().startswith('|'))
            has_km_header = bool(re.search(r'Km\s*[\(（]', text, re.I))
            has_vmax_header = bool(re.search(r'Vmax\s*[\(（\[]', text, re.I))
            has_catalyst_header = bool(re.search(r'Catalyst|Nanozyme|Material', text[:200], re.I))
            is_table = (pipe_count >= 2) or (has_km_header and has_catalyst_header) or (has_vmax_header and has_catalyst_header)
            if is_table:
                table_like_texts.append(text)
            else:
                inline_texts.append(text)

        self._extract_kinetics_from_text(record, inline_texts)

        if record["main_activity"]["kinetics"]["Km"] is None or record["main_activity"]["kinetics"]["Vmax"] is None:
            self._extract_kinetics_from_flattened_table(record, table_like_texts, selected_name)

        if record["main_activity"]["kinetics"]["Km"] is None and table_values:
            self._extract_kinetics_from_table(record, table_values)

        self._extract_kcat_from_text(record, buckets.get("kinetics", []))
        self._extract_pH_profile(record, buckets)
        self._extract_temperature_profile(record, buckets)
        self._extract_synthesis_method(record, buckets.get("synthesis", []) + buckets.get("material", [])[:5] + buckets.get("characterization", [])[:3])
        self._extract_size_properties(record, buckets.get("material", []) + buckets.get("characterization", []) + buckets.get("synthesis", [])[:3])
        self._extract_physical_properties(record, buckets.get("characterization", []) + buckets.get("material", [])[:3])
        self._extract_morphology_from_text(record, buckets.get("characterization", []) + buckets.get("material", [])[:5])

        self._extract_applications_from_text(record, buckets.get("application", []))

        self._extract_mechanism(record, buckets.get("mechanism", []) + buckets.get("activity", []) + buckets.get("kinetics", [])[:5] + buckets.get("application", [])[:3])

        if doc:
            self._fulltext_fallback_extract(record, doc, selected_name)

        self._verifier_assisted_extract(record, doc, selected_name)

        return record

    def _verifier_assisted_extract(self, record, doc, selected_name):
        kin = record["main_activity"]["kinetics"]
        missing_params = []
        if kin.get("Km") is None:
            missing_params.append(("Km", "Km_unit"))
        if kin.get("Vmax") is None:
            missing_params.append(("Vmax", "Vmax_unit"))
        if kin.get("kcat") is None:
            missing_params.append(("kcat", "kcat_unit"))
        if kin.get("kcat_Km") is None:
            missing_params.append(("kcat_Km", "kcat_Km_unit"))

        if not missing_params or not doc:
            return

        full_text = " ".join(doc.chunks)
        all_numbers = _extract_all_numbers_from_source(full_text)

        for param, unit_field in missing_params:
            candidates = []
            title_lower = (doc.metadata.get("title", "") or "").lower()
            for num_val, snippet in all_numbers:
                has_unit = _guess_unit_from_snippet(snippet, param)
                if has_unit:
                    ratio = 0
                    if _KM_RANGES[0] <= num_val <= _KM_RANGES[1]:
                        ratio += 1
                    if selected_name.lower() in snippet.lower():
                        ratio += 2
                    for pkw in _PARAM_KEYWORDS.get(param, []):
                        if pkw.lower() in snippet.lower():
                            ratio += 3
                    if param == "Km" and title_lower and "kinetic" not in title_lower:
                        if "activity" in title_lower or "substrate" in title_lower:
                            ratio += 1
                    candidates.append((ratio, num_val, has_unit, snippet))

            if candidates:
                candidates.sort(key=lambda c: c[0], reverse=True)
                best = candidates[0]
                if best[0] >= 1:
                    kin[param] = best[1]
                    kin[f"{param}_unit"] = best[2]
                    kin[f"_evidence_{param}"] = best[3][:300]
                    kin["source"] = "verifier_fallback"
                    logger.info(
                        f"[SMN] Verifier fallback: {param}={best[1]} {best[2]} "
                        f"(regex missed, found via numeric search, score={best[0]})"
                    )

    _METHOD_PRIORITY = {
        "uv-vis": 1, "uv/vis": 1, "uv vis": 1, "absorption": 1,
        "spectrophotometric": 1,
        "fluorescence": 2, "fluorometric": 2,
        "colorimetric": 2, "colorimetry": 2,
        "electrochemical": 3, "amperometric": 3,
        "sers": 4, "surface-enhanced": 4, "raman": 4,
        "other": 5,
    }

    def _detect_kinetics_method(self, text: str) -> str:
        tl = text.lower()
        for key in self._METHOD_PRIORITY:
            if key in tl:
                return key
        return "other"

    def _extract_kinetics_from_text(self, record: Dict[str, Any], kinetics_texts: List[str]):
        _norm_unit = _normalize_unit_fn

        km_candidates = []
        vmax_candidates = []

        for text in kinetics_texts:
            norm_text = _normalize_ocr_scientific(text)
            method = self._detect_kinetics_method(text)
            method_pri = self._METHOD_PRIORITY.get(method, 5)
            matched_vmax = False

            for pat in _KM_VMAX_JOINT_PATTERNS:
                m = pat.search(norm_text)
                if not m:
                    m = pat.search(text)
                if m:
                    km_val = _parse_scientific_notation(m.group(1))
                    km_unit = m.group(2)
                    vmax_raw = m.group(3)
                    vmax_unit = m.group(4)
                    vmax_val = _parse_scientific_notation(vmax_raw)
                    if isinstance(km_val, (int, float)):
                        km_candidates.append((method_pri, km_val, km_unit, "text", text[:300]))
                    if isinstance(vmax_val, (int, float)):
                        vmax_candidates.append((method_pri, vmax_val, vmax_unit, "text", text[:300]))
                    break

            for pat in _KM_PATTERNS:
                m = pat.search(norm_text)
                if not m:
                    m = pat.search(text)
                if m:
                    groups = m.groups()
                    if len(groups) == 3:
                        if groups[0] in ("mM", "μM", "uM", "M", "mmol", "umol", "nmol"):
                            value, unit = groups[1], groups[0]
                        else:
                            try:
                                float(groups[0])
                                value, unit = groups[0], groups[2]
                            except (ValueError, TypeError):
                                try:
                                    float(groups[1])
                                    value, unit = groups[1], groups[2]
                                except (ValueError, TypeError):
                                    continue
                    elif len(groups) == 2:
                        value, unit = groups
                    else:
                        continue
                    try:
                        km_candidates.append((method_pri, float(value), unit, "text", text[:300]))
                    except ValueError:
                        pass
                    break

            for pat in _VMAX_PATTERNS:
                m = pat.search(norm_text)
                if not m:
                    m = pat.search(text)
                if m:
                    groups = m.groups()
                    if len(groups) == 2:
                        g0, g1 = groups
                        g0_is_unit = g0 in _RATE_UNITS or bool(re.match(r'10[−\-–]?\d*\s*M\s*[sS]', g0)) or bool(re.match(r'[mμunp]?M[·\s]*s[⁻\-–]1', g0))
                        g1_is_unit = g1 in _RATE_UNITS or bool(re.match(r'10[−\-–]?\d*\s*M\s*[sS]', g1)) or bool(re.match(r'[mμunp]?M[·\s]*s[⁻\-–]1', g1))
                        if g1_is_unit and not g0_is_unit:
                            value, unit = g0, g1
                        elif g0_is_unit:
                            value, unit = g1, g0
                        else:
                            value, unit = g0, None
                    elif len(groups) == 3:
                        value, unit = groups[1], groups[2]
                    else:
                        continue
                    vmax_val = _parse_scientific_notation(value.strip())
                    if isinstance(vmax_val, (int, float)):
                        vmax_candidates.append((method_pri, vmax_val, unit, "text", text[:300]))
                        matched_vmax = True
                    break

            if not matched_vmax:
                fallback = _extract_vmax_fallback(text)
                if fallback and isinstance(fallback.get("value"), (int, float)):
                    vmax_candidates.append((method_pri, fallback["value"], fallback.get("unit"), fallback.get("source", "text_ocr_fallback"), text[:300]))

        kin = record["main_activity"]["kinetics"]
        if km_candidates:
            km_candidates.sort(key=lambda c: c[0])
            best = km_candidates[0]
            if kin.get("Km") is None or best[0] < 5:
                kin["Km"] = best[1]
                _nu = _norm_unit(best[2]) if _norm_unit and best[2] else best[2]
                kin["Km_unit"] = _nu if _nu else best[2]
                kin["source"] = best[3]
                kin["_evidence_Km"] = best[4]
                if len(km_candidates) > 1:
                    logger.info(f"[SMN] Km multi-method: picked {best[1]} {best[2]} (method={best[0]}) from {len(km_candidates)} candidates")

        if vmax_candidates:
            vmax_candidates.sort(key=lambda c: (c[0], 0 if c[3] == "text" else 1))
            best = vmax_candidates[0]
            if kin.get("Vmax") is None or best[0] < 5 or (best[0] == 5 and best[3] == "text" and kin.get("source", "").endswith("fallback")):
                kin["Vmax"] = best[1]
                _nu = _norm_unit(best[2]) if _norm_unit and best[2] else best[2]
                kin["Vmax_unit"] = _nu if _nu else best[2]
                kin["source"] = best[3]
                kin["_evidence_Vmax"] = best[4]
                if len(vmax_candidates) > 1:
                    logger.info(f"[SMN] Vmax multi-method: picked {best[1]} {best[2]} (method={best[0]}) from {len(vmax_candidates)} candidates")

    def _extract_kinetics_from_flattened_table(self, record: Dict[str, Any],
                                                kinetics_texts: List[str],
                                                selected_name: str):
        _norm_unit = _normalize_unit_fn
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
            lines_raw = text.strip().split('\n')
            pipe_count = sum(1 for line in lines_raw if line.strip().startswith('|'))
            if pipe_count >= 2:
                lines = []
                for line in lines_raw:
                    stripped = line.strip()
                    if stripped.startswith('|'):
                        cells = [c.strip() for c in stripped.strip('|').split('|')]
                        lines.append('  '.join(cells))
                    elif stripped:
                        lines[-1] = lines[-1] + '  ' + stripped if lines else stripped
                if len(lines) < 2:
                    single_line = self._try_parse_inline_table(text, selected_name, record)
                    if single_line:
                        return
                    continue
            else:
                norm_text = _normalize_ocr_scientific(text)
                lines_raw = norm_text.strip().split('\n')
                if len(lines_raw) < 2:
                    single_line = self._try_parse_inline_table(text, selected_name, record)
                    if single_line:
                        return
                    continue
                lines = lines_raw

            header = lines[0]
            separator_idx = None
            for idx, line in enumerate(lines):
                if re.match(r'^\s*\|?\s*[-:]{3,}\s*[-:|\s]*$', line):
                    separator_idx = idx
                    break
            if separator_idx is not None:
                data_lines = lines[separator_idx + 1:]
            else:
                data_lines = lines[1:]
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

            for line in data_lines:
                parts = re.split(r'\s{2,}|\t', line.strip())
                if len(parts) < 2:
                    continue

                line_lower = line.lower()
                name_lower = (selected_name or "").lower().replace(" ", "").replace("-", "")
                name_original = (selected_name or "").lower()
                line_compact = line_lower.replace(" ", "").replace("-", "")

                is_match = (name_lower in line_compact or
                            name_original in line_lower or
                            "this work" in line_lower or
                            "our" in line_lower)

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
                            _nu = _norm_unit(km_unit) if _norm_unit and km_unit else km_unit
                            record["main_activity"]["kinetics"]["Km_unit"] = _nu if _nu else km_unit
                            record["main_activity"]["kinetics"]["source"] = "text"
                            record["main_activity"]["kinetics"]["_evidence_Km"] = text[:300]
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
                            _nu = _norm_unit(vmax_unit_raw) if _norm_unit and vmax_unit_raw else vmax_unit_raw
                            record["main_activity"]["kinetics"]["Vmax_unit"] = _nu if _nu else vmax_unit_raw
                            record["main_activity"]["kinetics"]["source"] = "text"
                            record["main_activity"]["kinetics"]["_evidence_Vmax"] = text[:300]
                        else:
                            norm_vmax = _normalize_ocr_scientific(raw_vmax)
                            vmax_parsed2 = _parse_scientific_notation(norm_vmax)
                            if isinstance(vmax_parsed2, (int, float)):
                                record["main_activity"]["kinetics"]["Vmax"] = vmax_parsed2
                                _nu = _norm_unit(vmax_unit_raw) if _norm_unit and vmax_unit_raw else vmax_unit_raw
                                record["main_activity"]["kinetics"]["Vmax_unit"] = _nu if _nu else vmax_unit_raw
                                record["main_activity"]["kinetics"]["source"] = "text"
                                record["main_activity"]["kinetics"]["_evidence_Vmax"] = text[:300]
                            else:
                                nums = _NUM_RE.findall(raw_vmax)
                                if nums:
                                    try:
                                        record["main_activity"]["kinetics"]["Vmax"] = float(nums[0])
                                    except ValueError:
                                        record["main_activity"]["kinetics"]["Vmax"] = raw_vmax
                                    _nu = _norm_unit(vmax_unit_raw) if _norm_unit and vmax_unit_raw else vmax_unit_raw
                                    record["main_activity"]["kinetics"]["Vmax_unit"] = _nu if _nu else vmax_unit_raw
                                    record["main_activity"]["kinetics"]["source"] = "text"
                                    record["main_activity"]["kinetics"]["_evidence_Vmax"] = text[:300]

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

    def _try_parse_inline_table(self, text: str, selected_name: str,
                                 record: Dict[str, Any]) -> bool:
        _norm_unit = _normalize_unit_fn
        km_header_m = re.search(r'Km\s*[\(（]\s*(mM|μM|uM|M|mmol|umol|nmol)\s*[\)）]', text, re.I)
        vmax_header_m = re.search(r'Vmax\s*[\(（\[]\s*([^\)）\]]+?)\s*[\)）\]]', text, re.I)
        if not km_header_m and not vmax_header_m:
            return False

        km_unit = km_header_m.group(1) if km_header_m else None
        vmax_unit = vmax_header_m.group(1).strip() if vmax_header_m else None

        header_end = max(km_header_m.end() if km_header_m else 0,
                         vmax_header_m.end() if vmax_header_m else 0)
        data_part = text[header_end:].strip()

        name_lower = (selected_name or "").lower()
        name_variants = [name_lower]
        name_variants.append(name_lower.replace(" ", ""))
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

        substrate_m = re.match(r'(?:' + re.escape(selected_name) + r'|[\w\s]*?this work)\s+(\w+)\s+', after_catalyst, re.I)
        substrate = substrate_m.group(1) if substrate_m else None

        nums = re.findall(r'([\d.]+)', after_catalyst)
        if len(nums) >= 2:
            if vmax_header_m and km_header_m:
                try:
                    vmax_val = float(nums[0])
                    km_val = float(nums[1])
                    record["main_activity"]["kinetics"]["Km"] = km_val
                    _nu = _norm_unit(km_unit) if _norm_unit and km_unit else km_unit
                    record["main_activity"]["kinetics"]["Km_unit"] = _nu if _nu else km_unit
                    record["main_activity"]["kinetics"]["Vmax"] = vmax_val
                    _nu = _norm_unit(vmax_unit) if _norm_unit and vmax_unit else vmax_unit
                    record["main_activity"]["kinetics"]["Vmax_unit"] = _nu if _nu else vmax_unit
                    record["main_activity"]["kinetics"]["source"] = "text"
                    record["main_activity"]["kinetics"]["_evidence_Km"] = text[:300]
                    record["main_activity"]["kinetics"]["_evidence_Vmax"] = text[:300]
                    if substrate:
                        record["main_activity"]["kinetics"]["substrate"] = substrate
                    return True
                except ValueError:
                    pass
            elif km_header_m:
                try:
                    km_val = float(nums[0])
                    record["main_activity"]["kinetics"]["Km"] = km_val
                    _nu = _norm_unit(km_unit) if _norm_unit and km_unit else km_unit
                    record["main_activity"]["kinetics"]["Km_unit"] = _nu if _nu else km_unit
                    record["main_activity"]["kinetics"]["source"] = "text"
                    record["main_activity"]["kinetics"]["_evidence_Km"] = text[:300]
                    if substrate:
                        record["main_activity"]["kinetics"]["substrate"] = substrate
                    return True
                except ValueError:
                    pass
        return False

    def _extract_kinetics_from_table(self, record: Dict[str, Any], table_values: List[Dict]):
        _norm_unit = _normalize_unit_fn
        for val in table_values:
            param = val.get("parameter", "")
            source = val.get("source", "table")
            if param == "Km" and record["main_activity"]["kinetics"]["Km"] is None:
                raw_val = val["value"]
                parsed = _parse_scientific_notation(str(raw_val))
                if isinstance(parsed, (int, float)):
                    record["main_activity"]["kinetics"]["Km"] = parsed
                    _nu = _norm_unit(val.get("unit")) if _norm_unit and val.get("unit") else val.get("unit")
                    record["main_activity"]["kinetics"]["Km_unit"] = _nu if _nu else val.get("unit")
                    record["main_activity"]["kinetics"]["substrate"] = val.get("substrate")
                    record["main_activity"]["kinetics"]["source"] = source
                    record["main_activity"]["kinetics"]["_evidence_Km"] = val.get("original_text") or val.get("evidence_text") or str(val)[:300]
            elif param == "Vmax" and record["main_activity"]["kinetics"]["Vmax"] is None:
                raw_val = val["value"]
                parsed = _parse_scientific_notation(str(raw_val))
                if isinstance(parsed, (int, float)):
                    record["main_activity"]["kinetics"]["Vmax"] = parsed
                else:
                    record["main_activity"]["kinetics"]["Vmax"] = raw_val
                _nu = _norm_unit(val.get("unit")) if _norm_unit and val.get("unit") else val.get("unit")
                record["main_activity"]["kinetics"]["Vmax_unit"] = _nu if _nu else val.get("unit")
                record["main_activity"]["kinetics"]["source"] = source
                record["main_activity"]["kinetics"]["_evidence_Vmax"] = val.get("original_text") or val.get("evidence_text") or str(val)[:300]
            elif param in ("kcat", "Kcat", "k_cat") and record["main_activity"]["kinetics"]["kcat"] is None:
                try:
                    parsed = _parse_scientific_notation(str(val["value"]))
                    if isinstance(parsed, (int, float)):
                        record["main_activity"]["kinetics"]["kcat"] = parsed
                        _raw_u = val.get("unit", "s^-1")
                        _nu = _norm_unit(_raw_u) if _norm_unit and _raw_u else _raw_u
                        record["main_activity"]["kinetics"]["kcat_unit"] = _nu if _nu else _raw_u
                        record["main_activity"]["kinetics"]["source"] = source
                        record["main_activity"]["kinetics"]["_evidence_kcat"] = val.get("original_text") or val.get("evidence_text") or str(val)[:300]
                except (ValueError, TypeError):
                    pass
            elif param in ("kcat/Km", "kcat_Km", "Kcat/Km", "catalytic_efficiency") and record["main_activity"]["kinetics"]["kcat_Km"] is None:
                try:
                    parsed = _parse_scientific_notation(str(val["value"]))
                    if isinstance(parsed, (int, float)):
                        record["main_activity"]["kinetics"]["kcat_Km"] = parsed
                        _raw_u = val.get("unit", "M^-1 s^-1")
                        _nu = _norm_unit(_raw_u) if _norm_unit and _raw_u else _raw_u
                        record["main_activity"]["kinetics"]["kcat_Km_unit"] = _nu if _nu else _raw_u
                        record["main_activity"]["kinetics"]["source"] = source
                        record["main_activity"]["kinetics"]["_evidence_kcat_Km"] = val.get("original_text") or val.get("evidence_text") or str(val)[:300]
                except (ValueError, TypeError):
                    pass

    def _extract_kcat_from_text(self, record: Dict[str, Any], kinetics_texts: List[str]):
        _norm_unit = _normalize_unit_fn
        for text in kinetics_texts:
            norm_text = _normalize_ocr_scientific(text)
            if record["main_activity"]["kinetics"]["kcat"] is None:
                for pat in _KCAT_PATTERNS:
                    m = pat.search(norm_text)
                    if not m:
                        m = pat.search(text)
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
                            _nu = _norm_unit(unit) if _norm_unit and unit else unit
                            record["main_activity"]["kinetics"]["kcat_unit"] = _nu if _nu else unit
                            record["main_activity"]["kinetics"]["_evidence_kcat"] = text[:300]
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
                            _nu = _norm_unit("s^-1") if _norm_unit else "s^-1"
                            record["main_activity"]["kinetics"]["kcat_unit"] = _nu if _nu else "s^-1"
                            record["main_activity"]["kinetics"]["_evidence_kcat"] = text[:300]
                            logger.info(f"[SMN] kcat parsed from E-notation: {base}e{exp} = {kcat_val:.2e}")
                    except (ValueError, TypeError):
                        pass

            if record["main_activity"]["kinetics"]["kcat_Km"] is None:
                for pat in _KCAT_KM_PATTERNS:
                    m = pat.search(norm_text)
                    if not m:
                        m = pat.search(text)
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
                            _nu = _norm_unit(unit) if _norm_unit and unit else unit
                            record["main_activity"]["kinetics"]["kcat_Km_unit"] = _nu if _nu else unit
                            record["main_activity"]["kinetics"]["_evidence_kcat_Km"] = text[:300]
                            break

            if record["main_activity"]["kinetics"]["kcat_Km"] is None:
                e_m = re.search(r'\bkcat\s*/\s*Km\b[^.=]{0,20}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)', norm_text, re.I)
                if not e_m:
                    e_m = re.search(r'\bkcat\s*/\s*Km\b[^.=]{0,20}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)', text, re.I)
                if e_m:
                    try:
                        base = float(e_m.group(1))
                        exp = int(e_m.group(2).replace('−', '-').replace('\u2212', '-'))
                        kcat_km_val = base * (10 ** exp)
                        if 1e0 <= kcat_km_val <= 1e12:
                            record["main_activity"]["kinetics"]["kcat_Km"] = kcat_km_val
                            _nu = _norm_unit("M^-1 s^-1") if _norm_unit else "M^-1 s^-1"
                            record["main_activity"]["kinetics"]["kcat_Km_unit"] = _nu if _nu else "M^-1 s^-1"
                            record["main_activity"]["kinetics"]["_evidence_kcat_Km"] = text[:300]
                            logger.info(f"[SMN] kcat/Km parsed from E-notation: {base}e{exp} = {kcat_km_val:.2e}")
                    except (ValueError, TypeError):
                        pass

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
                            _nu = _norm_unit("M^-1 s^-1") if _norm_unit else "M^-1 s^-1"
                            record["main_activity"]["kinetics"]["kcat_Km_unit"] = _nu if _nu else "M^-1 s^-1"
                            record["main_activity"]["kinetics"]["_evidence_kcat_Km"] = text[:300]
                            logger.info(f"[SMN] kcat/Km from catalytic efficiency E-notation: {base}e{exp} = {kcat_km_val:.2e}")
                    except (ValueError, TypeError):
                        pass

        if record["main_activity"]["kinetics"]["kcat"] is None:
            kcat_km = record["main_activity"]["kinetics"].get("kcat_Km")
            km = record["main_activity"]["kinetics"].get("Km")
            km_unit = record["main_activity"]["kinetics"].get("Km_unit", "")
            kcat_km_unit = record["main_activity"]["kinetics"].get("kcat_Km_unit", "")
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
                    logger.info(f"[SMN] kcat derived from kcat/Km={kcat_km:.2e} * Km={km} {km_unit} = {kcat_val:.2e} s^-1")

    def _extract_pH_profile(self, record: Dict[str, Any], buckets):
        ph_profile = record["main_activity"].get("pH_profile", {})
        if not isinstance(ph_profile, dict):
            ph_profile = {}
            record["main_activity"]["pH_profile"] = ph_profile

        if isinstance(buckets, dict):
            search_texts = (
                buckets.get("activity", [])
                + buckets.get("kinetics", [])
                + buckets.get("application", [])[:5]
                + record.get("raw_supporting_text", {}).get("kinetics", [])[:5]
            )
        else:
            search_texts = list(buckets) + record.get("raw_supporting_text", {}).get("kinetics", [])[:5]

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

        # 2. 动力学实验条件中的pH（只记录为conditions，不标记为optimal_pH）
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

        if ph_profile.get("pH_range") is None:
            for text in search_texts:
                for pat in _PH_PATTERNS["pH_range"]:
                    m = pat.search(text)
                    if m:
                        ph_profile["pH_range"] = f"{m.group(1)}-{m.group(2)}"
                        break
                if ph_profile.get("pH_range") is not None:
                    break

    def _extract_temperature_profile(self, record: Dict[str, Any], buckets):
        temp_profile = record["main_activity"].get("temperature_profile", {})
        if not isinstance(temp_profile, dict):
            temp_profile = {}
            record["main_activity"]["temperature_profile"] = temp_profile

        if isinstance(buckets, dict):
            search_texts = (
                buckets.get("activity", [])
                + buckets.get("kinetics", [])
                + buckets.get("application", [])[:5]
                + record.get("raw_supporting_text", {}).get("kinetics", [])[:5]
            )
        else:
            search_texts = list(buckets) + record.get("raw_supporting_text", {}).get("kinetics", [])[:5]

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
            _TEMP_OPTIMAL_FALLBACK = [
                re.compile(r'\boptimal\s+(?:reaction\s+)?temperature\s*(?:was|=|:|of)\s*([\d.]+)\s*°?\s*C', re.I),
                re.compile(r'\b(?:reaction\s+)?temperature\s*(?:was|=|:)\s*([\d.]+)\s*°?C', re.I),
                re.compile(r'\b(?:at|under)\s*([\d.]+)\s*°?\s*C\b', re.I),
                re.compile(r'\bincubat\w*\s+(?:at\s+)?([\d.]+)\s*°?\s*C', re.I),
                re.compile(r'\b([\d.]+)\s*°\s*C\b', re.I),
            ]
            for text, norm in zip(search_texts, norm_texts):
                if re.search(r'\b(?:optimal|optimum|dependent|effect|range|profile)\s+(?:of\s+)?temperature\b|\btemperature\s+(?:dependent|effect|range|profile|optimum|optimal|reaction)\b', text, re.I):
                    _TEMP_CONTEXT_PATTERNS = [
                        re.compile(r'\b(?:reaction\s+)?temperature\s*(?:was|=|:)\s*([\d.]+)\s*°?C', re.I),
                        re.compile(r'\b(?:at|under)\s*([\d.]+)\s*°?\s*C\b', re.I),
                        re.compile(r'\b([\d.]+)\s*°\s*C\b', re.I),
                    ]
                    for pat in _TEMP_CONTEXT_PATTERNS:
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

        # 3. 动力学实验条件中的温度（只记录为conditions）
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

    def _extract_synthesis_method(self, record: Dict[str, Any], synthesis_texts: List[str]):
        sel = record.get("selected_nanozyme", {})
        if not isinstance(sel, dict):
            return

        if sel.get("synthesis_method") is None:
            method_scores: Dict[str, float] = {}
            for text in synthesis_texts:
                for method_name, pattern in _SYNTHESIS_METHODS.items():
                    if pattern.search(text):
                        weight = 0.1 if method_name == "general_synthesis" else 1.0
                        score = method_scores.get(method_name, 0) + weight
                        method_scores[method_name] = score
            if method_scores:
                non_generic = {k: v for k, v in method_scores.items() if k != "general_synthesis"}
                if non_generic:
                    best_method = max(non_generic, key=non_generic.get)
                else:
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

        if synth_cond.get("pH") is None:
            for text in synthesis_texts:
                for pat in _SYNTHESIS_CONDITION_PATTERNS.get("pH", []):
                    m = pat.search(text)
                    if m:
                        synth_cond["pH"] = m.group(1)
                        break
                if synth_cond.get("pH"):
                    break

        if not synth_cond.get("solvent"):
            for text in synthesis_texts:
                for pat in _SYNTHESIS_CONDITION_PATTERNS.get("solvent", []):
                    m = pat.search(text)
                    if m:
                        raw = m.group(1).strip()
                        if raw.lower() not in ("the", "a", "an", "this"):
                            synth_cond["solvent"] = raw
                        break
                if synth_cond.get("solvent"):
                    break

    def _extract_size_properties(self, record: Dict[str, Any], material_texts: List[str]):
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
                        groups = m.groups()
                        all_digits = [g for g in groups if g and re.match(r'^\d{3}$', g)]
                        if all_digits:
                            sel["crystal_structure"] = ", ".join(f"({p})" for p in all_digits)
                        elif m.lastindex and m.group(1):
                            raw = m.group(1).strip()
                            if re.match(r'^[\d\s,.\u00c5]+$', raw):
                                continue
                            elif re.match(r'^[\d\s,]+$', raw):
                                planes = re.findall(r'\d{3}', raw)
                                if planes:
                                    sel["crystal_structure"] = ", ".join(f"({p})" for p in planes)
                            else:
                                sel["crystal_structure"] = raw.lower()
                        else:
                            match_text = m.group(0).lower()
                            for struct_name in ("spinel", "perovskite", "fluorite", "cubic",
                                               "tetragonal", "hexagonal", "orthorhombic",
                                               "monoclinic", "amorphous", "crystalline",
                                               "anatase", "rutile", "brookite",
                                               "rock salt", "zinc blende", "wurtzite",
                                               "graphitic", "face-centered cubic",
                                               "body-centered cubic"):
                                if struct_name in match_text:
                                    sel["crystal_structure"] = struct_name
                                    break
                            if sel.get("crystal_structure") is None:
                                planes = re.findall(r'\((\d{3})\)', m.group(0))
                                if planes:
                                    sel["crystal_structure"] = ", ".join(f"({p})" for p in planes)
                        break
                if sel.get("crystal_structure"):
                    break

    def _extract_physical_properties(self, record: Dict[str, Any], char_texts: List[str]):
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
        "nanoplate", "nanoplates", "nanobelt", "nanobelts",
        "nanocage", "nanocages", "nanoframe", "nanoframes",
        "nanobranch", "nanobranches", "nanotripod", "nanotetrapod",
        "nanopyramid", "nanopyramids", "nanocone", "nanocones",
        "nanocauliflower", "nanobouquet",
        "nanocoral", "nanosponge", "nanomesh",
        "quantum dot", "quantum dots", "QD", "QDs",
        "2D", "3D", "1D",
        "hollow", "mesostructured", "hierarchical",
        "tetrahedr", "hexagonal prism", "bipyramid",
        "sea-urchin", "sea urchin",
        "foam-like", "aerogel", "hydrogel",
        "MOF-derived", "prussian blue analogue",
    ]

    _MORPHOLOGY_PHRASE_PATTERNS = [
        re.compile(r'(?:uniform|regular|monodisperse|well-defined|well-defined)\s+((?:hollow|solid|mesoporous|porous|core-shell|yolk-shell)\s+)?((?:polyhedral|spherical|cubical|rod-like|sheet-like|flower-like|dendritic|branched|needle-like|spindle|ellipsoidal|prismatic|hexagonal|tetragonal)\s+)?(?:morphology|shape|structure|nanostructure)', re.I),
        re.compile(r'(?:exhibits?|shows?|displays?|possesses?|has|with)\s+(?:a\s+|an\s+)?((?:hollow|solid|mesoporous|porous|core-shell|yolk-shell|uniform|regular)\s+)?((?:polyhedral|spherical|cubical|rod-like|sheet-like|flower-like|dendritic|branched|needle-like|spindle|ellipsoidal|prismatic|hexagonal|tetragonal)\s+)?morphology', re.I),
        re.compile(r'(?:morphology|shape|structure)\s+(?:of\s+(?:the\s+)?)?(?:\S+\s+){0,3}(?:is|was|are|were)\s+(?:found\s+to\s+be\s+)?(?:a\s+|an\s+)?((?:hollow|solid|mesoporous|porous|core-shell|yolk-shell|uniform|regular|well-defined)\s+)?((?:polyhedral|spherical|cubical|rod-like|sheet-like|flower-like|dendritic|branched|needle-like|spindle|ellipsoidal|prismatic|hexagonal|tetragonal)\s+)?', re.I),
    ]

    def _extract_morphology_from_text(self, record, char_texts):
        sel = record.get("selected_nanozyme", {})
        if not isinstance(sel, dict):
            return
        if sel.get("morphology"):
            return
        selected_name = (sel.get("name") or "").lower()

        phrase_match = None
        for text in char_texts:
            tl = text.lower()
            has_name = selected_name and selected_name in tl
            is_caption = "figure" in tl or "fig." in tl or "tem " in tl or "sem " in tl or "hrtem" in tl or "afm" in tl
            if not (has_name or is_caption):
                continue
            for pat in self._MORPHOLOGY_PHRASE_PATTERNS:
                m = pat.search(text)
                if m:
                    parts = [g.strip() for g in m.groups() if g and g.strip()]
                    if parts:
                        phrase_match = " ".join(parts).rstrip()
                        break
            if phrase_match:
                break

        term_scores = {}
        for text in char_texts:
            tl = text.lower()
            has_name = selected_name and selected_name in tl
            is_caption = "figure" in tl or "fig." in tl or "tem " in tl or "sem " in tl or "hrtem" in tl or "afm" in tl
            weight = 3 if (has_name and is_caption) else (2 if has_name else (2 if is_caption else 1))
            for term in self._MORPHOLOGY_TERMS:
                if term in tl:
                    term_scores[term] = term_scores.get(term, 0) + weight
        if term_scores:
            sorted_terms = sorted(term_scores.items(), key=lambda x: -x[1])
            top_score = sorted_terms[0][1]
            selected = [t for t, s in sorted_terms if s >= top_score * 0.5][:3]
            if phrase_match:
                sel["morphology"] = phrase_match
            else:
                sel["morphology"] = ", ".join(selected)

    def _fulltext_fallback_extract(self, record, doc, selected_name):
        all_text = "\n".join(doc.chunks) if doc.chunks else ""
        if not all_text:
            return

        norm_text = _normalize_ocr_scientific(all_text)

        sel = record.get("selected_nanozyme", {})
        act = record.get("main_activity", {})
        kin = act.get("kinetics", {})
        ph_prof = act.get("pH_profile", {})
        temp_prof = act.get("temperature_profile", {})

        if ph_prof.get("optimal_pH") is None:
            for pat in _PH_PATTERNS["optimal_pH"]:
                m = pat.search(all_text)
                if not m:
                    m = pat.search(norm_text)
                if m:
                    try:
                        val = float(m.group(1))
                        if 0 <= val <= 14:
                            ph_prof["optimal_pH"] = val
                            logger.info(f"[SMN] Fulltext fallback: optimal_pH={val}")
                            break
                    except (ValueError, IndexError):
                        pass

        if temp_prof.get("optimal_temperature") is None:
            for pat in _TEMPERATURE_PATTERNS["optimal_temperature"]:
                m = pat.search(all_text)
                if not m:
                    m = pat.search(norm_text)
                if m:
                    temp_prof["optimal_temperature"] = f"{m.group(1)} °C"
                    logger.info(f"[SMN] Fulltext fallback: optimal_temperature={m.group(1)}°C")
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
            term_scores = {}
            tl = all_text.lower()
            for chunk in (doc.chunks or []):
                cl = chunk.lower()
                has_name = selected_name and selected_name.lower() in cl
                is_caption = "figure" in cl or "fig." in cl or "tem " in cl or "sem " in cl or "hrtem" in cl
                weight = 3 if (has_name and is_caption) else (2 if has_name else (2 if is_caption else 1))
                for term in self._MORPHOLOGY_TERMS:
                    if term in cl:
                        term_scores[term] = term_scores.get(term, 0) + weight
            if term_scores:
                sorted_terms = sorted(term_scores.items(), key=lambda x: -x[1])
                top_score = sorted_terms[0][1]
                selected = [t for t, s in sorted_terms if s >= top_score * 0.5][:3]
                sel["morphology"] = ", ".join(selected)
                logger.info(f"[SMN] Fulltext fallback: morphology={sel['morphology']}")

        if sel.get("crystal_structure") is None:
            for pat in _CRYSTAL_STRUCTURE_PATTERNS:
                m = pat.search(all_text)
                if m:
                    groups = m.groups()
                    all_digits = [g for g in groups if g and re.match(r'^\d{3}$', g)]
                    if all_digits:
                        sel["crystal_structure"] = ", ".join(f"({p})" for p in all_digits)
                    elif m.lastindex and m.group(1):
                        raw = m.group(1).strip()
                        if re.match(r'^[\d\s,]+$', raw):
                            planes = re.findall(r'\d{3}', raw)
                            if planes:
                                sel["crystal_structure"] = ", ".join(f"({p})" for p in planes)
                        else:
                            sel["crystal_structure"] = raw.lower()
                    else:
                        match_text = m.group(0).lower()
                        for struct_name in ("spinel", "perovskite", "fluorite", "cubic",
                                           "tetragonal", "hexagonal", "orthorhombic",
                                           "monoclinic", "amorphous", "crystalline",
                                           "anatase", "rutile", "brookite"):
                            if struct_name in match_text:
                                sel["crystal_structure"] = struct_name
                                break
                        if sel.get("crystal_structure") is None:
                            planes = re.findall(r'\((\d{3})\)', m.group(0))
                            if planes:
                                sel["crystal_structure"] = ", ".join(f"({p})" for p in planes)
                    logger.info(f"[SMN] Fulltext fallback: crystal_structure={sel.get('crystal_structure')}")
                    break

        if not kin.get("Km") and not kin.get("Vmax"):
            for pat in _KM_PATTERNS:
                m = pat.search(norm_text)
                if m:
                    try:
                        km_val = m.group(1)
                        km_unit = m.group(2) if m.lastindex and m.lastindex >= 2 else "mM"
                        kin["Km"] = f"{km_val} {km_unit}"
                        logger.info(f"[SMN] Fulltext fallback: Km={km_val} {km_unit}")
                        break
                    except (IndexError, ValueError):
                        pass
            for pat in _VMAX_PATTERNS:
                m = pat.search(norm_text)
                if m:
                    try:
                        vmax_val = m.group(1)
                        vmax_unit = m.group(2) if m.lastindex and m.lastindex >= 2 else "M/s"
                        kin["Vmax"] = f"{vmax_val} {vmax_unit}"
                        logger.info(f"[SMN] Fulltext fallback: Vmax={vmax_val} {vmax_unit}")
                        break
                    except (IndexError, ValueError):
                        pass

        if act.get("enzyme_like_type") is None:
            for pat, etype in _ENZYME_TYPE_PATTERNS:
                if pat.search(all_text):
                    act["enzyme_like_type"] = etype
                    logger.info(f"[SMN] Fulltext fallback: enzyme_type={etype}")
                    break

        if act.get("mechanism") is None:
            for pat, mech in self._MECHANISM_PATTERNS:
                if pat.search(all_text):
                    act["mechanism"] = mech
                    logger.info(f"[SMN] Fulltext fallback: mechanism={mech}")
                    break

        if not record.get("applications"):
            apps_found = []
            tl = all_text.lower()
            for app_type, keywords in self._APP_TYPE_KEYWORDS.items():
                for kw in keywords:
                    if kw.lower() in tl:
                        apps_found.append(app_type)
                        break
            if apps_found:
                app = {"application_type": apps_found[0]}
                for pat in _LOD_PATTERNS:
                    m = pat.search(norm_text)
                    if m:
                        try:
                            app["LOD"] = f"{m.group(1)} {m.group(2)}"
                            break
                        except (IndexError, ValueError):
                            pass
                for pat in _ANALYTE_PATTERNS:
                    m = pat.search(all_text)
                    if m:
                        try:
                            raw_analyte = m.group(1).strip()
                            from application_extractor import is_valid_analyte
                            if is_valid_analyte(raw_analyte):
                                app["analyte"] = raw_analyte
                            break
                        except (IndexError, ValueError):
                            pass
                for pat in _LINEAR_RANGE_PATTERNS:
                    m = pat.search(norm_text)
                    if m:
                        try:
                            app["linear_range"] = f"{m.group(1)} {m.group(2)}"
                            break
                        except (IndexError, ValueError):
                            pass
                record["applications"] = [app]
                logger.info(f"[SMN] Fulltext fallback: applications={apps_found}")

        act["pH_profile"] = ph_prof
        act["temperature_profile"] = temp_prof

    _APP_TYPE_KEYWORDS = {
        "sensing": ["detection", "sensing", "sensor", "biosensor", "assay", "monitoring", "determin",
                    "biosensing", "imaging", "point-of-care", "poc", "diagnos", "theranost", "biomarker",
                    "elisa", "immunoassay", "lateral flow", "paper-based",
                    "colorimetric", "fluorometric", "electrochemical", "chemiluminescent",
                    "ratiometric", "turn-on", "turn-off", "selective detection", "sensitive detection"],
        "therapeutic": ["therapeutic", "antitumor", "wound heal", "cytoprotect",
                        "neuroprotect", "anti-inflammator", "antiinflammator", "therapy",
                        "catalytic therapy", "tumor therapy", "tumor ablation",
                        "photothermal therapy", "sonodynamic therapy", "chemodynamic therapy",
                        "photodynamic therapy", "immunotherapy", "gene therapy",
                        "synergistic therapy", "combination therapy", "chemo-therapy",
                        "radiotherapy", "magnetotherapy", "starvation therapy"],
        "antibacterial": ["antibacterial", "disinfect", "steriliz", "bactericid", "antimicrobial",
                          "anti-bacterial", "antiviral", "antifungal",
                          "wound infection", "bacterial killing", "membrane disruption"],
        "environmental": ["pollutant", "heavy metal", "pesticide", "organophosph", "endocrine",
                          "degrad", "environmental", "drinking water", "waste water", "river",
                          "lake", "tap water", "sea water", "environmental remediation",
                          "water purification", "soil remediation", "air purification",
                          "organic pollutant", "dye degrad", "antibiotic removal"],
        "antioxidant": ["antioxidant", "ros scaveng", "radical scaveng", "cytoprotect",
                        "oxidative stress", "anti-oxid", "radioprotect",
                        "cell protection", "inflammation reduction"],
        "biofilm_inhibition": ["biofilm", "anti-biofilm", "antibiofilm", "quorum sensing inhibition"],
        "food_safety": ["food safety", "food quality", "food contaminant", "foodborne",
                        "mycotoxin", "aflatoxin", "patulin", "ochratoxin",
                        "food additive", "food preserv"],
        "drug_delivery": ["drug delivery", "drug release", "nanocarrier", "controlled release",
                          "stimuli-responsive", "ph-responsive", "thermo-responsive"],
    }

    _ANALYTE_PATTERNS = [
        re.compile(r'\b(?:detection\s+(?:of|for)|sensing\s+(?:of|for)|determin(?:ation|ing)\s+(?:of|for))\s+([\w\-]+(?:\s[\w\-]+){0,3})', re.I),
        re.compile(r'\b(?:glucose|cholesterol|uric\s+acid|lactate|ascorbic\s+acid|dopamine|cysteine|glutathione|bilirubin)\b', re.I),
        re.compile(r'\b(?:Hg[\s2]*\+{1,2}|Pb[\s2]*\+{1,2}|Cd[\s2]*\+{1,2}|Cu[\s2]*\+{1,2}|Fe[\s3]*\+{1,2}|Cr\s*[Vv][Ii]+|As\s*[Vv][Ii]+)\b', re.I),
        re.compile(r'\b(?:xanthine|hypoxanthine|acetylcholine|choline|urea|hydrogen\s+peroxide|H2O2|phenol|bisphenol|catechol|hydroquinone)\b', re.I),
        re.compile(r'\b(?:mercury|lead|cadmium|arsenic|chromium)\b', re.I),
        re.compile(r'\b(?:sensing|detecting|monitoring)\s+(?:of\s+)?([\w\-]+(?:\s[\w\-]+){0,2})', re.I),
        re.compile(r'\b(?:thrombin|lysozyme|trypsin|urease|horseradish|HRP|BSA|albumin)\b', re.I),
        re.compile(r'\b(?:nitrofurantoin|chloramphenicol|tetracycline|kanamycin|gentamicin|ampicillin)\b', re.I),
        re.compile(r'\b(?:malathion|paraoxon|chlorpyrifos|diazinon|atrazine|simazine)\b', re.I),
        re.compile(r'\b(?:microcystin|okadaic\s+acid|saxitoxin|brevetoxin)\b', re.I),
        re.compile(r'\b(?:alpha-fetoprotein|AFP|CEA|PSA|CA[-\s]?125|CA[-\s]?19[-\s]?9)\b', re.I),
        re.compile(r'\b(?:miRNA|microRNA|DNA|mRNA|aptamer)\b', re.I),
        re.compile(r'\b(?:E\.?\s*coli|S\.?\s*aureus|Salmonella|Listeria|Staphylococcus)\b', re.I),
        re.compile(r'\b(?:cancer\s+cell|tumor\s+cell|HeLa|MCF[-\s]?7|HepG2|A549)\b', re.I),
        re.compile(r'\b(?:sucrose|maltose|fructose|lactose|galactose)\b', re.I),
        re.compile(r'\b(?:ethanol|methanol|formaldehyde|acetaldehyde)\b', re.I),
        re.compile(r'\b(?:nitrite|nitrate|ammonia|ammonium|phosphate)\b', re.I),
        re.compile(r'\b(?:sulfide|sulfite|sulfate|thiosulfate)\b', re.I),
        re.compile(r'\b(?:hypochlorite|chlorite|chlorate|perchlorate)\b', re.I),
        re.compile(r'\b(?:iodide|bromide|fluoride)\b', re.I),
        re.compile(r'\b(?:iron|zinc|cobalt|nickel|manganese|aluminum|silver|gold|platinum|palladium)\s+(?:ion|I{0,2}V{0,2})\b', re.I),
        re.compile(r'\b(?:Fe|Zn|Co|Ni|Mn|Al|Ag|Au|Pt|Pd|Cu|Cr|Ce|Ti|Sn|Pb|Hg|Cd)\s*[\d]*\s*\+{1,2}\b', re.I),
        re.compile(r'\b(?:BPA|bisphenol\s*A|endocrine\s+disruptor)\b', re.I),
        re.compile(r'\b(?:organophosph(?:ate|orus)|pesticide|insecticide|herbicide|fungicide)\b', re.I),
        re.compile(r'\b(?:antibiotic|drug|pharmaceutical)\b', re.I),
        re.compile(r'\b(?:ciprofloxacin|ofloxacin|norfloxacin|enrofloxacin)\b', re.I),
        re.compile(r'\b(?:rifampicin|isoniazid|pyrazinamide|ethambutol)\b', re.I),
        re.compile(r'\b(?:doxorubicin|daunorubicin|epirubicin)\b', re.I),
        re.compile(r'\b(?:hydrogen\s+sulfide|H2S|carbon\s+monoxide|CO|nitric\s+oxide|NO)\b', re.I),
        re.compile(r'\b(?:superoxide|O2|singlet\s+oxygen|hydroxyl\s+radical)\b', re.I),
        re.compile(r'\b(?:pH|dissolved\s+oxygen|DO|ORP|redox\s+potential)\b', re.I),
        re.compile(r'\b(?:creatine|creatinine|urea|BUN)\b', re.I),
        re.compile(r'\b(?:progesterone|testosterone|estradiol|estrogen|cortisol)\b', re.I),
        re.compile(r'\b(?:vitamin\s+[A-Z]|thiamine|riboflavin|niacin|folate|folic\s+acid)\b', re.I),
        re.compile(r'\b(?:mycotoxin|aflatoxin|ochratoxin|deoxynivalenol|fumonisin|zearalenone|T-2)\b', re.I),
    ]

    _SAMPLE_TYPE_MAP = {
        "serum": "serum", "plasma": "plasma", "urine": "urine", "blood": "blood",
        "saliva": "saliva", "tear": "tear", "water": "water", "food": "food",
        "milk": "food", "juice": "food", "wine": "food", "beer": "food",
        "cell": "cell_culture", "tissue": "tissue",
        "river water": "environmental_water", "lake water": "environmental_water",
        "tap water": "environmental_water",
        "sea water": "environmental_water", "waste water": "environmental_water",
        "drinking water": "environmental_water",
        "river": "environmental_water", "lake": "environmental_water",
        "cerebrospinal fluid": "cerebrospinal_fluid", "csf": "cerebrospinal_fluid",
        "sweat": "sweat", "interstitial fluid": "interstitial_fluid",
        "soil": "soil", "sediment": "sediment",
        "industrial effluent": "industrial_effluent",
    }

    def _extract_applications_from_text(self, record: Dict[str, Any], app_texts: List[str]):
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
                        from application_extractor import is_valid_analyte
                        if is_valid_analyte(analyte):
                            app["target_analyte"] = analyte
                    break
            for sample_kw, sample_type in sorted(self._SAMPLE_TYPE_MAP.items(), key=lambda x: -len(x[0])):
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
            has_substance = any(v is not None for k, v in app.items()
                                if k in ("detection_limit", "linear_range", "target_analyte", "sample_type"))
            has_type = app.get("application_type") is not None
            if not has_substance and not has_type:
                continue
            dedup_key = (app.get("application_type"), app.get("target_analyte"),
                         app.get("detection_limit"), app.get("linear_range"))
            if dedup_key in seen_apps:
                continue
            seen_apps.add(dedup_key)
            for key in ("application_type", "target_analyte", "method", "linear_range",
                        "detection_limit", "sample_type", "notes"):
                app.setdefault(key, None)
            app["_evidence"] = text[:300]
            record["applications"].append(app)


    _MECHANISM_PATTERNS = [
        (re.compile(r'\bFenton[-\s]like\b', re.I), "Fenton-like"),
        (re.compile(r'\bFenton\s+reaction\b', re.I), "Fenton-like"),
        (re.compile(r'\bFenton\b', re.I), "Fenton-like"),
        (re.compile(r'\bHaber[-\s]Weiss\b', re.I), "Haber-Weiss"),
        (re.compile(r'\bROS\s+generat', re.I), "ROS generation"),
        (re.compile(r'\b\*OH\b|hydroxyl\s+radical', re.I), "hydroxyl radical generation"),
        (re.compile(r'\bO2[-\*]?\b.*\bgenerat', re.I), "superoxide generation"),
        (re.compile(r'\bsuperoxide\s+anion', re.I), "superoxide generation"),
        (re.compile(r'\bsinglet\s+oxygen', re.I), "singlet oxygen generation"),
        (re.compile(r'\belectron\s+transfer', re.I), "electron transfer"),
        (re.compile(r'\bcharge\s+transfer', re.I), "charge transfer"),
        (re.compile(r'\boxygen\s+vacanc', re.I), "oxygen vacancy mediated"),
        (re.compile(r'(?:Fe|Co|Ni|Mn|Cu|Zn|Ru|Rh|Ir|Pt|Pd|Mo|W|V|Cr|Ti)-N[xc\d]', re.I), "M-Nx site catalysis"),
        (re.compile(r'\bmetal[-\s]N\d\b', re.I), "M-Nx site catalysis"),
        (re.compile(r'\bM[-\s]N[xc]\d?\b', re.I), "M-Nx site catalysis"),
        (re.compile(r'\bphoto[-\s]?Fenton\b', re.I), "photo-Fenton"),
        (re.compile(r'\bsono[-\s]?Fenton\b', re.I), "sono-Fenton"),
        (re.compile(r'\belectro[-\s]?Fenton\b', re.I), "electro-Fenton"),
        (re.compile(r'\bphotocatalyt', re.I), "photocatalytic"),
        (re.compile(r'\bsonocatalyt', re.I), "sonocatalytic"),
        (re.compile(r'\bpiezocatalyt', re.I), "piezocatalytic"),
        (re.compile(r'\b\*O2[-\^]?\b|\bsuperoxide\s+radical', re.I), "superoxide generation"),
        (re.compile(r'\b1O2\b', re.I), "singlet oxygen generation"),
        (re.compile(r'\bradical\s+scaveng', re.I), "radical scavenging"),
        (re.compile(r'\bROS[-\s]mediated\b', re.I), "ROS-mediated"),
        (re.compile(r'\bROS[-\s]induced\b', re.I), "ROS-induced"),
        (re.compile(r'\bcatalytic\s+cycle\b', re.I), "catalytic cycle"),
        (re.compile(r'\bactive\s+site\b', re.I), "active site catalysis"),
        (re.compile(r'\bM[-\s]N[xc]\d?\s+(?:site|center|coordination|moiety)\b', re.I), "M-Nx site catalysis"),
        (re.compile(r'\bsingle[-\s]?atom\s+(?:site|center|catalyst)', re.I), "single-atom catalysis"),
        (re.compile(r'\bSA[-\s]?C\b', re.I), "single-atom catalysis"),
        (re.compile(r'\bdefect[-\s]?mediated\b', re.I), "defect-mediated"),
        (re.compile(r'\bsulfur\s+vacancy\b', re.I), "sulfur vacancy mediated"),
        (re.compile(r'\bnitrogen\s+vacancy\b', re.I), "nitrogen vacancy mediated"),
        (re.compile(r'\bsurface[-\s]?mediated\b', re.I), "surface-mediated"),
        (re.compile(r'\badsorption[-\s]?mediated\b', re.I), "adsorption-mediated"),
        (re.compile(r'\binterfacial\s+catalys', re.I), "interfacial catalysis"),
        (re.compile(r'\benzyme[-\s]?mimick', re.I), "enzyme-mimicking"),
        (re.compile(r'\bbiomimetic\s+catalys', re.I), "biomimetic catalysis"),
        (re.compile(r'\bchemodynamic\s+therap', re.I), "chemodynamic"),
        (re.compile(r'\bphotodynamic\s+therap', re.I), "photodynamic"),
        (re.compile(r'\bsonodynamic\s+therap', re.I), "sonodynamic"),
        (re.compile(r'\bGSH\s+deplet', re.I), "GSH depletion"),
        (re.compile(r'\bglutathione\s+deplet', re.I), "GSH depletion"),
        (re.compile(r'\b\*OOH\b', re.I), "hydroperoxyl radical generation"),
        (re.compile(r'\bH2O2\s+generat', re.I), "H2O2 generation"),
        (re.compile(r'\bwater\s+oxidation\b', re.I), "water oxidation"),
        (re.compile(r'\boxygen\s+evolution\b', re.I), "oxygen evolution"),
        (re.compile(r'\boxygen\s+reduction\b', re.I), "oxygen reduction"),
        (re.compile(r'\bhydrogen\s+evolution\b', re.I), "hydrogen evolution"),
        (re.compile(r'\bCO2\s+reduction\b', re.I), "CO2 reduction"),
        (re.compile(r'\bN2\s+fixation\b', re.I), "N2 fixation"),
    ]

    def _extract_mechanism(self, record: Dict[str, Any], texts: List[str]):
        if record["main_activity"].get("mechanism"):
            return
        for text in texts:
            for pat, mech in self._MECHANISM_PATTERNS:
                if pat.search(text):
                    record["main_activity"]["mechanism"] = mech
                    return


class NumericValidator:
    def validate(self, record: Dict[str, Any], strict: bool = True) -> Tuple[Dict[str, Any], List[str]]:
        warnings = []
        kinetics = record.get("main_activity", {}).get("kinetics", {})

        km = kinetics.get("Km")
        km_unit = kinetics.get("Km_unit")
        if km is not None:
            if isinstance(km, (int, float)) and km < 0:
                warnings.append("Km_negative")
                kinetics["needs_review"] = True
            if strict and km_unit and km_unit.lower() not in ("mm", "m", "μm", "um", "mmol", "umol", "nmol"):
                warnings.append(f"suspect_Km_unit:{km_unit}")

        vmax = kinetics.get("Vmax")
        if vmax is not None:
            if isinstance(vmax, str) and not vmax.strip():
                kinetics["Vmax"] = None
                vmax = None
                warnings.append("Vmax_empty_string")
            elif isinstance(vmax, (int, float)) and vmax < 0:
                warnings.append("Vmax_negative")
                kinetics["needs_review"] = True

        if km is None and vmax is None:
            warnings.append("no_kinetics_found")

        for app in record.get("applications", []):
            lod = app.get("detection_limit")
            if lod is not None and isinstance(lod, str) and not re.search(r'\d', lod):
                warnings.append("LOD_no_numeric_value")

        record["diagnostics"]["warnings"].extend(warnings)
        return record, warnings

    _NANOZYME_KM_RANGES = {
        "peroxidase-like": (0.001, 500, "mM"),
        "oxidase-like": (0.01, 200, "mM"),
        "catalase-like": (0.1, 1000, "mM"),
        "superoxide-dismutase-like": (0.01, 100, "mM"),
        "glucose-oxidase-like": (0.1, 500, "mM"),
        "haloperoxidase-like": (0.01, 100, "mM"),
        "phosphatase-like": (0.001, 200, "mM"),
        "laccase-like": (0.01, 50, "mM"),
        "nitroreductase-like": (0.001, 100, "mM"),
    }

    _NANOZYME_VMAX_RANGES = {
        "peroxidase-like": (1e-4, 1e6, "μM/s"),
        "oxidase-like": (1e-3, 1e5, "μM/s"),
        "catalase-like": (1e-2, 1e6, "μM/s"),
        "glucose-oxidase-like": (1e-3, 1e5, "μM/s"),
    }

    _ANALYTE_ENZYME_COMPATIBILITY = {
        "peroxidase-like": {"h2o2", "tmb", "abts", "opd", "dab", "glucose", "dopamine", "ascorbic acid"},
        "oxidase-like": {"glucose", "ascorbic acid", "uric acid", "cholesterol", "dopamine"},
        "catalase-like": {"h2o2"},
        "glucose-oxidase-like": {"glucose", "o2"},
        "superoxide-dismutase-like": {"superoxide", "o2-"},
        "haloperoxidase-like": {"br-", "i-", "h2o2"},
    }

    def validate_nanozyme_kinetics(self, record: Dict[str, Any]) -> List[str]:
        warnings = []
        ma = record.get("main_activity", {})
        etype = ma.get("enzyme_like_type", "")
        kin = ma.get("kinetics", {})

        if not isinstance(kin, dict) or not etype:
            return warnings

        km_range = self._NANOZYME_KM_RANGES.get(etype)
        if km_range:
            km_val = kin.get("Km")
            km_u = kin.get("Km_unit", "")
            if isinstance(km_val, (int, float)):
                km_mM = self._to_mM(km_val, km_u)
                if km_mM is not None:
                    lo, hi, _ = km_range
                    if km_mM < lo or km_mM > hi:
                        warnings.append(
                            f"Km={km_val} {km_u} ({km_mM:.4f} mM) outside typical range "
                            f"for {etype} ({lo}-{hi} mM)"
                        )

        vmax_range = self._NANOZYME_VMAX_RANGES.get(etype)
        if vmax_range:
            vmax_val = kin.get("Vmax")
            vmax_u = kin.get("Vmax_unit", "")
            if isinstance(vmax_val, (int, float)):
                vmax_uM = self._to_uM_per_s(vmax_val, vmax_u)
                if vmax_uM is not None:
                    lo, hi, _ = vmax_range
                    if vmax_uM < lo or vmax_uM > hi:
                        warnings.append(
                            f"Vmax={vmax_val} {vmax_u} ({vmax_uM:.4f} μM/s) outside typical range "
                            f"for {etype}"
                        )

        for i, kl in enumerate(ma.get("kinetics_list", [])):
            if not isinstance(kl, dict):
                continue
            if km_range:
                kl_km = kl.get("Km")
                kl_kmu = kl.get("Km_unit", "")
                if isinstance(kl_km, (int, float)):
                    kl_km_mM = self._to_mM(kl_km, kl_kmu)
                    if kl_km_mM is not None:
                        lo, hi, _ = km_range
                        if kl_km_mM < lo or kl_km_mM > hi:
                            warnings.append(
                                f"kinetics_list[{i}]: Km={kl_km} {kl_kmu} outside typical range for {etype}"
                            )

        for app in record.get("applications", []):
            if not isinstance(app, dict):
                continue
            analyte = app.get("target_analyte", "")
            if analyte and etype in self._ANALYTE_ENZYME_COMPATIBILITY:
                compat = self._ANALYTE_ENZYME_COMPATIBILITY[etype]
                if analyte.lower() not in {a.lower() for a in compat}:
                    warnings.append(
                        f"Analyte '{analyte}' may be incompatible with {etype} "
                        f"(expected: {', '.join(sorted(compat))})"
                    )

        return warnings

    def _to_mM(self, val: float, unit: str) -> Optional[float]:
        conversions = {"M": 1e3, "mM": 1.0, "μM": 1e-3, "uM": 1e-3, "nM": 1e-6, "pM": 1e-9}
        factor = conversions.get(unit)
        return val * factor if factor else None

    def _to_uM_per_s(self, val: float, unit: str) -> Optional[float]:
        conversions = {
            "M/s": 1e6, "M s^-1": 1e6, "M·s-1": 1e6,
            "mM/s": 1e3, "mM s^-1": 1e3, "mM·s-1": 1e3,
            "μM/s": 1.0, "uM/s": 1.0, "μM s^-1": 1.0,
            "nM/s": 1e-3, "nM s^-1": 1e-3,
            "μM/min": 1.0 / 60, "uM/min": 1.0 / 60,
        }
        factor = conversions.get(unit)
        return val * factor if factor else None


class SingleMainNanozymePipeline:
    def __init__(self, client=None, config: Optional[SMNConfig] = None):
        self.client = client
        self.config = config or SMNConfig()
        self.meta_ext = PaperMetadataExtractor()
        self.recaller = CandidateRecaller(top_k=self.config.material_candidate_top_k)
        self.scorer = NanozymeScorer()
        self.bucket_builder = EvidenceBucketBuilder(max_sentences=self.config.max_evidence_sentences_per_bucket)
        self.table_proc = TableProcessor()
        self.figure_proc = FigureProcessor()
        self.rule_ext = RuleExtractor()
        if is_available("extraction_agents"):
            from extraction_agents import RuleExtractorAdapter
            self.rule_ext = RuleExtractorAdapter()
            logger.info("[SMN] Using RuleExtractorAdapter (4 specialized agents)")
        else:
            logger.warning("[SMN] extraction_agents not available, using original RuleExtractor")
        self.llm_structured = None
        if client and self.config.enable_llm and is_available("llm_structured_extractor"):
            from llm_structured_extractor import LLMStructuredExtractor
            self.llm_structured = LLMStructuredExtractor(client, self.config)
            logger.info("[SMN] LLMStructuredExtractor loaded (LLM-First mode)")
        self.material_identifier = None
        if client and self.config.enable_llm and is_available("material_identifier"):
            from material_identifier import MaterialIdentifier
            self.material_identifier = MaterialIdentifier(client, self.config)
            logger.info("[SMN] MaterialIdentifier loaded (LLM-First material identification)")
        self.num_val = NumericValidator()
        if is_available("diagnostics_builder"):
            from diagnostics_builder import DiagnosticsBuilder as FullDiagnosticsBuilder
            self.diag_builder = FullDiagnosticsBuilder()
            logger.info("[SMN] Using full DiagnosticsBuilder from diagnostics_builder module")
        else:
            self.diag_builder = None
            logger.warning("[SMN] diagnostics_builder not available, using inline diagnostics")
        self._guard: Optional[Any] = None
        self._agentic_guard: Optional[Any] = None
        if is_available("cross_validation_agent"):
            from cross_validation_agent import CrossValidationAgent
            self.cross_validator = CrossValidationAgent()
            logger.info("[SMN] CrossValidationAgent loaded")
        else:
            self.cross_validator = None
            logger.warning("[SMN] CrossValidationAgent not available")
        if is_available("consistency_agent"):
            from consistency_agent import ConsistencyAgent
            self.consistency_agent = ConsistencyAgent()
            logger.info("[SMN] ConsistencyAgent loaded")
        else:
            self.consistency_agent = None
            logger.warning("[SMN] ConsistencyAgent not available")
        if is_available("extraction_verifier"):
            from extraction_verifier import ExtractionVerifier
            self._verifier_class = ExtractionVerifier
            logger.info("[SMN] ExtractionVerifier loaded")
        else:
            self._verifier_class = None
            logger.warning("[SMN] ExtractionVerifier not available")

    def _deduplicate_vlm_tasks(self, tasks, priorities):
        if len(tasks) <= 1:
            return tasks, priorities

        def _caption_words(task):
            c = (task.get("caption", "") + " " + task.get("description", "")).lower()
            return set(re.findall(r'[a-z0-9]{3,}', c))

        keep = list(range(len(tasks)))
        for i in range(len(tasks)):
            if i not in keep:
                continue
            wi = _caption_words(tasks[i])
            if not wi:
                continue
            for j in range(i + 1, len(tasks)):
                if j not in keep:
                    continue
                wj = _caption_words(tasks[j])
                if not wj:
                    continue
                intersection = wi & wj
                if len(intersection) >= 3:
                    union = wi | wj
                    jaccard = len(intersection) / max(len(union), 1)
                    if jaccard > 0.7:
                        pi = priorities[i] if i < len(priorities) else 0
                        pj = priorities[j] if j < len(priorities) else 0
                        if pi >= pj:
                            keep.remove(j)
                            logger.info(
                                f"[SMN] VLM dedup: task[{j}] removed (similar to task[{i}], "
                                f"jaccard={jaccard:.1%}, caption='{list(wi & wj)[:3]}')"
                            )
                        else:
                            keep.remove(i)
                            logger.info(
                                f"[SMN] VLM dedup: task[{i}] removed (similar to task[{j}], "
                                f"jaccard={jaccard:.1%}, caption='{list(wi & wj)[:3]}')"
                            )
                            break

        if len(keep) < len(tasks):
            new_tasks = [tasks[k] for k in keep]
            new_pri = [priorities[k] if k < len(priorities) else 0 for k in keep]
            logger.info(f"[SMN] VLM dedup: {len(tasks)}→{len(new_tasks)} tasks after dedup")
            return new_tasks, new_pri
        return tasks, priorities

    async def _call_vlm(self, vlm_tasks: List[Dict], selected_name: str) -> Optional[List[Dict]]:
        if not self.client:
            return None
        if not is_available("vlm_extractor"):
            logger.warning("[SMN] VLMExtractor not available, skipping VLM")
            return None
        from vlm_extractor import VLMExtractor

        name_lower = selected_name.lower()
        variants = {name_lower}
        if "@" in name_lower:
            variants.update(p.strip() for p in name_lower.split("@") if p.strip())
        if "/" in name_lower:
            variants.update(p.strip() for p in name_lower.split("/") if p.strip())

        filtered_tasks = []
        task_priorities = []
        for task in vlm_tasks:
            caption = task.get("caption", "")
            description = task.get("description", "")
            body_context = task.get("body_context", "")
            combined = f"{caption} {description} {body_context}".lower()
            image_path = task.get("image_path", "")
            page_num = task.get("page_num", 0)

            mentions_selected = any(v in combined for v in variants if len(v) >= 2)
            has_kinetics = any(kw in combined for kw in ("km", "vmax", "michaelis", "kinetic", "kcat"))
            has_morphology = any(kw in combined for kw in ("tem", "sem", "afm", "morpholog", "size", "particle", "xrd", "xps", "ftir"))
            has_sensing = any(kw in combined for kw in ("detection", "sensing", "lod", "linear range"))
            has_ph_temp = any(kw in combined for kw in ("ph", "temperature", "thermal", "stability", "optimal", "optimum"))
            has_activity = any(kw in combined for kw in ("activity", "catalytic", "peroxidase", "oxidase", "enzyme"))

            priority = 0
            if has_kinetics:
                priority += 10
            if has_sensing:
                priority += 8
            if has_ph_temp:
                priority += 6
            if has_activity:
                priority += 5
            if has_morphology:
                priority += 4
            if mentions_selected:
                priority += 3
            if not caption and not description:
                fn_lower = image_path.lower() if image_path else ""
                if any(kw in fn_lower for kw in ("kinetic", "km", "vmax", "ph", "temp")):
                    priority += 5
                elif any(kw in fn_lower for kw in ("sem", "tem", "xrd", "morph")):
                    priority += 3
            if priority > 0:
                filtered_tasks.append(task)
                task_priorities.append(priority)
            else:
                logger.debug(f"[SMN] VLM skip: caption not related to selected material: {caption[:60]}")

        if not filtered_tasks:
            logger.info(f"[SMN] No relevant VLM tasks after filtering (was {len(vlm_tasks)}, now 0)")
            return None

        max_vlm_tasks = 8
        if len(filtered_tasks) > max_vlm_tasks:
            paired = list(zip(task_priorities, filtered_tasks))
            paired.sort(key=lambda x: x[0], reverse=True)
            filtered_tasks = [t for _, t in paired[:max_vlm_tasks]]
            task_priorities = [p for p, _ in paired[:max_vlm_tasks]]
            logger.info(f"[SMN] VLM tasks limited from {len(paired)} to {max_vlm_tasks} by priority")

        filtered_tasks, task_priorities = self._deduplicate_vlm_tasks(
            filtered_tasks, task_priorities
        )

        logger.info(f"[SMN] VLM tasks: {len(vlm_tasks)} total, {len(filtered_tasks)} relevant")

        extractor = VLMExtractor(self.client, batch_size=1)
        results = []
        for i, task in enumerate(filtered_tasks):
            image_path = task.get("image_path", "")
            caption = task.get("caption", "")
            description = task.get("description", "")
            elem_type = task.get("elem_type", "image")
            vlm_reason = task.get("vlm_reason", "")
            caption_type = task.get("caption_type", "")
            body_context = task.get("body_context", "")
            try:
                result = await asyncio.wait_for(
                    extractor._extract_from_image(
                        image_path=image_path,
                        caption=caption,
                        description=description,
                        elem_type=elem_type,
                        vlm_reason=vlm_reason,
                        caption_type=caption_type,
                        body_context=body_context,
                    ),
                    timeout=60,
                )
                if result and "error" not in result:
                    result["_source_task"] = task.get("figure_id", "")
                    result["_source_caption"] = caption
                    results.append(result)
            except asyncio.TimeoutError:
                logger.warning(f"[SMN] VLM task timed out (60s) for image: {image_path[:60]}")
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "rate" in err_str:
                    wait = min(30, 5 * (2 ** min(i, 3)))
                    logger.warning(f"[SMN] VLM rate limited, waiting {wait}s before next request")
                    await asyncio.sleep(wait)
                    try:
                        result = await asyncio.wait_for(
                            extractor._extract_from_image(
                                image_path=image_path,
                                caption=caption,
                                description=description,
                                elem_type=elem_type,
                                vlm_reason=vlm_reason,
                                caption_type=caption_type,
                                body_context=body_context,
                            ),
                            timeout=60,
                        )
                        if result and "error" not in result:
                            result["_source_task"] = task.get("figure_id", "")
                            result["_source_caption"] = caption
                            results.append(result)
                    except asyncio.TimeoutError:
                        logger.warning(f"[SMN] VLM retry timed out (60s) for image: {image_path[:60]}")
                    except Exception as e2:
                        logger.warning(f"[SMN] VLM retry also failed: {e2}")
                else:
                    logger.warning(f"[SMN] VLM task failed: {e}")
            if i < len(filtered_tasks) - 1:
                await asyncio.sleep(2)
        return results if results else None

    async def _call_table_vlm_fallback(
        self, fallback_tasks: List[Dict], selected_name: str
    ) -> Optional[List[Dict]]:
        if not self.client or not fallback_tasks:
            return None
        if not is_available("vlm_extractor"):
            logger.warning("[SMN] VLMExtractor not available for table fallback")
            return None
        from vlm_extractor import VLMExtractor

        extractor = VLMExtractor(self.client, batch_size=1)
        results = []

        for task in fallback_tasks:
            table_id = task.get("table_id", "unknown")
            caption = task.get("caption", "")
            table_type = task.get("table_type", "")
            bbox = task.get("bbox")
            page = task.get("page", 0)

            image_path = None
            for tbl in self._doc.table_task.get("tables", []):
                if tbl.get("table_id") == table_id and tbl.get("image_path"):
                    image_path = tbl["image_path"]
                    break

            if not image_path or not Path(image_path).exists():
                logger.debug(f"[SMN] Table VLM fallback: no image for {table_id}")
                continue

            is_kinetics = table_type == "kinetics_parameters"
            is_sensing = table_type == "sensing_performance"

            if is_kinetics:
                caption_type = "kinetics_caption"
            elif is_sensing:
                caption_type = "application_caption"
            else:
                caption_type = ""

            vlm_reason = f"table_vlm_fallback({table_type})"

            try:
                result = await asyncio.wait_for(
                    extractor._extract_from_image(
                        image_path=image_path,
                        caption=caption or f"Table: {table_id}",
                        description="",
                        elem_type="table",
                        vlm_reason=vlm_reason,
                        caption_type=caption_type,
                        body_context="",
                    ),
                    timeout=60,
                )
                if result and "error" not in result:
                    result["_source_task"] = table_id
                    result["_source_caption"] = caption
                    result["_is_table_fallback"] = True
                    results.append(result)
                    logger.info(f"[SMN] Table VLM fallback success: {table_id}")
            except asyncio.TimeoutError:
                logger.warning(f"[SMN] Table VLM fallback timed out for {table_id}")
            except Exception as e:
                logger.warning(f"[SMN] Table VLM fallback failed for {table_id}: {e}")

            await asyncio.sleep(2)

        return results if results else None

    _VLM_INVALID_VALUES = frozenset({
        "unknown", "not visible", "not clear", "unclear", "n/a", "na",
        "none", "null", "-", "--", "---", "not specified", "not provided",
        "cannot determine", "cannot be determined", "not applicable",
        "not discernible", "not readable", "illegible", "indeterminate",
    })

    def _clean_vlm_value(self, val) -> Any:
        if val is None:
            return None
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return val
        if isinstance(val, str):
            val = val.strip()
            if val.lower() in self._VLM_INVALID_VALUES:
                return None
            if len(val) == 0:
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
            return val
        if isinstance(val, dict):
            cleaned = {}
            for k, v in val.items():
                cv = self._clean_vlm_value(v)
                if cv is not None:
                    cleaned[k] = cv
            return cleaned if cleaned else None
        if isinstance(val, list):
            cleaned = [self._clean_vlm_value(v) for v in val]
            cleaned = [v for v in cleaned if v is not None]
            return cleaned if cleaned else None
        return val

    def _clean_vlm_extracted_values(self, ev: Dict) -> Dict:
        if not isinstance(ev, dict):
            return {}
        cleaned = {}
        for key, val in ev.items():
            cv = self._clean_vlm_value(val)
            if cv is not None:
                cleaned[key] = cv
        return cleaned

    def _sync_kinetics_list(self, record: Dict[str, Any]) -> Dict[str, Any]:
        kin = record.get("main_activity", {}).get("kinetics", {})
        kin_list = record.get("main_activity", {}).get("kinetics_list", [])
        if not isinstance(kin_list, list):
            kin_list = []
        has_kinetics_data = any(
            kin.get(k) is not None for k in ("Km", "Vmax", "kcat", "kcat_Km")
        )
        if kin_list:
            for entry in kin_list:
                if not isinstance(entry, dict):
                    continue
                for ukey in ("Km_unit", "Vmax_unit"):
                    u = entry.get(ukey)
                    if u and isinstance(u, str) and _normalize_unit_fn:
                        entry[ukey] = _normalize_unit_fn(u)
            if has_kinetics_data:
                primary = {k: kin.get(k) for k in ("Km", "Km_unit", "Vmax", "Vmax_unit",
                                                      "kcat", "kcat_unit", "kcat_Km", "kcat_Km_unit",
                                                      "substrate", "source", "needs_review")}
                if primary not in kin_list:
                    kin_list.insert(0, primary)
            else:
                first = kin_list[0] if kin_list else {}
                for k in ("Km", "Km_unit", "Vmax", "Vmax_unit", "kcat", "kcat_unit",
                          "kcat_Km", "kcat_Km_unit", "substrate", "source", "needs_review"):
                    if first.get(k) is not None:
                        kin[k] = first[k]
        elif has_kinetics_data:
            entry = {k: kin.get(k) for k in ("Km", "Km_unit", "Vmax", "Vmax_unit",
                                               "substrate", "source")}
            if kin.get("kcat") is not None:
                entry["kcat"] = kin["kcat"]
                entry["kcat_unit"] = kin.get("kcat_unit")
            if kin.get("kcat_Km") is not None:
                entry["kcat_Km"] = kin["kcat_Km"]
                entry["kcat_Km_unit"] = kin.get("kcat_Km_unit")
            kin_list = [entry]
        record["main_activity"]["kinetics_list"] = kin_list
        return record

    def _merge_vlm(self, record: Dict[str, Any], vlm_results: List[Dict]) -> Dict[str, Any]:
        for vr in vlm_results:
            ev = vr.get("extracted_values", {})
            if not isinstance(ev, dict):
                ev = {}
            ev = self._clean_vlm_extracted_values(ev)
            figure_type = vr.get("figure_type", "unknown")
            caption = vr.get("caption", "") or vr.get("_source_caption", "")

            if self._guard and caption:
                vlm_check = self._guard.check_vlm_result_attribution(vr, caption)
                if not vlm_check["valid"]:
                    logger.warning(
                        f"[SMN] VLM result skipped: {vlm_check['reason']}"
                    )
                    continue

            if self.config.figure_values_to_important_values:
                for km_item in ev.get("Km", []):
                    if isinstance(km_item, dict) and km_item.get("value") is not None:
                        iv = {
                            "name": "VLM_Km",
                            "value": str(km_item["value"]),
                            "unit": km_item.get("unit", ""),
                            "context": f"VLM {figure_type} figure",
                            "source": "VLM",
                            "needs_review": True,
                        }
                        record["important_values"].append(iv)
                        try:
                            vlm_val = float(km_item["value"])
                        except (ValueError, TypeError):
                            continue
                        rule_km = record["main_activity"]["kinetics"].get("Km")
                        raw_km_unit = km_item.get("unit", "")
                        vlm_val, raw_km_unit = _parse_unit_scientific_prefix(vlm_val, raw_km_unit)
                        iv["value"] = str(vlm_val)
                        iv["unit"] = raw_km_unit
                        km_unit_ok = _is_concentration_unit_fn(raw_km_unit) if raw_km_unit and _is_concentration_unit_fn else False
                        if rule_km is None:
                            record["main_activity"]["kinetics"]["Km"] = vlm_val
                            if km_unit_ok:
                                record["main_activity"]["kinetics"]["Km_unit"] = _normalize_unit_fn(raw_km_unit) if _normalize_unit_fn else raw_km_unit
                            elif _is_rate_unit_fn and _is_rate_unit_fn(raw_km_unit):
                                logger.warning(f"[SMN] VLM Km_unit='{raw_km_unit}' is a rate unit (should be concentration). Skipping unit assignment.")
                            else:
                                record["main_activity"]["kinetics"]["Km_unit"] = _normalize_unit_fn(raw_km_unit) if _normalize_unit_fn and raw_km_unit else (raw_km_unit or None)
                            record["main_activity"]["kinetics"]["source"] = "VLM"
                            if caption:
                                record["main_activity"]["kinetics"]["_evidence_Km"] = str(caption)[:300]
                            else:
                                record["main_activity"]["kinetics"]["_vlm_no_evidence"] = True
                            logger.info(f"[SMN] VLM Km={vlm_val} fills empty kinetics (source=VLM)")
                        elif isinstance(rule_km, (int, float)):
                            rel_diff = abs(vlm_val - rule_km) / max(abs(rule_km), 1e-10)
                            if rel_diff < 0.2:
                                logger.info(f"[SMN] VLM Km={vlm_val} confirms rule Km={rule_km} (diff={rel_diff:.1%})")
                            elif rel_diff > 0.5:
                                logger.warning(
                                    f"[SMN] VLM Km={vlm_val} differs >50% from rule Km={rule_km}. "
                                    f"Keeping rule value, VLM in important_values."
                                )
                            else:
                                logger.info(f"[SMN] VLM Km={vlm_val} differs {rel_diff:.1%} from rule Km={rule_km}")

                for vmax_item in ev.get("Vmax", []):
                    if isinstance(vmax_item, dict) and vmax_item.get("value") is not None:
                        iv = {
                            "name": "VLM_Vmax",
                            "value": str(vmax_item["value"]),
                            "unit": vmax_item.get("unit", ""),
                            "context": f"VLM {figure_type} figure",
                            "source": "VLM",
                            "needs_review": True,
                        }
                        record["important_values"].append(iv)
                        try:
                            vlm_val = float(vmax_item["value"])
                        except (ValueError, TypeError):
                            continue
                        raw_vmax_unit = vmax_item.get("unit", "")
                        vlm_val, raw_vmax_unit = _parse_unit_scientific_prefix(vlm_val, raw_vmax_unit)
                        iv["value"] = str(vlm_val)
                        iv["unit"] = raw_vmax_unit
                        rule_vmax = record["main_activity"]["kinetics"].get("Vmax")
                        vmax_unit_ok = _is_rate_unit_fn(raw_vmax_unit) if raw_vmax_unit and _is_rate_unit_fn else False
                        if rule_vmax is None:
                            record["main_activity"]["kinetics"]["Vmax"] = vlm_val
                            if vmax_unit_ok:
                                record["main_activity"]["kinetics"]["Vmax_unit"] = _normalize_unit_fn(raw_vmax_unit) if _normalize_unit_fn else raw_vmax_unit
                            elif _is_concentration_unit_fn and _is_concentration_unit_fn(raw_vmax_unit):
                                logger.warning(f"[SMN] VLM Vmax_unit='{raw_vmax_unit}' is a concentration unit (should be rate). Skipping unit assignment.")
                            else:
                                record["main_activity"]["kinetics"]["Vmax_unit"] = _normalize_unit_fn(raw_vmax_unit) if _normalize_unit_fn and raw_vmax_unit else (raw_vmax_unit or None)
                            record["main_activity"]["kinetics"]["source"] = "VLM"
                            if caption:
                                record["main_activity"]["kinetics"]["_evidence_Vmax"] = str(caption)[:300]
                            else:
                                record["main_activity"]["kinetics"]["_vlm_no_evidence"] = True
                            logger.info(f"[SMN] VLM Vmax={vlm_val} fills empty kinetics (source=VLM)")
                        elif isinstance(rule_vmax, (int, float)):
                            rel_diff = abs(vlm_val - rule_vmax) / max(abs(rule_vmax), 1e-10)
                            if rel_diff < 0.2:
                                logger.info(f"[SMN] VLM Vmax={vlm_val} confirms rule Vmax={rule_vmax} (diff={rel_diff:.1%})")
                            elif rel_diff > 0.5:
                                logger.warning(
                                    f"[SMN] VLM Vmax={vlm_val} differs >50% from rule Vmax={rule_vmax}. "
                                    f"Keeping rule value, VLM in important_values."
                                )
                            else:
                                logger.info(f"[SMN] VLM Vmax={vlm_val} differs {rel_diff:.1%} from rule Vmax={rule_vmax}")

                ps = ev.get("particle_size")
                if isinstance(ps, dict) and ps.get("value") is not None:
                    iv = {
                        "name": "VLM_particle_size",
                        "value": str(ps["value"]),
                        "unit": ps.get("unit", "nm"),
                        "context": f"VLM {figure_type} figure",
                        "source": "VLM",
                        "needs_review": True,
                    }
                    record["important_values"].append(iv)
                    if not record["selected_nanozyme"].get("size"):
                        record["selected_nanozyme"]["size"] = f"{ps['value']} {ps.get('unit', 'nm')}"

                for kcat_item in ev.get("kcat", []):
                    if isinstance(kcat_item, dict) and kcat_item.get("value") is not None:
                        iv = {
                            "name": "VLM_kcat",
                            "value": str(kcat_item["value"]),
                            "unit": kcat_item.get("unit", "s⁻¹"),
                            "context": f"VLM {figure_type} figure",
                            "source": "VLM",
                            "needs_review": True,
                        }
                        record["important_values"].append(iv)
                        try:
                            vlm_val = float(kcat_item["value"])
                        except (ValueError, TypeError):
                            continue
                        raw_kcat_unit = kcat_item.get("unit", "s⁻¹")
                        vlm_val, raw_kcat_unit = _parse_unit_scientific_prefix(vlm_val, raw_kcat_unit)
                        if record["main_activity"]["kinetics"].get("kcat") is None:
                            record["main_activity"]["kinetics"]["kcat"] = vlm_val
                            record["main_activity"]["kinetics"]["kcat_unit"] = raw_kcat_unit
                            record["main_activity"]["kinetics"]["source"] = "VLM"
                            if caption:
                                record["main_activity"]["kinetics"]["_evidence_kcat"] = str(caption)[:300]

                for kcat_km_item in ev.get("kcat_Km", []):
                    if isinstance(kcat_km_item, dict) and kcat_km_item.get("value") is not None:
                        iv = {
                            "name": "VLM_kcat_Km",
                            "value": str(kcat_km_item["value"]),
                            "unit": kcat_km_item.get("unit", "M⁻¹s⁻¹"),
                            "context": f"VLM {figure_type} figure",
                            "source": "VLM",
                            "needs_review": True,
                        }
                        record["important_values"].append(iv)
                        try:
                            vlm_val = float(kcat_km_item["value"])
                        except (ValueError, TypeError):
                            continue
                        raw_kcat_km_unit = kcat_km_item.get("unit", "M⁻¹s⁻¹")
                        vlm_val, raw_kcat_km_unit = _parse_unit_scientific_prefix(vlm_val, raw_kcat_km_unit)
                        if record["main_activity"]["kinetics"].get("kcat_Km") is None:
                            record["main_activity"]["kinetics"]["kcat_Km"] = vlm_val
                            record["main_activity"]["kinetics"]["kcat_Km_unit"] = raw_kcat_km_unit
                            record["main_activity"]["kinetics"]["source"] = "VLM"
                            if caption:
                                record["main_activity"]["kinetics"]["_evidence_kcat_Km"] = str(caption)[:300]

                sp = ev.get("sensing_performance")
                if isinstance(sp, dict):
                    for param in ("LOD", "linear_range", "sensitivity"):
                        val = sp.get(param)
                        if val is not None:
                            iv = {
                                "name": f"VLM_{param}",
                                "value": str(val),
                                "unit": "",
                                "context": f"VLM {figure_type} figure",
                                "source": "VLM",
                                "needs_review": True,
                            }
                            record["important_values"].append(iv)
                    vlm_lod = sp.get("LOD")
                    vlm_lr = sp.get("linear_range")
                    vlm_analyte = sp.get("target_analyte")
                    if vlm_analyte:
                        from application_extractor import is_valid_analyte
                        if not is_valid_analyte(str(vlm_analyte)):
                            vlm_analyte = None
                    if vlm_lod or vlm_lr:
                        apps = record.get("applications", [])
                        matched_app = None
                        if vlm_analyte:
                            for app in apps:
                                if (app.get("target_analyte") or "").lower() == str(vlm_analyte).lower():
                                    matched_app = app
                                    break
                        if matched_app:
                            if vlm_lod and matched_app.get("detection_limit") is None:
                                matched_app["detection_limit"] = str(vlm_lod)
                            if vlm_lr and matched_app.get("linear_range") is None:
                                matched_app["linear_range"] = str(vlm_lr)
                        else:
                            new_app = {
                                "application_type": "sensing",
                                "target_analyte": str(vlm_analyte) if vlm_analyte else None,
                                "detection_limit": str(vlm_lod) if vlm_lod else None,
                                "linear_range": str(vlm_lr) if vlm_lr else None,
                                "notes": "from VLM sensing_performance",
                                "_evidence": str(caption)[:300] if caption else None,
                            }
                            if not caption:
                                new_app["_vlm_no_evidence"] = True
                            apps.append(new_app)
                            record["applications"] = apps

                for ov in ev.get("other_values", []):
                    if isinstance(ov, dict) and ov.get("value") is not None:
                        iv = {
                            "name": f"VLM_{ov.get('label', 'unknown')}",
                            "value": str(ov["value"]),
                            "unit": ov.get("unit", ""),
                            "context": f"VLM {figure_type} figure",
                            "source": "VLM",
                            "needs_review": True,
                        }
                        record["important_values"].append(iv)

            observations = vr.get("observations", [])
            if observations:
                obs_text = "; ".join(str(o) for o in observations if o)
                if obs_text:
                    _MORPH_FIGURE_DESC_RE = re.compile(
                        r'(?:Panel\s+[A-Z]|Figure\s+\d|illustrates?|plots?\s|shows?\s|displays?\s|depicts?\s|presents?\s|demonstrates?\s|As\s+(?:can\s+be\s+)?seen|It\s+is\s+clear|The\s+(?:above|following)\s+figure|diagram|schematic|pathway|mechanism\s+links|catalyzes?\s+the\s+oxid)',
                        re.I
                    )
                    _MORPH_VALID_TERMS = re.compile(
                        r'(?:nanoparticle|nanosheet|nanotube|nanocluster|nanorod|nanowire|nanofiber|'
                        r'nanozyme|sphere|spherical|rod|wire|fiber|sheet|layer|layered|'
                        r'porous|hollow|core[- ]shell|dendritic|flower|cube|cubic|'
                        r'prism|belt|plate|flake|aggregate|amorphous|crystalline|'
                        r'octahedr|tetrahedr|icosahedr|ellip|spindle|worm)',
                        re.I
                    )
                    _clean_parts = []
                    for part in obs_text.split(";"):
                        part = part.strip()
                        if not part:
                            continue
                        if _MORPH_FIGURE_DESC_RE.search(part):
                            continue
                        if len(part) > 80 and part.count(',') > 3:
                            continue
                        if not _MORPH_VALID_TERMS.search(part):
                            continue
                        _clean_parts.append(part)
                    cleaned_morph = "; ".join(_clean_parts) if _clean_parts else ""

                    if not record["selected_nanozyme"].get("morphology"):
                        record["selected_nanozyme"]["morphology"] = cleaned_morph[:200]
                    else:
                        record["selected_nanozyme"]["_vlm_morphology_rejected"] = cleaned_morph[:200]
                        record["important_values"].append({
                            "name": "VLM_observations",
                            "value": cleaned_morph[:200],
                            "unit": "",
                            "context": f"VLM {figure_type} figure observations (morphology already set)",
                            "source": "VLM",
                            "needs_review": True,
                        })

            linked_type = vr.get("linked_activity_type")
            if linked_type and isinstance(linked_type, str):
                norm_type = self._normalize_enzyme_type(linked_type)
                rule_type = record["main_activity"].get("enzyme_like_type")
                if not rule_type or rule_type == "unknown":
                    record["main_activity"]["enzyme_like_type"] = norm_type
                    record["main_activity"]["_enzyme_type_source"] = "VLM"
                    logger.info(f"[SMN] VLM enzyme_type='{norm_type}' fills empty field")
                elif rule_type != norm_type:
                    record["main_activity"]["_vlm_enzyme_type_rejected"] = norm_type
                    logger.info(f"[SMN] VLM enzyme_type='{norm_type}' conflicts with rule='{rule_type}', kept as rejected")

            app_hints = vr.get("application_hints")
            if isinstance(app_hints, list) and app_hints:
                apps = record.get("applications", [])
                existing_types = {a.get("application_type") for a in apps if a.get("application_type")}
                for hint in app_hints:
                    if not isinstance(hint, str) or not hint.strip():
                        continue
                    norm_app = self._normalize_app_type(hint.strip())
                    if norm_app and norm_app not in existing_types:
                        vlm_app = {
                            "application_type": norm_app,
                            "target_analyte": None,
                            "notes": "from VLM application_hints",
                            "_evidence": str(caption)[:300] if caption else None,
                        }
                        if not caption:
                            vlm_app["_vlm_no_evidence"] = True
                        apps.append(vlm_app)
                        existing_types.add(norm_app)
                record["applications"] = apps

        self._check_multi_figure_consistency(record)
        self._cross_verify_vlm_no_evidence(record)

        return record

    def _cross_verify_vlm_no_evidence(self, record: Dict[str, Any]):
        kin = record["main_activity"]["kinetics"]
        if not kin.get("_vlm_no_evidence"):
            return

        for param in ("Km", "Vmax"):
            vlm_val = kin.get(param)
            if vlm_val is None:
                continue

            rule_val = kin.get(f"_rule_{param}")
            if rule_val is None:
                rule_val = kin.get(param)
            try:
                vlm_f = float(vlm_val)
            except (ValueError, TypeError):
                continue

            llm_alt = kin.get(f"_llm_{param}_alternative")
            llm_f = None
            if llm_alt is not None:
                try:
                    llm_f = float(llm_alt)
                except (ValueError, TypeError):
                    pass

            rule_f = None
            if rule_val is not None:
                try:
                    rule_f = float(rule_val)
                except (ValueError, TypeError):
                    pass

            agreements = 0
            if rule_f is not None and abs(vlm_f - rule_f) / max(abs(rule_f), 1e-10) < 0.2:
                agreements += 1
            if llm_f is not None and abs(vlm_f - llm_f) / max(abs(llm_f), 1e-10) < 0.2:
                agreements += 1

            if agreements >= 1:
                logger.info(
                    f"[SMN] VLM no_evidence {param}={vlm_f}: "
                    f"agrees with {'rule' if rule_f else ''}{' and LLM' if llm_f and rule_f else 'LLM' if llm_f else 'no other'}. "
                    f"Confidence boosted."
                )
                record["important_values"].append({
                    "name": f"VLM_{param}_confirmed",
                    "value": str(vlm_val),
                    "unit": kin.get(f"{param}_unit", ""),
                    "source": "VLM_no_evidence_cross_verified",
                    "context": "VLM value without caption evidence, confirmed by cross-check with other sources",
                    "needs_review": False,
                })
            else:
                logger.warning(
                    f"[SMN] VLM no_evidence {param}={vlm_f} has no corroborating source. "
                    f"Demoting to important_values."
                )
                record["important_values"].append({
                    "name": f"VLM_{param}_demoted",
                    "value": str(vlm_val),
                    "unit": kin.get(f"{param}_unit", ""),
                    "source": "VLM_no_evidence_unverified",
                    "context": "VLM value without caption evidence, no corroboration from rule or LLM",
                    "needs_review": True,
                })
                kin[param] = None
                kin[f"{param}_unit"] = None
                kin["needs_review"] = True

    def _check_multi_figure_consistency(self, record: Dict[str, Any]):
        vlm_kms = []
        vlm_vmaxs = []
        for iv in record.get("important_values", []):
            if not isinstance(iv, dict):
                continue
            name = iv.get("name", "")
            try:
                val = float(iv["value"]) if iv.get("value") else None
            except (ValueError, TypeError):
                continue
            if val is None:
                continue
            if name == "VLM_Km":
                vlm_kms.append(val)
            elif name == "VLM_Vmax":
                vlm_vmaxs.append(val)
        for param_name, values in [("Km", vlm_kms), ("Vmax", vlm_vmaxs)]:
            if len(values) < 2:
                continue
            max_val = max(values)
            min_val = min(values)
            if max_val == 0 and min_val == 0:
                continue
            rel_diff = (max_val - min_val) / max(abs(max_val), abs(min_val), 1e-10)
            if rel_diff > 0.3:
                import statistics
                median_val = statistics.median(values)
                logger.warning(
                    f"[SMN] Multi-figure {param_name} inconsistency: values={values}, "
                    f"max_diff={rel_diff:.1%}. Using median={median_val}."
                )
                record["diagnostics"].setdefault("warnings", []).append(
                    f"multi_figure_{param_name}_inconsistent: {values}"
                )

    async def extract(self, mid_json: Dict[str, Any]) -> Dict[str, Any]:
        record = make_empty_record()
        warnings: List[str] = []

        doc = PreprocessedDocument(mid_json)

        logger.info(f"[SMN] Input: source={doc.source_file}, parse_status={doc.parse_status}, "
                     f"kind={doc.document_kind}, chunks={len(doc.chunks)}, vlm_tasks={len(doc.vlm_tasks)}")

        if doc.parse_status not in ("SUCCESS", "ok", "success", "complete", "unknown"):
            warnings.append("parse_protocol_error")

        record["paper"] = self.meta_ext.extract(doc)
        logger.info(f"[SMN] Paper: title={str(record['paper'].get('title',''))[:60]}, "
                     f"year={record['paper'].get('year')}, doi={record['paper'].get('doi')}")

        candidates = self.recaller.recall(doc)
        logger.info(f"[SMN] Candidates (rule-based): {len(candidates)}")
        for c in candidates[:3]:
            logger.info(f"[SMN]   {c['name']} (sources={c.get('sources',set())})")

        llm_material_result = {}
        if self.material_identifier:
            try:
                title = doc.metadata.get("title", "")
                abstract_chunks = [c for c in doc.chunks[:5] if "abstract" in c.lower()[:200]]
                first_chunks = doc.chunks[:5]
                llm_material_result = await self.material_identifier.identify(
                    title=title,
                    abstract_chunks=abstract_chunks,
                    first_chunks=first_chunks,
                )
                if llm_material_result:
                    candidates = self.material_identifier.enhance_candidates(
                        candidates, llm_material_result, doc
                    )
                    logger.info(f"[SMN] LLM material identification: primary={llm_material_result.get('primary_nanozyme')}, "
                                f"related={[r['name'] for r in llm_material_result.get('related_systems', [])]}")
            except Exception as e:
                logger.warning(f"[SMN] MaterialIdentifier failed, using rule-based candidates only: {e}")

        if not candidates:
            warnings.append("no_candidates_found")
            record["diagnostics"]["warnings"] = warnings
            record["diagnostics"]["status"] = "partial"
            record["diagnostics"]["confidence"] = "low"
            record["diagnostics"]["needs_review"] = True
            return validate_schema(record)

        scored = self.scorer.score(candidates, doc)
        selected = scored[0]
        selected_name = selected["name"]
        ambiguous = selected.get("selection_ambiguous", False)

        logger.info(f"[SMN] Selected: {selected_name} (score={selected.get('score',0)}, "
                     f"sources={selected.get('sources',set())}, ambiguous={ambiguous})")

        all_candidate_names = [c["name"] for c in scored]
        from consistency_guard import ConsistencyGuard
        self._guard = ConsistencyGuard(selected_name, all_candidate_names, text_chunks=doc.chunks)
        self.bucket_builder.consistency_guard = self._guard
        logger.info(f"[SMN] ConsistencyGuard initialized for '{selected_name}', "
                     f"other candidates: {all_candidate_names[1:3]}")

        if self.config.enable_agentic_guard:
            if is_available("consistency_guard_agentic"):
                from consistency_guard_agentic import AgenticConsistencyGuard
                self._agentic_guard = AgenticConsistencyGuard(
                    selected_name, all_candidate_names, text_chunks=doc.chunks,
                    client=self.client,
                )
                logger.info(f"[SMN] AgenticConsistencyGuard initialized for '{selected_name}'")
            else:
                logger.warning("[SMN] consistency_guard_agentic not available, using base guard only")
                self._agentic_guard = None

        record["selected_nanozyme"]["name"] = selected_name
        if llm_material_result:
            record["selected_nanozyme"]["llm_identified"] = True
            record["selected_nanozyme"]["llm_confidence"] = llm_material_result.get("confidence", 0.0)
            related = llm_material_result.get("related_systems", [])
            if related:
                record["selected_nanozyme"]["related_systems"] = related

        buckets = self.bucket_builder.build(doc, selected_name, all_candidate_names)
        logger.info(f"[SMN] Buckets: " + ", ".join(f"{k}={len(v)}" for k, v in buckets.items()))

        record["raw_supporting_text"]["material"] = buckets.get("material", [])[:10]
        record["raw_supporting_text"]["activity"] = buckets.get("activity", [])[:10]
        record["raw_supporting_text"]["kinetics"] = buckets.get("kinetics", [])[:10]
        record["raw_supporting_text"]["application"] = buckets.get("application", [])[:10]

        tables = doc.table_task.get("tables", [])
        table_classified = self.table_proc.classify_and_summarize(tables, selected_name)
        table_kinetics_values = self.table_proc.get_kinetics_values(table_classified, selected_name)
        table_sensing_values = self.table_proc.get_sensing_values(table_classified, selected_name)
        table_characterization_values = self.table_proc.get_characterization_values(table_classified, selected_name)
        logger.info(f"[SMN] Tables: kinetics={len(table_classified.get('kinetics_tables',[]))}, "
                     f"comparison={len(table_classified.get('comparison_tables',[]))}, "
                     f"sensing={len(table_classified.get('sensing_tables',[]))}, "
                     f"characterization={len(table_classified.get('characterization_tables',[]))}")

        if self.client and self.config.enable_llm and doc.table_task:
            if is_available("llm_extractor"):
                try:
                    from llm_extractor import TableExtractor
                    tex = TableExtractor(self.client, batch_size=2)
                    table_llm_results = await tex.extract_all_tables(doc.table_task)
                    if table_llm_results:
                        for tr in table_llm_results:
                            if tr.get("error"):
                                continue
                            for rec in tr.get("records", []):
                                if not isinstance(rec, dict):
                                    continue
                                if rec.get("Km_value") is not None:
                                    table_kinetics_values.append({
                                        "parameter": "Km", "value": str(rec["Km_value"]),
                                        "unit": rec.get("Km_unit"), "substrate": rec.get("substrate"),
                                        "source": "table_llm",
                                    })
                                if rec.get("Vmax_value") is not None:
                                    table_kinetics_values.append({
                                        "parameter": "Vmax", "value": str(rec["Vmax_value"]),
                                        "unit": rec.get("Vmax_unit"), "substrate": rec.get("substrate"),
                                        "source": "table_llm",
                                    })
                                if rec.get("kcat_value") is not None:
                                    table_kinetics_values.append({
                                        "parameter": "kcat", "value": str(rec["kcat_value"]),
                                        "unit": rec.get("kcat_unit", "s⁻¹"), "substrate": None,
                                        "source": "table_llm",
                                    })
                                if rec.get("specific_activity_value") is not None:
                                    table_kinetics_values.append({
                                        "parameter": "specific_activity", "value": str(rec["specific_activity_value"]),
                                        "unit": rec.get("specific_activity_unit"), "substrate": None,
                                        "source": "table_llm",
                                    })
                                assay = rec.get("assay_condition", {})
                                if isinstance(assay, dict):
                                    cond = record["main_activity"]["conditions"]
                                    if assay.get("pH") is not None and cond.get("pH") is None:
                                        try:
                                            cond["pH"] = float(assay["pH"])
                                        except (ValueError, TypeError):
                                            cond["pH"] = str(assay["pH"])
                                    if assay.get("temperature") is not None and cond.get("temperature") is None:
                                        try:
                                            cond["temperature"] = float(assay["temperature"])
                                        except (ValueError, TypeError):
                                            cond["temperature"] = str(assay["temperature"])
                        logger.info(f"[SMN] TableExtractor: {len(table_llm_results)} tables processed, "
                                     f"kinetics_values now={len(table_kinetics_values)}")
                except Exception as e:
                    logger.warning(f"[SMN] TableExtractor failed: {e}, using rule-based table extraction only")
            else:
                logger.debug("[SMN] TableExtractor not available, using rule-based table extraction only")

        figure_summ = self.figure_proc.summarize(doc.vlm_tasks, selected_name)
        logger.info(f"[SMN] Figures: total={figure_summ['total']}, "
                     f"kinetics={figure_summ['kinetics_figures']}, "
                     f"morphology={figure_summ['morphology_figures']}")

        if self.llm_structured:
            try:
                _table_raw_texts = []
                for t in tables:
                    if isinstance(t, dict):
                        _table_raw_texts.append(t.get("raw_text", "") or t.get("text", ""))
                    elif isinstance(t, str):
                        _table_raw_texts.append(t)
                llm_structured_result = await self.llm_structured.extract_all(
                    selected_name, buckets,
                    table_texts=_table_raw_texts[:5] if _table_raw_texts else None,
                )
                if llm_structured_result:
                    self._apply_llm_structured_result(record, llm_structured_result)
                    logger.info(f"[SMN] LLM-structured: enzyme_type={llm_structured_result.get('enzyme_like_type')}, "
                                 f"Km={llm_structured_result.get('kinetics', {}).get('Km')}, "
                                 f"kinetics_list={len(llm_structured_result.get('kinetics_list', []))}, "
                                 f"morphology={llm_structured_result.get('morphology')}, "
                                 f"apps={len(llm_structured_result.get('applications', []))}")
            except Exception as e:
                logger.warning(f"[SMN] LLM-structured extraction failed, falling back to rules: {e}")

        self.rule_ext.extract_from_evidence(record, buckets, table_kinetics_values, selected_name, doc=doc)
        logger.info(f"[SMN] Rule extraction: enzyme_type={record['main_activity']['enzyme_like_type']}, "
                     f"Km={record['main_activity']['kinetics'].get('Km')}, "
                     f"apps={len(record.get('applications',[]))}")

        if table_characterization_values:
            sel = record.get("selected_nanozyme", {})
            for cv in table_characterization_values:
                param = cv.get("parameter", "")
                val = cv.get("value")
                unit = cv.get("unit")
                if param == "surface_area" and not sel.get("surface_area"):
                    sel["surface_area"] = f"{val} {unit}" if unit else str(val)
                elif param == "particle_size" and not sel.get("size"):
                    num_m = re.search(r'[\d.]+', str(val))
                    if num_m:
                        try:
                            sel["size"] = float(num_m.group())
                            sel["size_unit"] = unit or "nm"
                        except (ValueError, TypeError):
                            sel["size"] = f"{val} {unit}" if unit else str(val)
                    else:
                        sel["size"] = f"{val} {unit}" if unit else str(val)
            logger.info(f"[SMN] Table characterization values applied: {len(table_characterization_values)}")

        if self._agentic_guard and self.config.enable_agentic_guard:
            rule_check = self._agentic_guard.check_after_rule_extraction(record, buckets)
            if rule_check.action == "trigger_re_extraction":
                logger.warning(
                    f"[SMN] AgenticGuard rule checkpoint: {rule_check.re_extract_reason}. "
                    f"Fields: {rule_check.re_extract_fields}"
                )
                record["diagnostics"]["needs_review"] = True
            elif rule_check.action == "continue_with_warnings":
                warnings.extend(rule_check.warnings)
                logger.info(f"[SMN] AgenticGuard rule checkpoint warnings: {rule_check.warnings[:3]}")

        if self.config.enable_llm and self.client:
            if self.config.enable_llm_refinement:
                llm_result = await self._call_llm_with_refinement(
                    selected_name,
                    buckets, table_classified, figure_summ,
                )
            else:
                llm_result = await self._call_llm(
                    selected_name,
                    buckets, table_classified, figure_summ,
                )
            if llm_result:
                if self._agentic_guard and self.config.enable_agentic_guard:
                    llm_check = self._agentic_guard.check_after_llm_extraction(
                        record, llm_result, buckets,
                    )
                    if llm_check.issues and self.config.enable_llm_conflict_resolution:
                        for issue in llm_check.issues:
                            if issue.severity.value >= IssueSeverity.MEDIUM.value:
                                if issue.severity == IssueSeverity.HIGH and self.client:
                                    resolved = await self._agentic_guard.resolve_with_llm(issue, buckets)
                                    record["diagnostics"].setdefault("llm_resolutions", []).append({
                                        "field": resolved.field,
                                        "winner": resolved.resolved_by,
                                        "reasoning": resolved.resolution[:200],
                                    })
                                    logger.info(
                                        f"[SMN] LLM conflict resolved: {resolved.field} -> {resolved.resolved_by}"
                                    )
                if self.cross_validator:
                    record = self.cross_validator.merge_results(record, llm_result, [])
                    logger.info("[SMN] LLM merged via CrossValidationAgent")
                else:
                    record = self._merge_llm(record, llm_result)
                logger.info("[SMN] LLM extraction succeeded")
            else:
                warnings.append("llm_failed")
                logger.warning("[SMN] LLM failed, using rule-based partial")
        else:
            if not self.config.enable_llm:
                warnings.append("llm_disabled")
            else:
                warnings.append("llm_unavailable")
            logger.info("[SMN] LLM not available, rule-based only")

        if self.config.enable_vlm and self.client and doc.vlm_tasks:
            vlm_results = await self._call_vlm(doc.vlm_tasks, selected_name)

            table_fallback_tasks = doc.table_task.get("vlm_fallback_tasks", [])
            table_vlm_results = None
            if table_fallback_tasks and self.client:
                logger.info(f"[SMN] Processing {len(table_fallback_tasks)} table VLM fallback tasks")
                table_vlm_results = await self._call_table_vlm_fallback(
                    table_fallback_tasks, selected_name
                )

            all_vlm_results = []
            if vlm_results:
                all_vlm_results.extend(vlm_results)
            if table_vlm_results:
                all_vlm_results.extend(table_vlm_results)

            if all_vlm_results:
                if self.cross_validator:
                    record = self.cross_validator.merge_results(record, {}, all_vlm_results)
                    inconsistencies = self.cross_validator.check_multi_figure_kinetics_consistency(all_vlm_results)
                    if inconsistencies:
                        for inc in inconsistencies:
                            param = inc.get("parameter", "")
                            severity = inc.get("severity", "medium")
                            warnings.append(f"multi_figure_{param}_inconsistency")
                            logger.warning(
                                f"[SMN] Multi-figure inconsistency: {param} "
                                f"v1={inc.get('figure_1_value')} vs v2={inc.get('figure_2_value')} "
                                f"(diff={inc.get('relative_difference')}, severity={severity})"
                            )
                        record["main_activity"]["kinetics"]["needs_review"] = True
                    logger.info("[SMN] VLM merged via CrossValidationAgent")
                else:
                    record = self._merge_vlm(record, all_vlm_results)
                logger.info(f"[SMN] VLM extraction succeeded, {len(all_vlm_results)} figures/tables processed")
            else:
                warnings.append("vlm_failed_or_no_results")
                logger.warning("[SMN] VLM failed or no results")
        else:
            if not self.config.enable_vlm:
                warnings.append("vlm_disabled")
            elif not self.client:
                warnings.append("vlm_unavailable")
            logger.info("[SMN] VLM not available, using figure captions only")

        if self._verifier_class and self._guard:
            try:
                verifier = self._verifier_class(
                    text_chunks=doc.chunks,
                    selected_name=selected_name,
                    all_candidates=all_candidate_names,
                )
                verification = verifier.verify_record(record)
                if verification.get("hallucination_suspects"):
                    logger.warning(
                        f"[SMN] Verification: hallucination_suspects={verification['hallucination_suspects']}"
                    )
                    record = verifier.demote_hallucinated_kinetics(record, verification)
                    for hs in verification["hallucination_suspects"]:
                        warnings.append("hallucination_suspect")
                if verification.get("mismatches"):
                    for mm in verification["mismatches"]:
                        mm_type = mm.get("type", "")
                        if mm_type in ("cross_material_mismatch", "condition_mismatch", "activity_application_mismatch"):
                            warnings.append(mm_type)
                        logger.warning(f"[SMN] Verification mismatch: {mm_type} - {mm.get('detail', '')}")
                if verification.get("unverified_fields"):
                    for uf in verification["unverified_fields"]:
                        if "vlm" in uf.lower():
                            warnings.append("vlm_unverified")
                        elif "llm" in uf.lower() or "no_evidence" in uf.lower():
                            warnings.append("llm_no_evidence")
                logger.info(
                    f"[SMN] Verification: rate={verification.get('overall_verification_rate', 0):.1%}, "
                    f"suspects={len(verification.get('hallucination_suspects', []))}, "
                    f"mismatches={len(verification.get('mismatches', []))}"
                )
                self._verification_data = verification
            except Exception as e:
                logger.warning(f"[SMN] ExtractionVerifier failed: {e}")
                self._verification_data = None
        else:
            self._verification_data = None

        _calibrate_fn = get_attr("numeric_validator", "calibrate_magnitude_ranges")
        if _calibrate_fn:
            try:
                ctx = _calibrate_fn(doc.chunks)
                self.num_val.set_paper_context(ctx)
            except Exception as e:
                logger.debug(f"[SMN] Paper context calibration skipped: {e}")

        record, val_warnings = self.num_val.validate(record, strict=self.config.numeric_validation_strict)
        warnings.extend(val_warnings)

        self._backfill_kinetics_from_important_values(record)

        self._final_kinetics_validation(record)

        nanozyme_kin_warnings = self.num_val.validate_nanozyme_kinetics(record)
        if nanozyme_kin_warnings:
            warnings.extend(nanozyme_kin_warnings)
            logger.info(f"[SMN] Nanozyme kinetics domain warnings: {nanozyme_kin_warnings[:3]}")

        self._infer_profiles(record, buckets)

        if self._guard:
            consistency = self._guard.validate_record_consistency(record)
            if consistency["issues"]:
                logger.warning(f"[SMN] Consistency issues: {consistency['issues']}")
            if consistency["warnings"]:
                warnings.extend(consistency["warnings"])
            if not consistency["is_consistent"]:
                record["diagnostics"]["needs_review"] = True
            guard_warnings = self._guard.get_warnings()
            if guard_warnings:
                warnings.extend(guard_warnings)
                logger.info(f"[SMN] Guard warnings: {guard_warnings}")

        if table_sensing_values:
            apps = record.get("applications", [])
            for sv in table_sensing_values:
                matched = None
                for app in apps:
                    if app.get("application_type") in ("sensing", "biosensing", "detection"):
                        matched = app
                        break
                if matched:
                    if sv["parameter"] == "LOD" and not matched.get("detection_limit"):
                        matched["detection_limit"] = f"{sv['value']} {sv['unit']}" if sv.get("unit") else str(sv["value"])
                    elif sv["parameter"] == "linear_range" and not matched.get("linear_range"):
                        matched["linear_range"] = f"{sv['value']} {sv['unit']}" if sv.get("unit") else str(sv["value"])
                else:
                    app = {"application_type": "sensing", "target_analyte": None, "method": None,
                           "linear_range": None, "detection_limit": None, "sample_type": None, "notes": None,
                           "_evidence": str(sv)[:300]}
                    if sv["parameter"] == "LOD":
                        app["detection_limit"] = f"{sv['value']} {sv['unit']}" if sv.get("unit") else str(sv["value"])
                    elif sv["parameter"] == "linear_range":
                        app["linear_range"] = f"{sv['value']} {sv['unit']}" if sv.get("unit") else str(sv["value"])
                    apps.append(app)
            record["applications"] = apps

        if not record.get("applications"):
            record["applications_note"] = "当前文献未包含相关内容"
        else:
            record["applications_note"] = None

        record["diagnostics"]["warnings"] = warnings
        if self.diag_builder:
            if getattr(self, '_verification_data', None):
                self.diag_builder.set_verification(self._verification_data)
            if doc and doc.chunks:
                self.diag_builder.set_raw_text("\n".join(doc.chunks))
            self.diag_builder.set_selected_nanozyme_full(record.get("selected_nanozyme"))
            is_supp = (doc.document_kind == "supplementary" if doc else False) or (
                record.get("paper", {}).get("document_kind") == "supplementary"
            )
            self.diag_builder.set_supplementary(is_supp)
            self.diag_builder.set_selected_nanozyme(
                selected_name,
                ambiguous=ambiguous,
            )
            self.diag_builder.set_main_activity(record.get("main_activity"))
            self.diag_builder.set_kinetics(
                record.get("main_activity", {}).get("kinetics")
            )
            self.diag_builder.set_applications(record.get("applications", []))
            self.diag_builder.add_numeric_warnings(
                [w for w in warnings if w.startswith(("Km_", "Vmax_", "suspect_", "no_kinetics", "LOD_"))]
            )
            diag = self.diag_builder.build()
            if not record["raw_supporting_text"].get("material") and not record["raw_supporting_text"].get("activity"):
                if "sparse_evidence" not in diag.get("warnings", []):
                    diag.setdefault("warnings", []).append("sparse_evidence")
            record["diagnostics"] = diag
        else:
            has_name = bool(record["selected_nanozyme"].get("name"))
            has_activity = bool(record["main_activity"].get("enzyme_like_type"))
            has_kinetics = any(record["main_activity"]["kinetics"].get(k) is not None for k in ("Km", "Vmax"))
            has_app = any(app.get("application_type") is not None for app in record.get("applications", []))
            is_supp = (doc.document_kind == "supplementary" if doc else False) or (
                record.get("paper", {}).get("document_kind") == "supplementary"
            )
            if has_name and has_activity and (has_kinetics or has_app):
                status = "complete"
            elif has_name and has_activity:
                status = "partial"
            elif has_name:
                status = "partial"
            else:
                status = "failed"
            if is_supp:
                status = "partial"
            if status == "complete":
                confidence = "high"
            elif status == "partial" and has_name and has_activity:
                confidence = "medium"
            else:
                confidence = "low"
            needs_review = status != "complete" or bool(warnings)
            deduped_warnings = list(dict.fromkeys(warnings))
            if ambiguous:
                deduped_warnings.append("selected_material_ambiguous")
            if is_supp:
                deduped_warnings.append("supplementary_only")
            if not record["raw_supporting_text"].get("material") and not record["raw_supporting_text"].get("activity"):
                deduped_warnings.append("sparse_evidence")
            record["diagnostics"] = {
                "status": status,
                "confidence": confidence,
                "needs_review": needs_review,
                "warnings": deduped_warnings,
            }

        if self.consistency_agent:
            record, consistency_warnings = self.consistency_agent.normalize_output(record)
            if consistency_warnings:
                warnings.extend(consistency_warnings)
                record["diagnostics"]["warnings"] = warnings
                logger.info(f"[SMN] ConsistencyAgent warnings: {consistency_warnings}")

        record = validate_schema(record)

        sel_name = record.get("selected_nanozyme", {}).get("name")

        record = self._sync_kinetics_list(record)

        logger.info(f"[SMN] Final: status={record['diagnostics']['status']}, "
                     f"confidence={record['diagnostics']['confidence']}, "
                     f"warnings={record['diagnostics']['warnings']}")

        return record

    async def _call_llm(self, selected_name: str,
                        buckets: Dict[str, List[str]],
                        table_classified: Dict, figure_summ: Dict) -> Optional[Dict]:
        if not self.client:
            return None

        table_summaries_text = ""
        for tbl_type in ("kinetics_tables", "sensing_tables"):
            for tbl in table_classified.get(tbl_type, []):
                table_summaries_text += f"[{tbl['table_type']}] {tbl.get('text','')[:200]}\n"
                for row in tbl.get("this_work_rows", []):
                    table_summaries_text += f"  This work: {row.get('cells',[])}\n"

        figure_summaries_text = ""
        for s in figure_summ.get("summaries", []):
            if s["mentions_selected"]:
                figure_summaries_text += f"[{s['figure_type']}] {s['caption']}\n"

        user_prompt = _LLM_USER_TEMPLATE.format(
            selected_material=selected_name,
            material_evidence="\n".join(buckets.get("material", [])[:8]) or "(none)",
            synthesis_evidence="\n".join(buckets.get("synthesis", [])[:5]) or "(none)",
            characterization_evidence="\n".join(buckets.get("characterization", [])[:5]) or "(none)",
            activity_evidence="\n".join(buckets.get("activity", [])[:8]) or "(none)",
            kinetics_evidence="\n".join(buckets.get("kinetics", [])[:8]) or "(none)",
            application_evidence="\n".join(buckets.get("application", [])[:5]) or "(none)",
            mechanism_evidence="\n".join(buckets.get("mechanism", [])[:5]) or "(none)",
            table_summaries=table_summaries_text or "(none)",
            figure_summaries=figure_summaries_text or "(none)",
        )

        messages = [
            {"role": "system", "content": _LLM_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = await self.client.chat_completion_text(messages, temperature=0.1, max_tokens=2048)
            if not response:
                return None
            from llm_extractor import JSONFixer
            result = JSONFixer().fix_common_issues(response)
            if result:
                logger.info(f"[SMN] LLM JSON parsed, keys: {list(result.keys())}")
                return result
            logger.warning("[SMN] LLM JSON parse failed")
            return None
        except Exception as e:
            logger.error(f"[SMN] LLM call failed: {e}")
            return None

    async def _call_llm_with_refinement(
        self,
        selected_name: str,
        buckets: Dict[str, List[str]],
        table_classified: Dict,
        figure_summ: Dict,
    ) -> Optional[Dict]:
        if not self.client:
            return None

        table_summaries_text = ""
        for tbl_type in ("kinetics_tables", "sensing_tables"):
            for tbl in table_classified.get(tbl_type, []):
                table_summaries_text += f"[{tbl['table_type']}] {tbl.get('text','')[:200]}\n"
                for row in tbl.get("this_work_rows", []):
                    table_summaries_text += f"  This work: {row.get('cells',[])}\n"

        figure_summaries_text = ""
        for s in figure_summ.get("summaries", []):
            if s["mentions_selected"]:
                figure_summaries_text += f"[{s['figure_type']}] {s['caption']}\n"

        user_prompt = _LLM_USER_TEMPLATE.format(
            selected_material=selected_name,
            material_evidence="\n".join(buckets.get("material", [])[:8]) or "(none)",
            synthesis_evidence="\n".join(buckets.get("synthesis", [])[:5]) or "(none)",
            characterization_evidence="\n".join(buckets.get("characterization", [])[:5]) or "(none)",
            activity_evidence="\n".join(buckets.get("activity", [])[:8]) or "(none)",
            kinetics_evidence="\n".join(buckets.get("kinetics", [])[:8]) or "(none)",
            application_evidence="\n".join(buckets.get("application", [])[:5]) or "(none)",
            mechanism_evidence="\n".join(buckets.get("mechanism", [])[:5]) or "(none)",
            table_summaries=table_summaries_text or "(none)",
            figure_summaries=figure_summaries_text or "(none)",
        )

        if is_available("llm_refinement"):
            try:
                from llm_refinement import AgenticLLMExtractor, LLMSchemaValidator
                extractor = AgenticLLMExtractor(
                    client=self.client,
                    max_iterations=self.config.llm_refinement_max_iterations,
                    validator=LLMSchemaValidator(),
                )
                refinement_result = await extractor.extract_with_refinement(
                    system_prompt=_LLM_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    temperature=0.1,
                    max_tokens=2048,
                )

                if refinement_result.iterations > 1:
                    logger.info(
                        f"[SMN] LLM refinement: {refinement_result.iterations} iterations. "
                        f"History: {refinement_result.refinement_history[-2:]}"
                    )

                if refinement_result.validation_errors:
                    logger.warning(
                        f"[SMN] LLM final validation errors: "
                        f"{[f'{e.field}:{e.error_type.value}' for e in refinement_result.validation_errors[:5]]}"
                    )

                if refinement_result.result:
                    logger.info(f"[SMN] LLM refinement succeeded, keys: {list(refinement_result.result.keys())}")

                return refinement_result.result
            except Exception as e:
                logger.error(f"[SMN] LLM refinement call failed: {e}")
                return None
        else:
            logger.warning("[SMN] llm_refinement not available, falling back to _call_llm")
            return await self._call_llm(
                selected_name, buckets, table_classified, figure_summ,
            )

    _LLM_NAME_FIXES = [
        (re.compile(r'FeeNeC', re.I), 'Fe-N-C'),
        (re.compile(r'CueNeC', re.I), 'Cu-N-C'),
        (re.compile(r'CoeNeC', re.I), 'Co-N-C'),
        (re.compile(r'MneNeC', re.I), 'Mn-N-C'),
        (re.compile(r'ZneNeC', re.I), 'Zn-N-C'),
        (re.compile(r'NieNeC', re.I), 'Ni-N-C'),
        (re.compile(r'FeeN(?![a-z])', re.I), 'Fe-N'),
        (re.compile(r'CueN(?![a-z])', re.I), 'Cu-N'),
        (re.compile(r'CoeN(?![a-z])', re.I), 'Co-N'),
        (re.compile(r'MneN(?![a-z])', re.I), 'Mn-N'),
        (re.compile(r'FeeO(?![a-z])', re.I), 'Fe-O'),
        (re.compile(r'CueO(?![a-z])', re.I), 'Cu-O'),
        (re.compile(r'-NeC\b', re.I), '-N-C'),
        (re.compile(r'-Ne\b', re.I), '-N'),
        (re.compile(r'SAzymes?\b', re.I), 'SAzyme'),
    ]

    _ENZYME_TYPE_NORMALIZE = {
        "peroxidase": "peroxidase-like",
        "peroxidase (pod)": "peroxidase-like",
        "pod": "peroxidase-like",
        "pod-like": "peroxidase-like",
        "oxidase": "oxidase-like",
        "oxidase (oxd)": "oxidase-like",
        "oxd": "oxidase-like",
        "oxd-like": "oxidase-like",
        "catalase": "catalase-like",
        "catalase (cat)": "catalase-like",
        "cat": "catalase-like",
        "cat-like": "catalase-like",
        "superoxide dismutase": "superoxide-dismutase-like",
        "sod": "superoxide-dismutase-like",
        "sod-like": "superoxide-dismutase-like",
        "glutathione peroxidase": "glutathione-peroxidase-like",
        "gpx": "glutathione-peroxidase-like",
        "gpx-like": "glutathione-peroxidase-like",
        "glutathione oxidase": "glutathione-oxidase-like",
        "gshox": "glutathione-oxidase-like",
        "glucose oxidase": "glucose-oxidase-like",
        "gox": "glucose-oxidase-like",
        "gox-like": "glucose-oxidase-like",
        "esterase": "esterase-like",
        "phosphatase": "phosphatase-like",
        "alp": "phosphatase-like",
        "alp-like": "phosphatase-like",
        "nitroreductase": "nitroreductase-like",
        "ntr": "nitroreductase-like",
        "ntr-like": "nitroreductase-like",
        "hydrolase": "hydrolase-like",
        "laccase": "laccase-like",
        "haloperoxidase": "haloperoxidase-like",
        "tyrosinase": "tyrosinase-like",
        "nuclease": "nuclease-like",
        "cascade enzymatic": "cascade-enzymatic",
        "cascade enzyme": "cascade-enzymatic",
    }

    _APP_TYPE_NORMALIZE = {
        "sensing": "sensing",
        "detection": "sensing",
        "colorimetric detection": "sensing",
        "colorimetric sensing": "sensing",
        "biosensing": "sensing",
        "determination": "sensing",
        "monitoring": "sensing",
        "assay": "sensing",
        "diagnostic": "sensing",
        "diagnosis": "sensing",
        "imaging": "sensing",
        "photoacoustic imaging": "sensing",
        "therapeutic": "therapeutic",
        "therapy": "therapeutic",
        "catalytic therapy": "therapeutic",
        "antitumor": "therapeutic",
        "tumor therapy": "therapeutic",
        "immunotherapy": "therapeutic",
        "gene therapy": "therapeutic",
        "antibacterial": "antibacterial",
        "environmental": "environmental",
        "environmental monitoring": "environmental",
        "degradation": "environmental",
        "environmental remediation": "environmental",
        "antioxidant": "antioxidant",
        "biofilm_inhibition": "biofilm_inhibition",
        "anti-biofilm": "biofilm_inhibition",
    }

    def _normalize_enzyme_type(self, raw) -> str:
        if not raw:
            return raw
        if isinstance(raw, list):
            raw = " + ".join(str(r) for r in raw if r)
        if not isinstance(raw, str):
            raw = str(raw)
        lower = raw.strip().lower()
        if lower in self._ENZYME_TYPE_NORMALIZE:
            return self._ENZYME_TYPE_NORMALIZE[lower]
        if "-like" in lower:
            return lower
        if " and " in lower:
            parts = [self._normalize_enzyme_type(p.strip()) for p in lower.split(" and ")]
            return " + ".join(parts)
        if "/" in lower:
            parts = [self._normalize_enzyme_type(p.strip()) for p in lower.split("/")]
            return " + ".join(parts)
        for key, val in sorted(self._ENZYME_TYPE_NORMALIZE.items(), key=lambda kv: -len(kv[0])):
            if key in lower:
                return val
        return raw

    def _normalize_app_type(self, raw: str) -> str:
        if not raw:
            return raw
        lower = raw.strip().lower()
        if lower in self._APP_TYPE_NORMALIZE:
            return self._APP_TYPE_NORMALIZE[lower]
        for key, val in self._APP_TYPE_NORMALIZE.items():
            if key in lower:
                return val
        return raw

    _ANALYTE_JUNK_RE = re.compile(
        r'\s+(?:for\s+the\s+detection|for\s+detection|for\s+sensing|for\s+the\s+assay|'
        r'for\s+the\s+determin|based\s+on|via|using|by\s+\w+|with\s+\w+|in\s+\w+|of\s+\w+|at\s+\w+)\s*.*$',
        re.I,
    )

    def _clean_analyte_name(self, raw: str) -> str:
        if not raw:
            return raw
        cleaned = self._ANALYTE_JUNK_RE.sub('', raw).strip()
        if len(cleaned) > 50:
            cleaned = cleaned[:50].rsplit(' ', 1)[0].strip()
        if len(cleaned) < 2:
            return raw
        return cleaned

    _NAME_SUFFIX_JUNK_RE = re.compile(
        r'\s+(?:nanozymes?|SAzymes?|enzyme\s+mimics?|catalysts?|nanoparticles?|NPs?)\s*$',
        re.I,
    )

    def _clean_llm_name(self, name: str) -> str:
        if not name:
            return name
        for pat, repl in self._LLM_NAME_FIXES:
            name = pat.sub(repl, name)
        name = self._NAME_SUFFIX_JUNK_RE.sub('', name).strip()
        return name

    _MORPHOLOGY_VALID_TERMS = frozenset({
        "nanoparticle", "nanoparticles", "nanosheet", "nanosheets", "nanorod", "nanorods",
        "nanosphere", "nanospheres", "nanotube", "nanotubes", "nanocluster", "nanoclusters",
        "nanocube", "nanocubes", "nanowire", "nanowires", "nanoflower", "nanoflowers",
        "core-shell", "core@shell", "hollow", "porous", "cubic", "spherical", "rod",
        "sheet", "flower", "wire", "tube", "sphere", "prism", "dendritic", "ellipsoidal",
        "platelet", "belt", "ribbon", "dumbbell", "octahedral", "tetrahedral", "spindle",
        "needle", "flake", "lamellar", "layered", "amorphous", "crystalline", "mesoporous",
        "yolk-shell", "janus", "dot", "quantum dot", "cluster", "island", "film",
    })

    def _clean_llm_morphology(self, morph: str) -> Optional[str]:
        if not morph or not isinstance(morph, str):
            return None
        morph = morph.strip()
        if len(morph) > 100:
            return None
        morph_lower = morph.lower()
        has_valid = any(term in morph_lower for term in self._MORPHOLOGY_VALID_TERMS)
        if not has_valid:
            return None
        if any(kw in morph_lower for kw in ("figure", "schematic", "illustration",
                                              "depicting", "depicts", "showing",
                                              "shows", "image", "caption", "scale bar",
                                              "entering", "cell", "tumor", "therapy",
                                              "mechanism", "pathway", "reaction")):
            words = morph_lower.split()
            valid_words = [w for w in words if w in self._MORPHOLOGY_VALID_TERMS]
            if valid_words:
                return ", ".join(valid_words)
            return None
        return morph

    _PH_OPTIMAL_PATTERNS = [
        re.compile(r'\boptimal\s+pH\s*(?:was|=|:|of)\s*([\d.]+)', re.I),
        re.compile(r'\bpH\s+optimum\s*(?:was|=|:|of)\s*([\d.]+)', re.I),
        re.compile(r'\bmaximum\s+activity\s+(?:at|was\s+observed\s+at)\s+pH\s*([\d.]+)', re.I),
        re.compile(r'\bpH\s+([\d.]+)\s+(?:showed|exhibited|displayed)\s+(?:the\s+)?(?:highest|maximum|max)\s+activity', re.I),
        re.compile(r'\b(?:highest|maximum|max)\s+(?:activity|catalytic\s+activity)\s+(?:at|was\s+observed\s+at)\s+pH\s*([\d.]+)', re.I),
        re.compile(r'\bpH\s*([\d.]+)\s+was\s+the\s+optimal', re.I),
        re.compile(r'\bactivity\s+(?:peaked|peak)\s+at\s+pH\s*([\d.]+)', re.I),
    ]
    _PH_RANGE_PATTERNS = [
        re.compile(r'\bpH\s+(?:range|window)\s*(?:of|was|=|:)\s*([\d.]+)\s*[-–—to]+\s*([\d.]+)', re.I),
        re.compile(r'\bactive\s+(?:in|at|from)\s+pH\s*([\d.]+)\s*[-–—to]+\s*([\d.]+)', re.I),
        re.compile(r'\bpH\s*([\d.]+)\s*[-–—]\s*([\d.]+)\s+(?:was|were)\s+active', re.I),
    ]
    _PH_STABILITY_PATTERNS = [
        re.compile(r'\b(?:pH|pH\s+stability)\s*(?:range|window)\s*(?:of|was|=|:)\s*([\d.]+)\s*[-–—to]+\s*([\d.]+)', re.I),
        re.compile(r'\bstable\s+(?:in|at|from)\s+pH\s*([\d.]+)\s*[-–—to]+\s*([\d.]+)', re.I),
        re.compile(r'\bretained\s+.*?activity\s+.*?pH\s*([\d.]+)\s*[-–—to]+\s*([\d.]+)', re.I),
    ]
    _TEMP_OPTIMAL_PATTERNS = [
        re.compile(r'\boptimal\s+(?:temperature|temp)\s*(?:was|=|:|of)\s*([\d.]+)\s*°?C?', re.I),
        re.compile(r'\b(?:temperature|temp)\s+optimum\s*(?:was|=|:|of)\s*([\d.]+)\s*°?C?', re.I),
        re.compile(r'\bmaximum\s+activity\s+(?:at|was\s+observed\s+at)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\b(?:highest|maximum|max)\s+(?:activity|catalytic)\s+(?:at|was\s+observed\s+at)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\bactivity\s+(?:peaked|peak)\s+at\s*([\d.]+)\s*°?C', re.I),
    ]
    _TEMP_RANGE_PATTERNS = [
        re.compile(r'\btemperature\s+(?:range|window)\s*(?:of|was|=|:)\s*([\d.]+)\s*[-–—to]+\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\bactive\s+(?:in|at|from)\s*([\d.]+)\s*[-–—to]+\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\b([\d.]+)\s*[-–—]\s*([\d.]+)\s*°C\s+(?:was|were)\s+active', re.I),
    ]
    _THERMAL_STABILITY_PATTERNS = [
        re.compile(r'\bstable\s+(?:up\s+to|until)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\bretained\s+.*?activity\s+.*?(?:up\s+to|until)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\bthermal\s+stability\s*(?:up\s+to|until|:)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\bTGA\s+.*?stable\s+(?:up\s+to|until)\s*([\d.]+)\s*°?C', re.I),
    ]

    def _backfill_kinetics_from_important_values(self, record: Dict[str, Any]) -> None:
        kin = record.get("main_activity", {}).get("kinetics", {})
        ivs = record.get("important_values", [])
        if not ivs:
            return

        backfilled = []
        for iv in ivs:
            name = iv.get("name", "")
            val_str = iv.get("value")
            unit = iv.get("unit", "")
            source = iv.get("source", "")

            if not val_str:
                continue

            try:
                val = float(val_str)
            except (ValueError, TypeError):
                parsed = _parse_scientific_notation(str(val_str))
                if isinstance(parsed, (int, float)):
                    val = parsed
                else:
                    continue

            if name in ("Km", "VLM_Km", "LLM_Km", "LLM_Km_alternative") and kin.get("Km") is None:
                record["main_activity"]["kinetics"]["Km"] = val
                if unit and not kin.get("Km_unit"):
                    if _is_concentration_unit_fn and _is_concentration_unit_fn(unit):
                        record["main_activity"]["kinetics"]["Km_unit"] = _normalize_unit_fn(unit) if _normalize_unit_fn else unit
                    elif _is_rate_unit_fn and _is_rate_unit_fn(unit):
                        logger.warning(f"[SMN] Backfill Km_unit='{unit}' is a rate unit, not concentration. Skipping.")
                    else:
                        record["main_activity"]["kinetics"]["Km_unit"] = _normalize_unit_fn(unit) if _normalize_unit_fn else unit
                if not kin.get("source"):
                    record["main_activity"]["kinetics"]["source"] = source or "important_values"
                backfilled.append(f"Km={val}")
            elif name in ("Vmax", "VLM_Vmax", "LLM_Vmax", "LLM_Vmax_alternative") and kin.get("Vmax") is None:
                record["main_activity"]["kinetics"]["Vmax"] = val
                if unit and not kin.get("Vmax_unit"):
                    if _is_rate_unit_fn and _is_rate_unit_fn(unit):
                        record["main_activity"]["kinetics"]["Vmax_unit"] = _normalize_unit_fn(unit) if _normalize_unit_fn else unit
                    elif _is_concentration_unit_fn and _is_concentration_unit_fn(unit):
                        logger.warning(f"[SMN] Backfill Vmax_unit='{unit}' is a concentration unit, not rate. Skipping.")
                    else:
                        record["main_activity"]["kinetics"]["Vmax_unit"] = _normalize_unit_fn(unit) if _normalize_unit_fn else unit
                if not kin.get("source"):
                    record["main_activity"]["kinetics"]["source"] = source or "important_values"
                backfilled.append(f"Vmax={val}")
            elif name in ("kcat", "VLM_kcat", "LLM_kcat", "LLM_kcat_alternative") and kin.get("kcat") is None:
                record["main_activity"]["kinetics"]["kcat"] = val
                if unit and not kin.get("kcat_unit"):
                    if _normalize_unit_fn:
                        record["main_activity"]["kinetics"]["kcat_unit"] = _normalize_unit_fn(unit)
                backfilled.append(f"kcat={val}")
            elif name in ("kcat_Km", "VLM_kcat_Km", "LLM_kcat_Km", "LLM_kcat_Km_alternative") and kin.get("kcat_Km") is None:
                record["main_activity"]["kinetics"]["kcat_Km"] = val
                if unit and not kin.get("kcat_Km_unit"):
                    if _normalize_unit_fn:
                        record["main_activity"]["kinetics"]["kcat_Km_unit"] = _normalize_unit_fn(unit)
                backfilled.append(f"kcat_Km={val}")

        if backfilled:
            logger.info(f"[SMN] Backfilled kinetics from important_values: {', '.join(backfilled)}")

    def _final_kinetics_validation(self, record: Dict[str, Any]) -> None:
        kin = record.get("main_activity", {}).get("kinetics", {})
        if not isinstance(kin, dict):
            return

        km_val = kin.get("Km")
        km_u = kin.get("Km_unit", "")
        if isinstance(km_val, (int, float)) and km_u in ("M",):
            if km_val > 1.0:
                logger.warning(f"[SMN] Final validation: Km={km_val} M is unrealistically large, clearing.")
                kin["Km"] = None
                kin["Km_unit"] = None
                kin["needs_review"] = True
        elif isinstance(km_val, (int, float)) and km_u in ("mM",) and km_val > 1000:
            logger.warning(f"[SMN] Final validation: Km={km_val} mM is unrealistically large, clearing.")
            kin["Km"] = None
            kin["Km_unit"] = None
            kin["needs_review"] = True

        vmax_val = kin.get("Vmax")
        vmax_u = kin.get("Vmax_unit", "")
        if isinstance(vmax_val, (int, float)) and vmax_u in ("M/s", "M s^-1", "M s-1") and abs(vmax_val) < 1.0:
            new_val = vmax_val * 1e6
            kin["Vmax"] = new_val
            kin["Vmax_unit"] = "μM/s"
            logger.info(f"[SMN] Final validation: Vmax auto-converted {vmax_val} M/s -> {new_val} μM/s")
        elif isinstance(vmax_val, (int, float)) and vmax_u in ("mM/s", "mM s^-1", "mM s-1") and abs(vmax_val) < 1.0:
            new_val = vmax_val * 1e3
            kin["Vmax"] = new_val
            kin["Vmax_unit"] = "μM/s"
            logger.info(f"[SMN] Final validation: Vmax auto-converted {vmax_val} mM/s -> {new_val} μM/s")

        for kl in record.get("main_activity", {}).get("kinetics_list", []):
            if not isinstance(kl, dict):
                continue
            kl_km = kl.get("Km")
            kl_kmu = kl.get("Km_unit", "")
            if isinstance(kl_km, (int, float)) and kl_kmu in ("M",) and kl_km > 1.0:
                kl["Km"] = None
                kl["Km_unit"] = None
            kl_vmax = kl.get("Vmax")
            kl_vmaxu = kl.get("Vmax_unit", "")
            if isinstance(kl_vmax, (int, float)) and kl_vmaxu in ("M/s", "M s^-1", "M s-1") and abs(kl_vmax) < 1.0:
                kl["Vmax"] = kl_vmax * 1e6
                kl["Vmax_unit"] = "μM/s"

    def _infer_profiles(self, record: Dict[str, Any], buckets: Dict[str, List[str]]) -> None:
        act = record.get("main_activity", {})
        if not act:
            return

        pH_prof = act.get("pH_profile", {})
        temp_prof = act.get("temperature_profile", {})

        if pH_prof.get("optimal_pH") is None:
            for sentence in buckets.get("activity", []):
                for pat in self._PH_OPTIMAL_PATTERNS:
                    m = pat.search(sentence)
                    if m:
                        try:
                            pH_prof["optimal_pH"] = float(m.group(1))
                            logger.info(f"[SMN] Extracted optimal_pH={m.group(1)} from evidence")
                            break
                        except (ValueError, TypeError):
                            pass
                if pH_prof.get("optimal_pH") is not None:
                    break

        if pH_prof.get("pH_range") is None:
            for sentence in buckets.get("activity", []):
                for pat in self._PH_RANGE_PATTERNS:
                    m = pat.search(sentence)
                    if m:
                        pH_prof["pH_range"] = f"{m.group(1)}-{m.group(2)}"
                        break
                if pH_prof.get("pH_range") is not None:
                    break

        if temp_prof.get("optimal_temperature") is None:
            for sentence in buckets.get("activity", []):
                for pat in self._TEMP_OPTIMAL_PATTERNS:
                    m = pat.search(sentence)
                    if m:
                        temp_prof["optimal_temperature"] = f"{m.group(1)} °C"
                        logger.info(f"[SMN] Extracted optimal_temperature={m.group(1)}°C from evidence")
                        break
                if temp_prof.get("optimal_temperature") is not None:
                    break

        if temp_prof.get("temperature_range") is None:
            for sentence in buckets.get("activity", []):
                for pat in self._TEMP_RANGE_PATTERNS:
                    m = pat.search(sentence)
                    if m:
                        temp_prof["temperature_range"] = f"{m.group(1)}-{m.group(2)} °C"
                        break
                if temp_prof.get("temperature_range") is not None:
                    break

        act["pH_profile"] = pH_prof
        act["temperature_profile"] = temp_prof

    def _apply_llm_structured_result(self, record: Dict[str, Any], llm_result: Dict[str, Any]) -> None:
        ma = record.get("main_activity", {})
        if not isinstance(ma, dict):
            return

        if llm_result.get("enzyme_like_type") and not ma.get("enzyme_like_type"):
            ma["enzyme_like_type"] = llm_result["enzyme_like_type"]

        llm_kin = llm_result.get("kinetics", {})
        if isinstance(llm_kin, dict):
            kin = ma.get("kinetics", {})
            if not isinstance(kin, dict):
                kin = {}
                ma["kinetics"] = kin
            for key in ("Km", "Km_unit", "Vmax", "Vmax_unit", "kcat", "kcat_unit",
                         "kcat_Km", "kcat_Km_unit", "substrate"):
                if llm_kin.get(key) is not None and kin.get(key) is None:
                    kin[key] = llm_kin[key]

        llm_kin_list = llm_result.get("kinetics_list", [])
        if llm_kin_list and not ma.get("kinetics_list"):
            ma["kinetics_list"] = llm_kin_list

        sel = record.get("selected_nanozyme", {})
        if isinstance(sel, dict):
            for key in ("morphology", "size", "size_unit", "crystal_structure",
                         "surface_area", "synthesis_method"):
                if llm_result.get(key) is not None and not sel.get(key):
                    sel[key] = llm_result[key]
            llm_synth_cond = llm_result.get("synthesis_conditions")
            if isinstance(llm_synth_cond, dict):
                sc = sel.get("synthesis_conditions", {})
                if not isinstance(sc, dict):
                    sc = {}
                    sel["synthesis_conditions"] = sc
                for sc_key in ("temperature", "time"):
                    if llm_synth_cond.get(sc_key) is not None and not sc.get(sc_key):
                        sc[sc_key] = llm_synth_cond[sc_key]
                if llm_synth_cond.get("precursors") and not sc.get("precursors"):
                    sc["precursors"] = llm_synth_cond["precursors"]
            if llm_result.get("characterization") and not sel.get("characterization"):
                sel["characterization"] = llm_result["characterization"]

        llm_apps = llm_result.get("applications", [])
        if llm_apps and not record.get("applications"):
            from application_extractor import is_valid_analyte
            for app in llm_apps:
                analyte = app.get("target_analyte", "")
                if analyte and not is_valid_analyte(analyte):
                    app["target_analyte"] = None
            record["applications"] = llm_apps

        llm_ph = llm_result.get("pH_profile", {})
        if isinstance(llm_ph, dict):
            ph = ma.get("pH_profile", {})
            if not isinstance(ph, dict):
                ph = {}
                ma["pH_profile"] = ph
            for ph_key in ("optimal_pH", "pH_range"):
                if llm_ph.get(ph_key) is not None and not ph.get(ph_key):
                    ph[ph_key] = llm_ph[ph_key]

        llm_tp = llm_result.get("temperature_profile", {})
        if isinstance(llm_tp, dict):
            tp = ma.get("temperature_profile", {})
            if not isinstance(tp, dict):
                tp = {}
                ma["temperature_profile"] = tp
            for tp_key in ("optimal_temperature", "temperature_range"):
                if llm_tp.get(tp_key) is not None and not tp.get(tp_key):
                    tp[tp_key] = llm_tp[tp_key]

    def _merge_llm(self, record: Dict[str, Any], llm: Dict[str, Any]) -> Dict[str, Any]:
        if self._guard:
            llm_check = self._guard.check_llm_result_attribution(llm)
            if llm_check["issues"]:
                logger.warning(f"[SMN] LLM attribution issues: {llm_check['issues']}")
                llm = llm_check["filtered_result"]

        if "selected_nanozyme" in llm:
            llm_sel = llm["selected_nanozyme"]
            for key in list(record["selected_nanozyme"].keys()):
                if key == "synthesis_conditions" and "synthesis_conditions" in llm_sel:
                    if isinstance(llm_sel["synthesis_conditions"], dict):
                        for sk in list(record["selected_nanozyme"]["synthesis_conditions"].keys()):
                            if sk in llm_sel["synthesis_conditions"] and llm_sel["synthesis_conditions"][sk] is not None:
                                rule_val = record["selected_nanozyme"]["synthesis_conditions"].get(sk)
                                if rule_val is None:
                                    record["selected_nanozyme"]["synthesis_conditions"][sk] = llm_sel["synthesis_conditions"][sk]
                                else:
                                    record["selected_nanozyme"]["synthesis_conditions"][f"_llm_{sk}"] = llm_sel["synthesis_conditions"][sk]
                elif key == "name" and "name" in llm_sel and llm_sel["name"] is not None:
                    val = self._clean_llm_name(llm_sel["name"])
                    if self._guard:
                        val_lower = val.lower().strip()
                        sel_lower = self._guard.selected_lower
                        if val_lower != sel_lower and val_lower not in self._guard.selected_variants and sel_lower not in val_lower:
                            llm_is_more_specific = len(val) > len(record["selected_nanozyme"]["name"]) * 1.5
                            rule_is_generic = sel_lower in {p.lower() for p in _NON_MATERIAL_PHRASES} or sel_lower in {g.lower() for g in _GENERIC_PHRASES}
                            if llm_is_more_specific or rule_is_generic:
                                logger.info(
                                    f"[SMN] LLM name '{val}' is more specific than rule '{record['selected_nanozyme']['name']}'. "
                                    f"Using LLM name."
                                )
                                record["selected_nanozyme"]["name"] = val
                                record["selected_nanozyme"]["_name_source"] = "llm_override"
                            else:
                                logger.warning(
                                    f"[SMN] LLM name '{val}' doesn't match selected '{record['selected_nanozyme']['name']}'. "
                                    f"Keeping rule-based name."
                                )
                                record["selected_nanozyme"]["_llm_name_rejected"] = val
                        else:
                            record["selected_nanozyme"]["name"] = val
                    else:
                        record["selected_nanozyme"]["name"] = val
                elif key in llm_sel and llm_sel[key] is not None:
                    val = llm_sel[key]
                    if key == "morphology" and isinstance(val, str):
                        val = self._clean_llm_morphology(val)
                        if val is None:
                            continue
                    rule_val = record["selected_nanozyme"].get(key)
                    if rule_val is None:
                        record["selected_nanozyme"][key] = val
                    else:
                        _LOW_QUALITY_RULE_VALUES = {
                            "synthesis_method": {"general synthesis", "general_synthesis"},
                            "morphology": set(),
                        }
                        low_quality = _LOW_QUALITY_RULE_VALUES.get(key, set())
                        if rule_val in low_quality and val not in low_quality:
                            logger.info(
                                f"[SMN] LLM {key} '{val}' overrides low-quality rule '{rule_val}'"
                            )
                            record["selected_nanozyme"][key] = val
                            record["selected_nanozyme"][f"_llm_{key}_override_reason"] = "rule_value_low_quality"
                        else:
                            record["selected_nanozyme"][f"_llm_{key}"] = val

        if "main_activity" in llm:
            llm_act = llm["main_activity"]
            for key in list(record["main_activity"].keys()):
                if key == "conditions" and "conditions" in llm_act:
                    for ck in list(record["main_activity"]["conditions"].keys()):
                        if ck in llm_act["conditions"] and llm_act["conditions"][ck] is not None:
                            rule_val = record["main_activity"]["conditions"].get(ck)
                            if rule_val is None:
                                record["main_activity"]["conditions"][ck] = llm_act["conditions"][ck]
                            else:
                                record["main_activity"]["conditions"][f"_llm_{ck}"] = llm_act["conditions"][ck]
                elif key == "pH_profile" and "pH_profile" in llm_act:
                    if isinstance(llm_act["pH_profile"], dict):
                        for pk in list(record["main_activity"]["pH_profile"].keys()):
                            if pk in llm_act["pH_profile"] and llm_act["pH_profile"][pk] is not None:
                                rule_val = record["main_activity"]["pH_profile"].get(pk)
                                if rule_val is None:
                                    record["main_activity"]["pH_profile"][pk] = llm_act["pH_profile"][pk]
                                else:
                                    record["main_activity"]["pH_profile"][f"_llm_{pk}"] = llm_act["pH_profile"][pk]
                elif key == "temperature_profile" and "temperature_profile" in llm_act:
                    if isinstance(llm_act["temperature_profile"], dict):
                        for tk in list(record["main_activity"]["temperature_profile"].keys()):
                            if tk in llm_act["temperature_profile"] and llm_act["temperature_profile"][tk] is not None:
                                rule_val = record["main_activity"]["temperature_profile"].get(tk)
                                if rule_val is None:
                                    record["main_activity"]["temperature_profile"][tk] = llm_act["temperature_profile"][tk]
                                else:
                                    record["main_activity"]["temperature_profile"][f"_llm_{tk}"] = llm_act["temperature_profile"][tk]
                elif key == "kinetics" and "kinetics" in llm_act:
                    llm_kinetics = llm_act["kinetics"]
                    if isinstance(llm_kinetics, list):
                        if llm_kinetics:
                            llm_kinetics = llm_kinetics[0] if isinstance(llm_kinetics[0], dict) else {}
                        else:
                            llm_kinetics = {}
                    if not isinstance(llm_kinetics, dict):
                        llm_kinetics = {}
                    if isinstance(llm_kinetics, dict):
                        for kk in list(record["main_activity"]["kinetics"].keys()):
                            if kk in llm_kinetics and llm_kinetics[kk] is not None:
                                val = llm_kinetics[kk]
                                if kk == "substrate" and isinstance(val, (int, float)):
                                    logger.warning(f"[SMN] LLM kinetics.substrate is numeric ({val}), ignoring")
                                    continue
                                if kk in ("Km", "Vmax", "kcat", "kcat_Km") and isinstance(val, str):
                                    try:
                                        val = float(val)
                                    except (ValueError, TypeError):
                                        parsed = _parse_scientific_notation(val)
                                        if isinstance(parsed, (int, float)):
                                            val = parsed
                                        else:
                                            norm_val = _normalize_ocr_scientific(val)
                                            parsed2 = _parse_scientific_notation(norm_val)
                                            if isinstance(parsed2, (int, float)):
                                                val = parsed2
                                if kk in ("Km", "Vmax", "kcat", "kcat_Km") and isinstance(val, (int, float)):
                                    rule_val = record["main_activity"]["kinetics"].get(kk)
                                    if rule_val is not None and isinstance(rule_val, (int, float)):
                                        ratio = max(abs(val), abs(rule_val), 1e-10) / max(min(abs(val), abs(rule_val)), 1e-10)
                                        logger.debug(f"[SMN] kinetics merge: {kk} rule={rule_val} llm={val} ratio={ratio:.2f}")
                                        if ratio >= 100:
                                            rule_str = str(rule_val)
                                            llm_str = f"{val:.6e}"
                                            llm_mantissa = f"{abs(val):.4f}"
                                            rule_is_prefix = (
                                                llm_mantissa.startswith(rule_str[:4]) or
                                                rule_str.startswith(llm_mantissa[:4]) or
                                                (abs(rule_val) > 0 and abs(val / rule_val - round(val / rule_val)) < 0.01 and round(val / rule_val) in (1e7, 1e8, 1e6, 1e9))
                                            )
                                            _MAGNITUDE_RANGES = {
                                                "Km": (1e-9, 1.0),
                                                "Vmax": (1e-12, 1e6),
                                                "kcat": (1e-3, 1e8),
                                                "kcat_Km": (1e0, 1e10),
                                            }
                                            mag_range = _MAGNITUDE_RANGES.get(kk)
                                            rule_in_range = mag_range and mag_range[0] <= abs(rule_val) <= mag_range[1]
                                            llm_in_range = mag_range and mag_range[0] <= abs(val) <= mag_range[1]
                                            is_truncated = False
                                            if abs(val) > 0 and abs(rule_val) > 0:
                                                import math
                                                llm_mantissa_str = f"{abs(val):.6e}".split('e')[0].replace('.', '')
                                                rule_str_digits = rule_str.replace('.', '').lstrip('0')
                                                if len(rule_str_digits) >= 2 and llm_mantissa_str.startswith(rule_str_digits[:min(len(rule_str_digits), 4)]):
                                                    is_truncated = True
                                                if abs(rule_val) >= 1 and abs(val) < 1:
                                                    if rule_str.startswith(f"{abs(val):.1f}".lstrip('0').split('.')[0]):
                                                        is_truncated = True
                                            if rule_is_prefix or is_truncated:
                                                logger.info(
                                                    f"[SMN] LLM {kk}={val} differs by >100x from rule {kk}={rule_val}, "
                                                    f"but rule value appears to be a truncated parse. Using LLM value."
                                                )
                                                record["main_activity"]["kinetics"][kk] = val
                                                if f"_llm_{kk}_unit" in llm_kinetics and llm_kinetics[f"_llm_{kk}_unit"]:
                                                    raw_unit = llm_kinetics[f"_llm_{kk}_unit"]
                                                    if kk == "Km" and _is_concentration_unit_fn and _is_concentration_unit_fn(raw_unit):
                                                        record["main_activity"]["kinetics"][f"{kk}_unit"] = _normalize_unit_fn(raw_unit) if _normalize_unit_fn else raw_unit
                                                    elif kk == "Vmax" and _is_rate_unit_fn and _is_rate_unit_fn(raw_unit):
                                                        record["main_activity"]["kinetics"][f"{kk}_unit"] = _normalize_unit_fn(raw_unit) if _normalize_unit_fn else raw_unit
                                                    elif kk in ("kcat", "kcat_Km"):
                                                        record["main_activity"]["kinetics"][f"{kk}_unit"] = _normalize_unit_fn(raw_unit) if _normalize_unit_fn else raw_unit
                                                    elif kk == "Km" and _is_rate_unit_fn and _is_rate_unit_fn(raw_unit):
                                                        logger.warning(f"[SMN] LLM Km_unit='{raw_unit}' is a rate unit, not concentration. Skipping.")
                                                    elif kk == "Vmax" and _is_concentration_unit_fn and _is_concentration_unit_fn(raw_unit):
                                                        logger.warning(f"[SMN] LLM Vmax_unit='{raw_unit}' is a concentration unit, not rate. Skipping.")
                                                    else:
                                                        record["main_activity"]["kinetics"][f"{kk}_unit"] = _normalize_unit_fn(raw_unit) if _normalize_unit_fn else raw_unit
                                            elif not rule_in_range and llm_in_range:
                                                logger.info(
                                                    f"[SMN] LLM {kk}={val} differs by >100x from rule {kk}={rule_val}, "
                                                    f"but rule value is outside expected magnitude range. Using LLM value."
                                                )
                                                record["main_activity"]["kinetics"][kk] = val
                                                if f"_llm_{kk}_unit" in llm_kinetics and llm_kinetics[f"_llm_{kk}_unit"]:
                                                    _validate_and_assign_kinetics_unit(record["main_activity"]["kinetics"], kk, llm_kinetics[f"_llm_{kk}_unit"])
                                            else:
                                                logger.warning(
                                                    f"[SMN] LLM {kk}={val} differs by >100x from rule {kk}={rule_val}. "
                                                    f"Keeping rule-based value. LLM value saved to important_values."
                                                )
                                                record["main_activity"]["kinetics"][f"_llm_{kk}_rejected"] = val
                                                record["important_values"].append({
                                                    "name": f"LLM_{kk}_alternative",
                                                    "value": str(val),
                                                    "unit": record["main_activity"]["kinetics"].get(f"{kk}_unit", ""),
                                                    "context": "LLM alternative value, differs from rule-based",
                                                    "source": "LLM",
                                                    "needs_review": True,
                                                })
                                            continue
                                        elif ratio > 10:
                                            rule_str = str(rule_val)
                                            llm_mantissa = f"{abs(val):.4f}"
                                            rule_is_prefix = (
                                                llm_mantissa.startswith(rule_str[:4]) or
                                                rule_str.startswith(llm_mantissa[:4]) or
                                                (abs(rule_val) > 0 and abs(val / rule_val - round(val / rule_val)) < 0.01 and round(val / rule_val) in (1e7, 1e8, 1e6, 1e9))
                                            )
                                            _MAGNITUDE_RANGES_10X = {
                                                "Km": (1e-9, 1.0),
                                                "Vmax": (1e-12, 1e6),
                                                "kcat": (1e-3, 1e8),
                                                "kcat_Km": (1e0, 1e12),
                                            }
                                            mag_range = _MAGNITUDE_RANGES_10X.get(kk)
                                            rule_in_range = mag_range and mag_range[0] <= abs(rule_val) <= mag_range[1]
                                            llm_in_range = mag_range and mag_range[0] <= abs(val) <= mag_range[1]
                                            is_truncated = False
                                            if abs(val) > 0 and abs(rule_val) > 0:
                                                llm_mantissa_str = f"{abs(val):.6e}".split('e')[0].replace('.', '')
                                                rule_str_digits = rule_str.replace('.', '').lstrip('0')
                                                if len(rule_str_digits) >= 2 and llm_mantissa_str.startswith(rule_str_digits[:min(len(rule_str_digits), 4)]):
                                                    is_truncated = True
                                                if abs(rule_val) >= 1 and abs(val) < 1:
                                                    if rule_str.startswith(f"{abs(val):.1f}".lstrip('0').split('.')[0]):
                                                        is_truncated = True
                                            rule_unit = record["main_activity"]["kinetics"].get(f"{kk}_unit")
                                            rule_unit_abnormal = rule_unit is None or (isinstance(rule_unit, str) and "×10" in rule_unit)
                                            if rule_is_prefix or is_truncated:
                                                logger.info(
                                                    f"[SMN] LLM {kk}={val} differs by >10x from rule {kk}={rule_val}, "
                                                    f"but rule value appears to be a truncated parse. Using LLM value."
                                                )
                                                record["main_activity"]["kinetics"][kk] = val
                                                if f"_llm_{kk}_unit" in llm_kinetics and llm_kinetics[f"_llm_{kk}_unit"]:
                                                    _validate_and_assign_kinetics_unit(record["main_activity"]["kinetics"], kk, llm_kinetics[f"_llm_{kk}_unit"])
                                            elif not rule_in_range and llm_in_range:
                                                logger.info(
                                                    f"[SMN] LLM {kk}={val} differs by >10x from rule {kk}={rule_val}, "
                                                    f"but rule value is outside expected magnitude range. Using LLM value."
                                                )
                                                record["main_activity"]["kinetics"][kk] = val
                                                if f"_llm_{kk}_unit" in llm_kinetics and llm_kinetics[f"_llm_{kk}_unit"]:
                                                    _validate_and_assign_kinetics_unit(record["main_activity"]["kinetics"], kk, llm_kinetics[f"_llm_{kk}_unit"])
                                            elif rule_unit_abnormal:
                                                logger.info(
                                                    f"[SMN] LLM {kk}={val} differs by >10x from rule {kk}={rule_val}, "
                                                    f"but rule value has abnormal/missing unit ('{rule_unit}'). Using LLM value."
                                                )
                                                record["main_activity"]["kinetics"][kk] = val
                                                if f"_llm_{kk}_unit" in llm_kinetics and llm_kinetics[f"_llm_{kk}_unit"]:
                                                    _validate_and_assign_kinetics_unit(record["main_activity"]["kinetics"], kk, llm_kinetics[f"_llm_{kk}_unit"])
                                            else:
                                                logger.warning(
                                                    f"[SMN] LLM {kk}={val} differs by >10x from rule {kk}={rule_val}. "
                                                    f"Keeping rule-based value. LLM value saved as alternative."
                                                )
                                                record["main_activity"]["kinetics"][f"_llm_{kk}_alternative"] = val
                                                record["important_values"].append({
                                                    "name": f"LLM_{kk}_alternative",
                                                    "value": str(val),
                                                    "unit": record["main_activity"]["kinetics"].get(f"{kk}_unit", ""),
                                                    "context": "LLM alternative value, differs from rule-based",
                                                    "source": "LLM",
                                                    "needs_review": True,
                                                })
                                            continue
                                        else:
                                            record["main_activity"]["kinetics"][f"_{kk}_source"] = "rule_primary"
                                            record["main_activity"]["kinetics"][f"_llm_{kk}_alternative"] = val
                                            record["important_values"].append({
                                                "name": f"LLM_{kk}_alternative",
                                                "value": str(val),
                                                "unit": record["main_activity"]["kinetics"].get(f"{kk}_unit", ""),
                                                "context": f"LLM alternative value (rule={rule_val}, within 10x)",
                                                "source": "LLM",
                                                "needs_review": True,
                                            })
                                            logger.info(
                                                f"[SMN] Rule {kk}={rule_val} kept over LLM {kk}={val} (within 10x). "
                                                f"LLM value saved as alternative."
                                            )
                                            continue
                                else:
                                    record["main_activity"]["kinetics"][kk] = val
                                    llm_ev = llm_kinetics.get(f"evidence_{kk}") or llm_kinetics.get("evidence_text")
                                    if llm_ev:
                                        record["main_activity"]["kinetics"][f"_evidence_{kk}"] = str(llm_ev)[:300]
                                    else:
                                        record["main_activity"]["kinetics"]["_llm_no_evidence"] = True
                        for kk in llm_kinetics:
                            if kk.startswith("_"):
                                continue
                            if kk in record["main_activity"]["kinetics"]:
                                continue
                            if llm_kinetics[kk] is None:
                                continue
                            val = llm_kinetics[kk]
                            if kk == "substrate" and isinstance(val, (int, float)):
                                continue
                            if kk in ("Km", "Vmax", "kcat", "kcat_Km"):
                                if isinstance(val, str):
                                    try:
                                        val = float(val)
                                    except (ValueError, TypeError):
                                        parsed = _parse_scientific_notation(val)
                                        if isinstance(parsed, (int, float)):
                                            val = parsed
                                        else:
                                            norm_val = _normalize_ocr_scientific(val)
                                            parsed2 = _parse_scientific_notation(norm_val)
                                            if isinstance(parsed2, (int, float)):
                                                val = parsed2
                                            else:
                                                continue
                                if not isinstance(val, (int, float)):
                                    continue
                                record["main_activity"]["kinetics"][kk] = val
                                record["main_activity"]["kinetics"][f"_{kk}_source"] = "llm_supplement"
                                if f"_llm_{kk}_unit" in llm_kinetics and llm_kinetics[f"_llm_{kk}_unit"]:
                                    _validate_and_assign_kinetics_unit(record["main_activity"]["kinetics"], kk, llm_kinetics[f"_llm_{kk}_unit"])
                                llm_ev = llm_kinetics.get(f"evidence_{kk}") or llm_kinetics.get("evidence_text")
                                if llm_ev:
                                    record["main_activity"]["kinetics"][f"_evidence_{kk}"] = str(llm_ev)[:300]
                                else:
                                    record["main_activity"]["kinetics"]["_llm_no_evidence"] = True
                            else:
                                record["main_activity"]["kinetics"][kk] = val
                elif key == "enzyme_like_type" and "enzyme_like_type" in llm_act and llm_act["enzyme_like_type"] is not None:
                    llm_type = self._normalize_enzyme_type(llm_act["enzyme_like_type"])
                    rule_type = record["main_activity"].get("enzyme_like_type")
                    if rule_type and rule_type != "unknown" and rule_type != llm_type:
                        if "+" in rule_type or "+" in llm_type:
                            record["main_activity"]["enzyme_like_type"] = llm_type
                        else:
                            _ENZYME_SUBTYPES = {
                                "oxidase-like": {"glucose-oxidase-like", "glutathione-oxidase-like"},
                                "peroxidase-like": {"glutathione-peroxidase-like", "haloperoxidase-like"},
                                "dismutase-like": {"superoxide-dismutase-like"},
                            }
                            rule_core = rule_type.lower().replace("-like", "").strip()
                            llm_core = llm_type.lower().replace("-like", "").strip()
                            is_subtype = False
                            for parent, children in _ENZYME_SUBTYPES.items():
                                if rule_type == parent and llm_type in children:
                                    is_subtype = True
                                    break
                                if llm_type == parent and rule_type in children:
                                    is_subtype = True
                                    break
                            if is_subtype:
                                if len(llm_type) >= len(rule_type):
                                    record["main_activity"]["enzyme_like_type"] = llm_type
                                else:
                                    record["main_activity"]["_llm_enzyme_type_rejected"] = llm_type
                            else:
                                logger.warning(
                                    f"[SMN] LLM enzyme_type='{llm_type}' conflicts with rule='{rule_type}'. "
                                    f"Keeping rule-based value."
                                )
                                record["main_activity"]["_llm_enzyme_type_rejected"] = llm_type
                    else:
                        record["main_activity"]["enzyme_like_type"] = llm_type
                elif key in llm_act and llm_act[key] is not None:
                    rule_val = record["main_activity"].get(key)
                    if rule_val is None:
                        record["main_activity"][key] = llm_act[key]
                    else:
                        record["main_activity"][f"_llm_{key}"] = llm_act[key]

        if "main_activity" in llm:
            llm_act = llm["main_activity"]
            if "kinetics_list" in llm_act and isinstance(llm_act["kinetics_list"], list):
                valid_kin_list = []
                for entry in llm_act["kinetics_list"]:
                    if isinstance(entry, dict) and any(v is not None for v in entry.values()):
                        valid_kin_list.append(entry)
                if valid_kin_list:
                    existing_kl = record["main_activity"].get("kinetics_list", [])
                    existing_subs = {k.get("substrate") for k in existing_kl}
                    for vk in valid_kin_list:
                        sub = vk.get("substrate")
                        if sub not in existing_subs:
                            existing_kl.append(vk)
                            existing_subs.add(sub)
                        else:
                            for ek in existing_kl:
                                if ek.get("substrate") == sub:
                                    for fk, fv in vk.items():
                                        if fv is not None and ek.get(fk) is None:
                                            ek[fk] = fv
                                    break
                    record["main_activity"]["kinetics_list"] = existing_kl

        if "applications" in llm and isinstance(llm["applications"], list):
            valid = []
            for a in llm["applications"]:
                if not isinstance(a, dict):
                    continue
                if not any(v is not None for v in a.values()):
                    continue
                if a.get("application_type"):
                    a["application_type"] = self._normalize_app_type(a["application_type"])
                if a.get("target_analyte"):
                    a["target_analyte"] = self._clean_analyte_name(a["target_analyte"])
                    from application_extractor import is_valid_analyte
                    if not is_valid_analyte(a["target_analyte"] or ""):
                        a["target_analyte"] = None
                valid.append(a)
            if valid:
                existing_apps = record.get("applications", [])
                existing_keys = set()
                for ea in existing_apps:
                    key = (ea.get("application_type"), ea.get("target_analyte"))
                    existing_keys.add(key)
                for va in valid:
                    key = (va.get("application_type"), va.get("target_analyte"))
                    if key not in existing_keys:
                        if va.get("evidence_text") and not va.get("_evidence"):
                            va["_evidence"] = str(va["evidence_text"])[:300]
                        existing_apps.append(va)
                        existing_keys.add(key)
                    else:
                        for ea in existing_apps:
                            if (ea.get("application_type"), ea.get("target_analyte")) == key:
                                for fk, fv in va.items():
                                    if fv is not None and ea.get(fk) is None:
                                        ea[fk] = fv
                                break
                record["applications"] = existing_apps

        if "important_values" in llm and isinstance(llm["important_values"], list):
            valid = [v for v in llm["important_values"] if isinstance(v, dict) and v.get("value") is not None]
            if valid:
                existing_iv = record.get("important_values", [])
                existing_names = {iv.get("name") for iv in existing_iv}
                for v in valid:
                    if v.get("name") not in existing_names:
                        existing_iv.append(v)
                        existing_names.add(v.get("name"))
                record["important_values"] = existing_iv

        return record
