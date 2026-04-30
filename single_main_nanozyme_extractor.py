import json
import re
import logging
import asyncio
from copy import deepcopy
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from consistency_guard_agentic import IssueSeverity
except ImportError:
    class IssueSeverity:
        LOW = type('Enum', (), {'value': 'low'})()
        MEDIUM = type('Enum', (), {'value': 'medium'})()
        HIGH = type('Enum', (), {'value': 'high'})()
        CRITICAL = type('Enum', (), {'value': 'critical'})()

EXTRACTION_MODE = "single_main_nanozyme"
SCHEMA_VERSION = "single_main_nanozyme.v2"

FORBIDDEN_OLD_FIELDS = frozenset({
    "nanozyme_systems", "catalytic_activities", "benchmark_records",
    "assay_graph", "systems_count", "activities_count",
    "single_record_assembler", "system_name",
})

EMPTY_RECORD = {
    "paper": {
        "title": None, "authors": None, "journal": None,
        "year": None, "doi": None, "source_file": None, "document_kind": None,
    },
    "selected_nanozyme": {
        "name": None, "selection_reason": None, "composition": None,
        "morphology": None, "size": None, "size_unit": None,
        "size_distribution": None, "metal_elements": [],
        "dopants_or_defects": [], "synthesis_method": None,
        "synthesis_conditions": {
            "temperature": None, "time": None, "precursors": [],
            "method_detail": None,
        },
        "crystal_structure": None, "surface_area": None,
        "zeta_potential": None, "pore_size": None,
        "characterization": [], "stability": None,
    },
    "main_activity": {
        "enzyme_like_type": None, "substrates": [], "assay_method": None,
        "signal": None,
        "conditions": {
            "buffer": None, "pH": None, "temperature": None, "reaction_time": None,
        },
        "pH_profile": {
            "optimal_pH": None, "pH_range": None, "pH_stability_range": None,
        },
        "temperature_profile": {
            "optimal_temperature": None, "temperature_range": None,
            "thermal_stability": None,
        },
        "kinetics": {
            "Km": None, "Km_unit": None, "Vmax": None, "Vmax_unit": None,
            "kcat": None, "kcat_unit": None,
            "kcat_Km": None, "kcat_Km_unit": None,
            "substrate": None, "source": None, "needs_review": False,
        },
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
})

_RATIO_PATTERN = re.compile(r'^[A-Za-z]/[A-Za-z]', re.I)

_REAGENT_NAMES = frozenset({
    "NaAc", "NaCl", "KCl", "NaOH", "HCl", "H2SO4", "HNO3",
    "PBS", "Tris", "HEPES", "MES", "MOPS", "CH3COOH",
    "Na2HPO4", "NaH2PO4", "EDTA", "SDS", "CTAB",
    "DMF", "DMSO", "THF", "EtOH", "CH3OH",
    "Na2CO3", "NaHCO3", "CaCl2", "MgCl2",
    "Na2SO4", "NaNO3", "KNO3", "NH4Cl",
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
})

_SUBSTRATE_PLUS_RE = re.compile(
    r'^(?:' + '|'.join(re.escape(s) for s in _SUBSTRATE_NAMES) + r')\s+(?:system|solution|mixture|assay|reaction)$',
    re.I,
)

_SENTENCE_ID_RE = re.compile(r'^S\d{3,}$', re.I)

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
    r"(?:\b[A-Z][a-z]?\d*(?:[A-Z][a-z]?\d*)+\b)"
    r"|(?:\b[A-Z][a-z]?O\d*\b)"
    r"|(?:\b(?:Fe|Co|Ni|Mn|Cu|Zn|Ce|Au|Ag|Pt|Pd|Ti|V|Cr|Mo|W|Ru|Rh|Ir|"
    r"La|Pr|Nd|Sm|Eu|Gd|Tb|Dy|Ho|Er|Tm|Yb|Lu)\d*(?:O\d*)?"
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
    r'\b(?:Fe|Co|Ni|Mn|Cu|Zn|Ce|Au|Ag|Pt|Pd|Ti|V|Cr|Mo|W|Ru|Rh|Ir|La|Pr|Nd|Sm|Eu|Gd|Tb|Dy|Ho|Er|Tm|Yb|Lu)\d*'
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
    (re.compile(r'\bperoxidase[-\s]?like\b', re.I), "peroxidase-like"),
    (re.compile(r'\bPOD[-\s]?like\b', re.I), "peroxidase-like"),
    (re.compile(r'\boxidase[-\s]?like\b', re.I), "oxidase-like"),
    (re.compile(r'\bOXD[-\s]?like\b', re.I), "oxidase-like"),
    (re.compile(r'\bcatalase[-\s]?like\b', re.I), "catalase-like"),
    (re.compile(r'\bCAT[-\s]?like\b', re.I), "catalase-like"),
    (re.compile(r'\bsuperoxide\s+dismutase[-\s]?like\b', re.I), "superoxide-dismutase-like"),
    (re.compile(r'\bSOD[-\s]?like\b', re.I), "superoxide-dismutase-like"),
    (re.compile(r'\bglutathione\s+peroxidase[-\s]?like\b', re.I), "glutathione-peroxidase-like"),
    (re.compile(r'\bGPx[-\s]?like\b', re.I), "glutathione-peroxidase-like"),
    (re.compile(r'\besterase[-\s]?like\b', re.I), "esterase-like"),
    (re.compile(r'\bcascade\s+enzym\w+\s+activ', re.I), "cascade-enzymatic"),
    (re.compile(r'\bglutathione\s+oxidase[-\s]?like\b', re.I), "glutathione-oxidase-like"),
    (re.compile(r'\bGOx[-\s]?like\b', re.I), "glucose-oxidase-like"),
    (re.compile(r'\bglucose\s+oxidase[-\s]?like\b', re.I), "glucose-oxidase-like"),
]

_SUBSTRATE_KEYWORDS = {
    "TMB", "ABTS", "OPD", "H2O2", "DCFH", "DCFH-DA",
    "guaiacol", "pyrogallol", "catechol",
}

_KM_PATTERNS = [
    re.compile(r'\bKm\s*[\(（]\s*(\w[\w\d\-]*)\s*[\)）]\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*)?(mM|μM|uM|M|mmol|umol|nmol)', re.I),
    re.compile(r'\bKm\s+for\s+(\w[\w\d\-]*)\s+(?:\w+\s+){0,2}(?:was|=|:|≈|~)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*)?(mM|μM|uM|M|mmol|umol|nmol)', re.I),
    re.compile(r'\bapparent\s+Km\s+(?:\w+\s+){0,2}(?:was|=|:|≈|~)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*)?(mM|μM|uM|M|mmol|umol|nmol)', re.I),
    re.compile(r'\bKm\s+value\s+(?:toward|for|of)\s+(\w[\w\d\-]*)\s+.*?(?:was|is|=|:|≈|~|calculated\s+to\s+be)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*)?(mM|μM|uM|M|mmol|umol|nmol)', re.I),
    re.compile(r'\bKm\s*[\(（]\s*(mM|μM|uM|M|mmol|umol|nmol)\s*[\)）]\s+([\d.]+)', re.I),
    re.compile(r'\bKm\s*(?:was|is|=|:|≈|~)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*)?(mM|μM|uM|M|mmol|umol|nmol)', re.I),
    re.compile(r'\bKm\s+of\s+(\w[\w\d\-]*)\s+(?:was|is|=|:|≈|~)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*)?(mM|μM|uM|M|mmol|umol|nmol)', re.I),
    re.compile(r'\bKm\s*[\(（]\s*(\w[\w\d\-]*)\s*[\)）]\s*=\s*([\d.]+)\s*[×x]\s*10[\^⁻\-–]?\s*[-]?(\d+)\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bMichaelis\s+constant\s*(?:for\s+)?(\w[\w\d\-]*)?\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bMichaelis[\s-]*Menten\s+constant\s*\)?\s*[^.]{0,60}?(?:was\s+)?(?:calculated\s+to\s+be|found\s+to\s+be)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*|\s+[\d.]+\s+)?(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\s*\)?\s*[^.]{0,60}?(?:was\s+)?(?:calculated\s+to\s+be|found\s+to\s+be)\s*([\d.]+)\s*(?:±\s*[\d.]+\s*|\s+[\d.]+\s+)?(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\s+(?:values?\s+)?(?:to|toward|for)\s+(\S+)\s+(?:and|&)\s+\S+\s+(?:are|were|is|was)\s*([\d.]+)\s+(?:and|&)\s*[\d.]+\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\s+(?:was|is|were|are)\s*(?:calculated\s+(?:to\s+be|as)\s+)?(?:approximately\s+)?([\d.]+)\s*(?:±\s*[\d.]+\s*)?(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\b[^.]{0,40}?\(([\d.]+)\s*(mM|μM|uM|M)\)', re.I),
    re.compile(r'\bKm\s*(?:of|for)\s+\S+\s+(?:toward|to)\s+\w[\w\d\-]*\s+(?:was|is|=|:)\s*([\d.]+)\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\s+values?\s+(?:of|for)\s+\S+\s+(?:for\s+)?(?:and|&)?\s*\S*\s+(?:are|were|is|was)\s*([\d.]+)\s*(?:and|&|,)\s*[\d.]+\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\s+values?\s+of\s+([\d.]+)\s*(mM|μM|uM|M)\s+(?:and|&|,)\s*[\d.]+\s*(?:mM|μM|uM|M)?', re.I),
    re.compile(r'\bKm\b\s*\)?\s*(?:were|was|are|is)\s*([\d.]+)\s*(?:and|&|,)\s*[\d.]+\s*(mM|μM|uM|M)', re.I),
    re.compile(r'\bKm\b[^.]{0,30}?\bare\s*([\d.]+)\s*(?:and|&)\s*[\d.]+\s*(mM|μM|uM|M)', re.I),
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
    re.compile(r'\bkcat\s*[\(（]\s*(\w[\w\d\-]*)\s*[\)）]\s*(?:was|=|:|≈|~)\s*([\d.]+(?:\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-)?\s*[-]?\d+)?)\s*(s(?:\u207b|\u2212|\u2013|-)?1|s-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bkcat(?!\s*/\s*Km)\s+(?:for\s+)?(\w[\w\d\-]*)?\s*(?:was|=|:|≈|~)\s*([\d.]+(?:\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-)?\s*[-]?\d+)?)\s*(s(?:\u207b|\u2212|\u2013|-)?1|s-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bkcat(?!\s*/\s*Km)\s*(?:was|=|:|≈|~)\s*([\d.]+(?:\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-)?\s*[-]?\d+)?)\s*(s(?:\u207b|\u2212|\u2013|-)?1|s-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bturnover\s+(?:number|frequency)\s*(?:was|=|:|≈|~)\s*([\d.]+(?:\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-)?\s*[-]?\d+)?)\s*(s(?:\u207b|\u2212|\u2013|-)?1|s-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bkcat(?!\s*/\s*Km)\s*(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)\s*(s(?:\u207b|\u2212|\u2013|-)?1|s-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bkcat(?!\s*/\s*Km)\b[^.=]{0,20}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*[×x\u00d7]?\s*10(?:\u207b|\u2212|\u2013|-)\s*(\d+)\s*(s(?:\u207b|\u2212|\u2013|-)?1|s-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bcatalytic\s+(?:rate\s+)?constant\s*(?:was|=|:|≈|~|\u2248)\s*([\d.]+(?:\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-)?\s*[-]?\d+)?)\s*(s(?:\u207b|\u2212|\u2013|-)?1|s-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bkcat\s*=\s*([\d.]+)\s*(s(?:\u207b|\u2212|\u2013|-)?1|s-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bkcat(?!\s*/\s*Km)\b[^.=]{0,30}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+(?:\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-)?\s*[-]?\d+)?)\s*(s(?:\u207b|\u2212|\u2013|-)?1|s-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bkcat(?!\s*/\s*Km)\b[^.=]{0,15}?([\d.]+)\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-)\s*(\d+)\s*(s(?:\u207b|\u2212|\u2013|-)?1|s-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bkcat(?!\s*/\s*Km)\b[^.=]{0,15}?([\d.]+)\s*[eE][\-−\u2212]?(\d+)\s*(s(?:\u207b|\u2212|\u2013|-)?1|s-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bKcat(?!\s*/\s*Km)\b[^.=]{0,20}?(?:was|=|:|≈|~|\u2248)\s*([\d.]+(?:\s*[×x\u00d7]\s*10(?:\u207b|\u2212|\u2013|-)?\s*[-]?\d+)?)\s*(s(?:\u207b|\u2212|\u2013|-)?1|s-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
    re.compile(r'\bkcat\s*[\(（]\s*(\w[\w\d\-]*)\s*[\)）]\s*=\s*([\d.]+)\s*(s(?:\u207b|\u2212|\u2013|-)?1|s-1|min(?:\u207b|\u2212|\u2013|-)?1|min-1)', re.I),
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
]

def _normalize_ocr_scientific(text: str) -> str:
    if not text:
        return text
    t = text
    t = re.sub(r'\bK\s+m\b', 'Km', t, flags=re.I)
    t = re.sub(r'\bV\s+max\b', 'Vmax', t, flags=re.I)
    t = re.sub(r'\bk\s+cat\b', 'kcat', t, flags=re.I)
    t = t.replace('\ufffd', '\u25a1')
    t = re.sub(r'10\s*\u25a1\s*(\d)', lambda m: '10\u207b' + m.group(1), t)
    t = re.sub(r'([\d.]+)\s*\u25a1\s*10', lambda m: m.group(1) + ' \u00d710', t)
    t = re.sub(r'([a-zA-Z\u03bc])\s*\u25a1\s*(\d)', lambda m: m.group(1) + '\u207b' + m.group(2), t)
    t = re.sub(r'(\d)\s*\u25a1\s*(\d)', r'\1-\2', t)
    t = t.replace('\u00bc', '=')
    t = t.replace('\u0006', '\u00b1')
    t = re.sub(r'([\d.]+)\s*[\u02da\u00b0\u00ba\u25e6]\s*C\b', r'\1 °C', t, flags=re.I)
    t = re.sub(r'([\d.]+)\s*\u25a1\s*C\b', r'\1 °C', t, flags=re.I)
    t = re.sub(r'([\d.]+)\s*°\s+C\b', r'\1 °C', t, flags=re.I)
    t = re.sub(r'(\w)e(\d)', lambda m: m.group(1) + ' \u2248 ' + m.group(2), t)
    t = re.sub(r'\b([m\u03bcunp]?M)\s+(s)\s*[\u207b\u2212\u2013\-]?\s*1\b', lambda m: m.group(1) + '\u00b7' + m.group(2) + '\u207b\u00b9', t)
    t = re.sub(r'\b(s)\s+[\-–—]\s*1\b', lambda m: m.group(1) + '\u207b\u00b9', t, flags=re.I)
    t = re.sub(r'\b(m)\s+(M)\s*[\u207b\u2212\u2013\-]?\s*1\b', 'mM\u207b\u00b9', t)
    t = re.sub(r'\b(m)\s+(Ms)\s*[\u207b\u2212\u2013\-]?\s*1\b', 'mM\u00b7s\u207b\u00b9', t, flags=re.I)
    t = re.sub(r'\b(m)\s+(M)\b', 'mM', t)
    t = re.sub(r'([\d.]+)\s+10\s*[\u207b\u2212\u2013\-]\s*(\d+)', lambda m: m.group(1) + ' \u00d7 10\u207b' + m.group(2), t)
    t = re.sub(r'([\d.]+)\s*[x\u00d7]\s*10\s*[\^]?\s*[\u2212\u2013\-]\s*(\d+)', lambda m: m.group(1) + ' \u00d7 10\u207b' + m.group(2), t)
    t = re.sub(r'([\d.]+)\s*[x\u00d7]\s*10\s*[\^]?\s*(\d+)', lambda m: m.group(1) + ' \u00d7 10' + m.group(2), t)
    t = re.sub(r'([\d.]+)\s*[x\u00d7]\s*10\s*(\d+)', lambda m: m.group(1) + ' \u00d7 10' + m.group(2), t)
    t = re.sub(r'(\d+)\s+10\s+(\d+)\s+Ms?\s*[\-–—]?\s*1\b', lambda m: m.group(1) + ' \u00d7 10\u207b' + m.group(2) + ' M/s', t, flags=re.I)
    t = re.sub(r'(\d+)\s+10\s+(\d+)\s+[Mm]\s*[Ss]\s*[\-–—]?\s*1\b', lambda m: m.group(1) + ' \u00d7 10\u207b' + m.group(2) + ' M/s', t, flags=re.I)
    t = t.replace('\u25a1', '')
    return t


def _parse_scientific_notation(s):
    try:
        return float(s)
    except (ValueError, TypeError):
        pass
    s = s.strip()
    m = re.match(r'([\d.]+)\s*[×x\u00d7]\s*10\s*[\^]?\s*([⁻\u207b\-–\u2013−\u2212]?)(\d+)', s)
    if m:
        base = float(m.group(1))
        sign = m.group(2)
        exp = int(m.group(3))
        if sign in ('\u207b', '-', '\u2013', '\u2212', '⁻'):
            return base * (10 ** -exp)
        return base * (10 ** exp)
    m = re.match(r'([\d.]+)\s*[eE]\s*([\-−\u2212]?)(\d+)', s)
    if m:
        base = float(m.group(1))
        sign = m.group(2)
        exp = int(m.group(3))
        if sign in ('-', '\u2212', '\u2212'):
            return base * (10 ** -exp)
        return base * (10 ** exp)
    m = re.match(r'([\d.]+)\s+10\s*([⁻\u207b\-–\u2013−\u2212]?)(\d+)', s)
    if m:
        base = float(m.group(1))
        sign = m.group(2)
        exp = int(m.group(3))
        if sign in ('\u207b', '-', '\u2013', '\u2212', '⁻'):
            return base * (10 ** -exp)
        return base * (10 ** exp)
    m = re.match(r'([\d.]+)\s*[×x\u00d7]?\s*10\s*([⁻\u207b\-–\u2013−\u2212]?)(\d+)', s)
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


def _extract_vmax_fallback(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    norm = _normalize_ocr_scientific(text)
    for pat in _VMAX_OCR_PATTERNS:
        m = pat.search(norm)
        if m:
            groups = m.groups()
            if len(groups) == 2:
                base_str, exp_str = groups
                try:
                    base = float(base_str)
                    exp_val = _parse_scientific_notation(exp_str)
                    if isinstance(exp_val, (int, float)):
                        vmax_val = base * (10 ** -exp_val) if exp_val > 0 else base * (10 ** exp_val)
                    else:
                        exp_clean = re.sub(r'[^\d\-]', '', exp_str)
                        exp_int = int(exp_clean) if exp_clean else 0
                        vmax_val = base * (10 ** -exp_int)
                    unit_m = _VMAX_RATE_UNIT_RE.search(norm[m.end():m.end() + 30])
                    unit = unit_m.group(0).strip() if unit_m else None
                    return {"value": vmax_val, "unit": unit, "source": "text_ocr_fallback"}
                except (ValueError, TypeError):
                    continue
            elif len(groups) == 3:
                base_str, exp_str, unit = groups
                try:
                    base = float(base_str)
                    exp_clean = re.sub(r'[^\d\-]', '', exp_str)
                    exp_int = int(exp_clean) if exp_clean else 0
                    vmax_val = base * (10 ** -exp_int)
                    return {"value": vmax_val, "unit": unit, "source": "text_ocr_fallback"}
                except (ValueError, TypeError):
                    continue
    vm = re.search(r'\bV\s*max\b', norm, re.I)
    if not vm:
        vm = re.search(r'\bmaximum\s+velocity\b', norm, re.I)
    if vm:
        after = norm[vm.end():vm.end() + 150]
        e_notation_m = re.search(r'([\d.]+)\s*[eE]\s*([\-−\u2212]?\d+)', after)
        if e_notation_m:
            try:
                parsed = _parse_scientific_notation(e_notation_m.group(0))
                if isinstance(parsed, (int, float)):
                    unit_m = _VMAX_RATE_UNIT_RE.search(after[e_notation_m.end():e_notation_m.end() + 30])
                    unit = unit_m.group(0).strip() if unit_m else None
                    return {"value": parsed, "unit": unit, "source": "text_ocr_fallback"}
            except (ValueError, TypeError):
                pass
        num_m = re.search(r'([\d.]+)\s*[×x\u00d7]\s*10[\u207b\u207a\u2212\u2013\-–]?\s*(\d+)', after)
        if num_m:
            try:
                base = float(num_m.group(1))
                exp_str = num_m.group(2)
                full_match = num_m.group(0)
                has_minus = bool(re.search(r'10[\u207b⁻\-–\u2212\u2013]', full_match))
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
        plain_m = re.search(r'(?:was|=|:|≈|~|\u2248)\s*([\d.]+)\s*(?:\u00b1\s*[\d.]+\s*)?(mM\u207b\u00b9|mM\u00b7s\u207b\u00b9|mM/?s|M\u207b\u00b9s\u207b\u00b9|M\u00b7s\u207b\u00b9|M/?s|mM\s*s\u207b\u00b9|M\s*s\u207b\u00b9)', after, re.I)
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
        r'(?:LOD|limit\s+of\s+detection|detection\s+limit)\s*(?:of|=|:|≈|~|was|is)\s*([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm)',
        re.I,
    ),
    re.compile(
        r'(?:LOD|limit\s+of\s+detection|detection\s+limit)\s*[\(（]\s*([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm)\s*[\)）]',
        re.I,
    ),
    re.compile(
        r'(?:LOD|detection\s+limit)\s+(?:was\s+|is\s+)?(?:calculated\s+to\s+be\s+|found\s+to\s+be\s+)?([\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L|ppb|ppm)',
        re.I,
    ),
]
_LINEAR_RANGE_PATTERNS = [
    re.compile(
        r'(?:linear\s+range|linear\s+detection\s+range|calibration\s+range)\s*(?:of|=|:|≈|~|was|is)\s*([\d.]+\s*[-–—~to]+\s*[\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L)',
        re.I,
    ),
    re.compile(
        r'(?:linear\s+range|calibration\s+range)\s*[\(（]\s*([\d.]+\s*[-–—~to]+\s*[\d.]+)\s*(nM|μM|uM|mM|M|pg/mL|ng/mL|μg/mL|mg/L)\s*[\)）]',
        re.I,
    ),
]

_BUCKET_KEYWORDS = {
    "material": re.compile(
        r"(?:composition|morpholog|size|element|dopan|defect|stability|"
        r"synthes|prepar|fabricat|nanoparticle|nanosheet|nanotube|nanorod|"
        r"core-shell|yolk-shell|hollow|mesoporous|"
        r"crystal|amorphous|spinel|perovskite|anatase|rutile|"
        r"calcination|annealing|carbonization|pyrolysis)", re.I),
    "synthesis": re.compile(
        r"(?:synthes|prepar|fabricat|hydrothermal|calcination|annealing|"
        r"solvothermal|co-precipitation|sol-gel|precursor|"
        r"temperature|heated|furnace|reaction\s+time|"
        r"one-pot|two-step|in-situ|ex-situ)", re.I),
    "characterization": re.compile(
        r"(?:SEM|TEM|XRD|XPS|Raman|FTIR|EPR|AFM|EDX|EDS|SAED|"
        r"HAADF|HRTEM|XAFS|XANES|EXAFS|BET|TG|DTA|ICP|"
        r"zeta\s+potential|surface\s+area|pore\s+size|BJH|"
        r"lattice|d-spacing|crystallite)", re.I),
    "activity": re.compile(
        r"(?:peroxidase-like|oxidase-like|catalase-like|SOD-like|"
        r"enzyme-like|catalytic\s+activ|substrate|assay|TMB|ABTS|OPD|"
        r"DCFH|pH|buffer|reaction\s+time|temperature|"
        r"optimal\s+pH|optimal\s+temperature|pH\s+dependent|temperature\s+dependent|"
        r"pH\s+range|pH\s+stability|thermal\s+stability)", re.I),
    "kinetics": re.compile(
        r"(?:Km|K\s*m|Vmax|V\s*m|Michaelis|Lineweaver|"
        r"mM|M\s*s[−\-]1|×10|kinetic|kcat|specificity\s+constant)", re.I),
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
        r"river|lake|tap\s+water|sea\s+water)", re.I),
    "mechanism": re.compile(
        r"(?:ROS|O2[•\-\*]|•OH|1O2|electron\s+transfer|oxygen\s+vacancy|"
        r"active\s+site|radical|scaveng|mechanism|Fenton|Haber-Weiss|"
        r"superoxide|hydroxyl|singlet\s+oxygen)", re.I),
}

_SYNTHESIS_METHODS = {
    "hydrothermal": re.compile(r'\bhydrothermal\b', re.I),
    "solvothermal": re.compile(r'\bsolvothermal\b', re.I),
    "co-precipitation": re.compile(r'\bco-?precipitat', re.I),
    "sol-gel": re.compile(r'\bsol-?gel\b', re.I),
    "calcination": re.compile(r'\bcalcina', re.I),
    "annealing": re.compile(r'\banneal', re.I),
    "pyrolysis": re.compile(r'\bpyrolys', re.I),
    "chemical_vapor_deposition": re.compile(r'\bchemical\s+vapor\s+deposition\b|\bCVD\b', re.I),
    "electrospinning": re.compile(r'\belectrospinn', re.I),
    "microwave": re.compile(r'\bmicrowave', re.I),
    "ultrasonic": re.compile(r'\bultrasoni', re.I),
    "template_method": re.compile(r'\btemplate[-\s]?assist|\btemplate\s+method', re.I),
    "self-assembly": re.compile(r'\bself[-\s]?assembl', re.I),
    "wet_chemical": re.compile(r'\bwet\s+chemical', re.I),
    "solid_state": re.compile(r'\bsolid[-\s]?state\s+(?:reaction|method|synthesis)', re.I),
    "biomimetic_mineralization": re.compile(r'\bbiomimetic\s+mineraliz', re.I),
    "dealloying": re.compile(r'\bdealloy', re.I),
    "laser_ablation": re.compile(r'\blaser\s+ablat', re.I),
    "green_synthesis": re.compile(r'\bgreen\s+synthesis', re.I),
    "microemulsion": re.compile(r'\bmicroemuls', re.I),
    "reverse_microemulsion": re.compile(r'\breverse\s+microemuls', re.I),
    "polyol_method": re.compile(r'\bpolyol\s+method', re.I),
    "thermal_decomposition": re.compile(r'\bthermal\s+decompos', re.I),
    "carbonization": re.compile(r'\bcarbonizat', re.I),
    "dopamine_polymerization": re.compile(r'\bdopamine\s+polymeriz|\bpolydopamine', re.I),
    "impregnation": re.compile(r'\bimpregnat', re.I),
    "copolymerization": re.compile(r'\bcopolymeriz', re.I),
    "sacrificial_template": re.compile(r'\bsacrificial\s+template', re.I),
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
    ],
    "pH_range": [
        re.compile(r'\bpH\s+range\s*(?:of|=|:|≈|~|was|from)\s*([\d.]+)\s*[-–—~to]+\s*([\d.]+)', re.I),
        re.compile(r'\bactive\s+pH\s+range\s*([\d.]+)\s*[-–—~to]+\s*([\d.]+)', re.I),
        re.compile(r'\bpH\s*([\d.]+)\s*[-–—~to]+\s*([\d.]+)\s+(?:was|showed|exhibited)\s+(?:the\s+)?(?:highest|maximum|optimal)', re.I),
        re.compile(r'\bpH\s+range\s+of\s*([\d.]+)\s*[\u2013\-–—]\s*([\d.]+)', re.I),
        re.compile(r'\bpH\s+([\d.]+)\s*[\u2013\-–—]\s*([\d.]+)\s+(?:with|showed)', re.I),
    ],
    "pH_stability": [
        re.compile(r'\bpH\s+stability\s*(?:range|window)?\s*(?:of|=|:|≈|~|was)?\s*([\d.]+)\s*[-–—~to]+\s*([\d.]+)', re.I),
        re.compile(r'\bstable\s+(?:over|in|at)\s+pH\s*(?:range\s+)?([\d.]+)\s*[-–—~to]+\s*([\d.]+)', re.I),
        re.compile(r'\bretained\s+.*?activity\s+(?:over|in)\s+pH\s*([\d.]+)\s*[-–—~to]+\s*([\d.]+)', re.I),
        re.compile(r'\b(?:maintained|preserved)\s+.*?activity\s+(?:over|in|within)\s+pH\s*([\d.]+)\s*[-–—~to]+\s*([\d.]+)', re.I),
        re.compile(r'\bpH\s+stability\s+was\s+(?:studied|evaluated|examined)\s+(?:from|over|in)\s*([\d.]+)\s*[-–—~to]+\s*([\d.]+)', re.I),
    ],
}

_TEMPERATURE_PATTERNS = {
    "optimal_temperature": [
        re.compile(r'\boptimal\s+(?:reaction\s+)?temperature\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\boptimum\s+(?:reaction\s+)?temperature\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\btemperature\s+optimum\s*(?:was|=|:|≈|~)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\boptimal\s+temperature\s+of\s*([\d.]+)\s*°?C', re.I),
    ],
    "temperature_range": [
        re.compile(r'\btemperature\s+range\s*(?:of|=|:|≈|~|was|from)\s*([\d.]+)\s*[-–—~to]+\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\bactive\s+temperature\s+range\s*([\d.]+)\s*[-–—~to]+\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\btemperature\s+([\d.]+)\s*[-–—~to]+\s*([\d.]+)\s*°C\s+(?:with|showed)', re.I),
    ],
    "thermal_stability": [
        re.compile(r'\bthermal\s+stability\s*(?:up\s+to|until|≤|<=)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\bstable\s+(?:up\s+to|until|at)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\bretained\s+.*?activity\s+(?:up\s+to|until|at)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\bthermally\s+stable\s+(?:up\s+to|until|at)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\bTGA\s+(?:showed|revealed|indicated)\s+.*?decompos\w+\s+(?:at|above|around)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\b(?:maintained|preserved|retained)\s+.*?(?:activity|structure|stability)\s+(?:up\s+to|until|at)\s*([\d.]+)\s*°?C', re.I),
        re.compile(r'\bno\s+(?:significant\s+)?(?:loss|decrease|change)\s+in\s+activity\s+(?:up\s+to|until|below)\s*([\d.]+)\s*°?C', re.I),
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
    ],
    "time": [
        re.compile(r'\bfor\s+([\d.]+)\s*(h|hr|hrs|hour|hours|min|minutes?)\b', re.I),
        re.compile(r'\b(?:reaction|synthesis|annealing|calcination|pyrolysis|carbonization)\s+(?:time|duration)\s*(?:of|was|=|:)\s*([\d.]+)\s*(h|hr|hrs|hour|hours|min|minutes?)', re.I),
        re.compile(r'\b(?:maintained|kept|held)\s+(?:at|for)\s*[\d.]+\s*°?C\s+(?:for\s+)?([\d.]+)\s*(h|hr|hrs|hour|hours|min|minutes?)', re.I),
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
    "characterization_table": re.compile(r'\bXRD\b|\bXPS\b|\bBET\b|\bTEM\b|\bSEM\b', re.I),
}

_THIS_WORK_RE = re.compile(
    r'\bthis\s+work\b|\bcurrent\s+work\b|\bpresent\s+work\b|\bour\s+(?:nanozyme|catalyst|material|system)\b',
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
9. For kinetics, extract BOTH Km AND Vmax if both appear. Look carefully for Vmax — it often appears near Km.
10. size = numeric value only (e.g. 50), size_unit = unit only (e.g. "nm"). Do NOT combine them.

OUTPUT STRUCTURE:
{
  "selected_nanozyme": {
    "name": null, "selection_reason": null, "composition": null,
    "morphology": null, "size": null, "size_unit": null,
    "size_distribution": null, "metal_elements": [],
    "dopants_or_defects": [], "synthesis_method": null,
    "synthesis_conditions": {"temperature": null, "time": null, "precursors": [], "method_detail": null},
    "crystal_structure": null, "surface_area": null,
    "zeta_potential": null, "pore_size": null,
    "characterization": [], "stability": null
  },
  "main_activity": {
    "enzyme_like_type": null, "substrates": [], "assay_method": null, "signal": null,
    "conditions": {"buffer": null, "pH": null, "temperature": null, "reaction_time": null},
    "pH_profile": {"optimal_pH": null, "pH_range": null, "pH_stability_range": null},
    "temperature_profile": {"optimal_temperature": null, "temperature_range": null, "thermal_stability": null},
    "kinetics": {
      "Km": null, "Km_unit": null, "Vmax": null, "Vmax_unit": null,
      "kcat": null, "kcat_unit": null, "kcat_Km": null, "kcat_Km_unit": null,
      "substrate": null, "source": null, "needs_review": false
    },
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
- Synthesis: method name + conditions (temp/time/precursors). Common: hydrothermal, solvothermal, co-precipitation, sol-gel, calcination, pyrolysis, CVD, self-assembly, carbonization, stripping.
- pH_profile: optimal_pH = pH at maximum activity. pH_range = active range (e.g. "3-7"). pH_stability_range = range where nanozyme remains stable. Look for "optimal pH", "pH optimum", "maximum activity at pH X", "pH-dependent activity".
- Temperature_profile: optimal_temperature = temp at maximum activity. temperature_range = active range. thermal_stability = max temp before degradation. Look for "optimal temperature", "TGA", "stable up to X°C".
- Size: size = number only, size_unit = unit. size_distribution = range (e.g. "50-80 nm"). crystal_structure = phase (spinel/perovskite/amorphous/graphitic). surface_area = BET value. pore_size = diameter.
- Morphology: ONLY physical shape words (cubic, spherical, nanosheet, nanorod, core-shell, etc.). NOT figure captions or descriptions.
- Applications: Extract EACH distinct application separately. target_analyte ≠ substrate. If none, output [].
- Important values: capture key numbers not fitting elsewhere (e.g. specific activity, photothermal conversion efficiency, laser wavelength). If none, output []."""

_LLM_USER_TEMPLATE = """\
Selected main nanozyme material: {selected_material}
Selection reason: {selection_reason}

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
    for new_key in ("size_unit", "size_distribution", "crystal_structure",
                    "surface_area", "zeta_potential", "pore_size"):
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

    if auto_fixed and "schema_auto_fixed" not in warnings:
        warnings.append("schema_auto_fixed")
    diag["warnings"] = warnings
    record["diagnostics"] = diag

    try:
        from numeric_validator import normalize_unit
    except ImportError:
        normalize_unit = None

    if normalize_unit:
        kinetics = record.get("main_activity", {}).get("kinetics", {})
        for ukey in ("Km_unit", "Vmax_unit", "kcat_unit", "kcat_Km_unit"):
            raw_u = kinetics.get(ukey)
            if raw_u and isinstance(raw_u, str):
                normed = normalize_unit(raw_u)
                if normed != raw_u:
                    kinetics[ukey] = normed
        sel_nano = record.get("selected_nanozyme", {})
        for ukey in ("size_unit",):
            raw_u = sel_nano.get(ukey)
            if raw_u and isinstance(raw_u, str):
                normed = normalize_unit(raw_u)
                if normed != raw_u:
                    sel_nano[ukey] = normed

        for app in record.get("applications", []):
            if not isinstance(app, dict):
                continue
            for ukey in ("detection_limit_unit", "linear_range_unit"):
                raw_u = app.get(ukey)
                if raw_u and isinstance(raw_u, str):
                    normed = normalize_unit(raw_u)
                    if normed != raw_u:
                        app[ukey] = normed

        for ukey in ("Km_unit", "Vmax_unit", "kcat_unit", "kcat_Km_unit"):
            raw_u = kinetics.get(ukey)
            if raw_u and isinstance(raw_u, str):
                if re.match(r'^[×x\u00d7]\s*10\s*[\^]?\s*[\-−–]?\s*\d+$', raw_u):
                    val = kinetics.get(ukey.replace("_unit", ""))
                    if val is not None and isinstance(val, (int, float)):
                        exp_m = re.search(r'[\-−–]?(\d+)', raw_u)
                        if exp_m:
                            exp = int(exp_m.group(0).replace('−', '-').replace('–', '-'))
                            kinetics[ukey.replace("_unit", "")] = val * (10 ** exp)
                            kinetics[ukey] = None

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
            if 8 < len(line) < 300 and ("," in line or " and " in line.lower()) and re.search(r'[A-Z][a-z]+', line):
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
        (re.compile(r'0(?=[A-Z][a-z])'), 'O'),
        (re.compile(r'(?<=[A-Z])0(?=[a-z])'), 'O'),
    ]

    _OCR_COMPOUND_FIXES = [
        (re.compile(r'(\w)e([A-Z])C\b'), r'\1-\2-C'),
        (re.compile(r'(\w)e([A-Z])N\b'), r'\1-\2-N'),
        (re.compile(r'(\w)Ne([A-Z])\b'), r'\1-N-\2'),
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
        for m in re.finditer(r'\bMOF[-\s]?\d+\b|\bCOF[-\s]?\d+\b|\bZIF[-\s]?\d+\b', title, re.I):
            name = m.group(0).strip()
            if self._is_valid_candidate(name):
                results.append(name)
        for m in re.finditer(
            r'\b(?:Fe|Co|Ni|Mn|Cu|Zn|Ce|Au|Ag|Pt|Pd|Ti|V|Cr|Mo|W|Ru|Rh|Ir|La)'
            r'-(?:[A-Z][a-z]*-?)+\b',
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
            cleaned = re.sub(r'^[/\\]\s*\w+\s+', "", cleaned).strip()
            cleaned = re.sub(r'^\d+\s+', "", cleaned).strip()
            if cleaned == prev:
                break
        m = _MATERIAL_PATTERN_RE.search(cleaned)
        if m:
            core = m.group(0).strip()
            if self._is_valid_candidate(core):
                cleaned = core
        if len(cleaned) > 40:
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
        if lower.startswith("the ") or lower.startswith("a "):
            return False
        if re.match(r'^[A-Z][a-z]?\d*[+-]$', name):
            return False
        if re.match(r'^[A-Z][a-z]?\d+$', name) and not any(w in lower for w in _MORPHOLOGY_WORDS):
            elem = re.match(r'^([A-Z][a-z]?)\d+$', name)
            if elem and elem.group(1) in {"Fe", "Co", "Ni", "Mn", "Cu", "Zn", "Ce", "Au",
                                           "Ag", "Pt", "Pd", "Ti", "V", "Cr", "Mo", "W",
                                           "Ru", "Rh", "Ir", "La"}:
                return False
        if re.match(r'^[a-z]{1,3}-[a-z]{1,3}$', name, re.I):
            if not re.match(r'^(?:Fe|Co|Ni|Mn|Cu|Zn|Ce|Au|Ag|Pt|Pd|Ti|V|Cr|Mo|W|Ru|Rh|Ir|La)-', name, re.I):
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
                    if longer_has_composite and not shorter_has_composite:
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

            score += self._score_data_richness(cand, doc)
            score += self._score_narrative_importance(cand, title, abstract_text)

            cand["score"] = score

        scored = sorted(candidates, key=lambda x: x["score"], reverse=True)

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
    def __init__(self, max_sentences: int = 20, consistency_guard=None):
        self.max_sentences = max_sentences
        self.consistency_guard = consistency_guard
        self.warnings = []

    def build(self, doc: PreprocessedDocument, selected_name: str,
              all_candidates: Optional[List[str]] = None) -> Dict[str, List[str]]:
        if self.consistency_guard is None:
            from consistency_guard import ConsistencyGuard
            self.consistency_guard = ConsistencyGuard(selected_name, all_candidates, text_chunks=doc.chunks)

        buckets: Dict[str, List[str]] = {k: [] for k in _BUCKET_KEYWORDS}

        all_sentences: List[Tuple[str, str]] = []
        for idx, chunk in enumerate(doc.chunks):
            for line in chunk.split("\n"):
                line = line.strip()
                if line:
                    all_sentences.append((line, self._infer_section(doc.chunk_contexts, idx, chunk)))
        for vlm_task in doc.vlm_tasks:
            caption = vlm_task.get("caption", "")
            if caption:
                all_sentences.append((caption, "characterization_caption"))

        name_lower = selected_name.lower()
        variants = {name_lower}
        if "@" in name_lower:
            variants.update(p.strip() for p in name_lower.split("@") if p.strip())
        if "/" in name_lower:
            variants.update(p.strip() for p in name_lower.split("/") if p.strip())
        for prefix in ("nano", "the ", "a "):
            if name_lower.startswith(prefix):
                variants.add(name_lower[len(prefix):])

        for text, section in all_sentences:
            text_lower = text.lower()
            name_matched = any(v in text_lower for v in variants)
            for bucket_name, pattern in _BUCKET_KEYWORDS.items():
                if not pattern.search(text):
                    continue
                if name_matched:
                    buckets[bucket_name].append(text)
                elif bucket_name in ("kinetics", "application", "mechanism"):
                    attr = self.consistency_guard.check_sentence_attribution(text)
                    if attr["belongs_to_selected"]:
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
                name_matched = any(v in text_lower for v in variants)
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

    def _infer_section(self, contexts: List[Dict], idx: int, chunk: str) -> str:
        cl = chunk.lower()[:500]
        if any(kw in cl for kw in ["synthesis", "preparation"]):
            return "synthesis"
        if any(kw in cl for kw in ["characteriz", "sem ", "tem ", "xrd"]):
            return "characterization"
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

            classified = False
            for tbl_type, pattern in _TABLE_TYPE_PATTERNS.items():
                if pattern.search(full_text):
                    entry = {"table_type": tbl_type, "headers": tbl.get("headers", tbl.get("columns", [])),
                             "row_count": len(rows), "text": full_text[:500],
                             "rows": rows, "content_text": content_text, "markdown": markdown, "caption": caption}

                    if tbl_type == "comparison_table":
                        this_work_rows = self._filter_this_work(tbl, selected_name)
                        entry["this_work_rows"] = this_work_rows
                        entry["other_rows_count"] = len(rows) - len(this_work_rows)
                    elif tbl_type == "kinetics_table":
                        entry["this_work_rows"] = self._filter_this_work(tbl, selected_name)

                    result[f"{tbl_type}s"].append(entry)
                    classified = True
                    break
            if not classified:
                result["general_tables"].append({
                    "table_type": "general_table", "headers": tbl.get("headers", tbl.get("columns", [])),
                    "row_count": len(rows), "text": full_text[:500],
                    "rows": rows, "content_text": content_text, "markdown": markdown, "caption": caption,
                })

        return result

    def _filter_this_work(self, tbl: Dict, selected_name: str) -> List[Dict]:
        this_work_rows = []
        name_lower = selected_name.lower()
        for row in tbl.get("rows", []):
            row_text = " ".join(str(cell) for cell in row).lower()
            if _THIS_WORK_RE.search(row_text) or name_lower in row_text:
                this_work_rows.append({"cells": row, "source": "this_work"})
        return this_work_rows

    def get_kinetics_values(self, classified: Dict[str, Any], selected_name: str) -> List[Dict]:
        values = []
        name_lower = selected_name.lower() if selected_name else ""
        for tbl in classified.get("kinetics_tables", []):
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
                    _RATE_UNITS = ("M s⁻¹", "M s-1", "M s–1", "M s^-1", "M/s", "mM/s", "μM/s", "M S⁻¹", "M S-1", "mM·s⁻¹", "mM\u00b7s\u207b\u00b9")
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

    def get_sensing_values(self, classified: Dict[str, Any]) -> List[Dict]:
        values = []
        for tbl in classified.get("sensing_tables", []):
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
        return values


class FigureProcessor:
    def summarize(self, vlm_tasks: List[Dict], selected_name: str) -> Dict[str, Any]:
        summaries = []
        for vlm_task in vlm_tasks:
            caption = vlm_task.get("caption", "")
            fig_type = self._infer_figure_type(caption)
            mentions_selected = selected_name.lower() in caption.lower()
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


class RuleExtractor:
    def extract_from_evidence(self, record: Dict[str, Any], buckets: Dict[str, List[str]],
                              table_values: List[Dict], selected_name: str,
                              doc: PreprocessedDocument = None) -> Dict[str, Any]:
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

        if record["main_activity"]["kinetics"]["Km"] is None or record["main_activity"]["kinetics"]["Vmax"] is None:
            self._extract_kinetics_from_text(record, buckets.get("kinetics", []))

        if record["main_activity"]["kinetics"]["Km"] is None or record["main_activity"]["kinetics"]["Vmax"] is None:
            self._extract_kinetics_from_flattened_table(record, buckets.get("kinetics", []), selected_name)

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

        if doc:
            self._fulltext_fallback_extract(record, doc, selected_name)

        return record

    def _extract_kinetics_from_text(self, record: Dict[str, Any], kinetics_texts: List[str]):
        try:
            from numeric_validator import normalize_unit as _norm_unit
        except ImportError:
            _norm_unit = None
        for text in kinetics_texts:
            norm_text = _normalize_ocr_scientific(text)
            if record["main_activity"]["kinetics"]["Km"] is None or record["main_activity"]["kinetics"]["Vmax"] is None:
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
                        if isinstance(km_val, (int, float)) and record["main_activity"]["kinetics"]["Km"] is None:
                            record["main_activity"]["kinetics"]["Km"] = km_val
                            _nu = _norm_unit(km_unit) if _norm_unit and km_unit else km_unit
                            record["main_activity"]["kinetics"]["Km_unit"] = _nu if _nu else km_unit
                            record["main_activity"]["kinetics"]["source"] = "text"
                        if isinstance(vmax_val, (int, float)) and record["main_activity"]["kinetics"]["Vmax"] is None:
                            record["main_activity"]["kinetics"]["Vmax"] = vmax_val
                            _nu = _norm_unit(vmax_unit) if _norm_unit and vmax_unit else vmax_unit
                            record["main_activity"]["kinetics"]["Vmax_unit"] = _nu if _nu else vmax_unit
                            record["main_activity"]["kinetics"]["source"] = "text"
                        break

            if record["main_activity"]["kinetics"]["Km"] is None:
                for pat in _KM_PATTERNS:
                    m = pat.search(norm_text)
                    if not m:
                        m = pat.search(text)
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
                            _nu = _norm_unit(unit) if _norm_unit and unit else unit
                            record["main_activity"]["kinetics"]["Km_unit"] = _nu if _nu else unit
                            if substrate:
                                record["main_activity"]["kinetics"]["substrate"] = substrate
                            record["main_activity"]["kinetics"]["source"] = "text"
                        except ValueError:
                            pass
                        break

            if record["main_activity"]["kinetics"]["Vmax"] is None:
                for pat in _VMAX_PATTERNS:
                    m = pat.search(norm_text)
                    if not m:
                        m = pat.search(text)
                    if m:
                        groups = m.groups()
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
                            _nu = _norm_unit(unit) if _norm_unit else unit
                            record["main_activity"]["kinetics"]["Vmax_unit"] = _nu if _nu else unit
                        if substrate and not record["main_activity"]["kinetics"]["substrate"]:
                            record["main_activity"]["kinetics"]["substrate"] = substrate
                        record["main_activity"]["kinetics"]["source"] = "text"
                        break

            if record["main_activity"]["kinetics"]["Vmax"] is None:
                fallback = _extract_vmax_fallback(text)
                if fallback and isinstance(fallback.get("value"), (int, float)):
                    record["main_activity"]["kinetics"]["Vmax"] = fallback["value"]
                    if fallback.get("unit"):
                        _nu = _norm_unit(fallback["unit"]) if _norm_unit else fallback["unit"]
                        record["main_activity"]["kinetics"]["Vmax_unit"] = _nu if _nu else fallback["unit"]
                    record["main_activity"]["kinetics"]["source"] = fallback.get("source", "text_ocr_fallback")
                    logger.info(f"[SMN] Vmax OCR fallback: {fallback['value']} {fallback.get('unit', '')}")

    def _extract_kinetics_from_flattened_table(self, record: Dict[str, Any],
                                                kinetics_texts: List[str],
                                                selected_name: str):
        try:
            from numeric_validator import normalize_unit as _norm_unit
        except ImportError:
            _norm_unit = None
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

                is_match = (name_lower in line_compact or
                            selected_name.lower() in line_lower or
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
                        else:
                            norm_vmax = _normalize_ocr_scientific(raw_vmax)
                            vmax_parsed2 = _parse_scientific_notation(norm_vmax)
                            if isinstance(vmax_parsed2, (int, float)):
                                record["main_activity"]["kinetics"]["Vmax"] = vmax_parsed2
                                _nu = _norm_unit(vmax_unit_raw) if _norm_unit and vmax_unit_raw else vmax_unit_raw
                                record["main_activity"]["kinetics"]["Vmax_unit"] = _nu if _nu else vmax_unit_raw
                                record["main_activity"]["kinetics"]["source"] = "text"
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
        try:
            from numeric_validator import normalize_unit as _norm_unit
        except ImportError:
            _norm_unit = None
        km_header_m = re.search(r'Km\s*[\(（]\s*(mM|μM|uM|M|mmol|umol|nmol)\s*[\)）]', text, re.I)
        vmax_header_m = re.search(r'Vmax\s*[\(（\[]\s*([^\)）\]]+?)\s*[\)）\]]', text, re.I)
        if not km_header_m and not vmax_header_m:
            return False

        km_unit = km_header_m.group(1) if km_header_m else None
        vmax_unit = vmax_header_m.group(1).strip() if vmax_header_m else None

        header_end = max(km_header_m.end() if km_header_m else 0,
                         vmax_header_m.end() if vmax_header_m else 0)
        data_part = text[header_end:].strip()

        name_lower = selected_name.lower()
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
                    if substrate:
                        record["main_activity"]["kinetics"]["substrate"] = substrate
                    return True
                except ValueError:
                    pass
        return False

    def _extract_kinetics_from_table(self, record: Dict[str, Any], table_values: List[Dict]):
        try:
            from numeric_validator import normalize_unit as _norm_unit
        except ImportError:
            _norm_unit = None
        for val in table_values:
            param = val.get("parameter", "")
            if param == "Km" and record["main_activity"]["kinetics"]["Km"] is None:
                try:
                    record["main_activity"]["kinetics"]["Km"] = float(val["value"])
                    _nu = _norm_unit(val.get("unit")) if _norm_unit and val.get("unit") else val.get("unit")
                    record["main_activity"]["kinetics"]["Km_unit"] = _nu if _nu else val.get("unit")
                    record["main_activity"]["kinetics"]["substrate"] = val.get("substrate")
                    record["main_activity"]["kinetics"]["source"] = "table"
                except (ValueError, TypeError):
                    pass
            elif param == "Vmax" and record["main_activity"]["kinetics"]["Vmax"] is None:
                try:
                    record["main_activity"]["kinetics"]["Vmax"] = float(val["value"])
                except (ValueError, TypeError):
                    record["main_activity"]["kinetics"]["Vmax"] = val["value"]
                _nu = _norm_unit(val.get("unit")) if _norm_unit and val.get("unit") else val.get("unit")
                record["main_activity"]["kinetics"]["Vmax_unit"] = _nu if _nu else val.get("unit")
                record["main_activity"]["kinetics"]["source"] = "table"
            elif param in ("kcat", "Kcat", "k_cat") and record["main_activity"]["kinetics"]["kcat"] is None:
                try:
                    parsed = _parse_scientific_notation(str(val["value"]))
                    if isinstance(parsed, (int, float)):
                        record["main_activity"]["kinetics"]["kcat"] = parsed
                        _raw_u = val.get("unit", "s^-1")
                        _nu = _norm_unit(_raw_u) if _norm_unit and _raw_u else _raw_u
                        record["main_activity"]["kinetics"]["kcat_unit"] = _nu if _nu else _raw_u
                        record["main_activity"]["kinetics"]["source"] = "table"
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
                        record["main_activity"]["kinetics"]["source"] = "table"
                except (ValueError, TypeError):
                    pass

    def _extract_kcat_from_text(self, record: Dict[str, Any], kinetics_texts: List[str]):
        try:
            from numeric_validator import normalize_unit as _norm_unit
        except ImportError:
            _norm_unit = None
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

        if ph_profile.get("pH_stability_range") is None:
            for text in search_texts:
                for pat in _PH_PATTERNS["pH_stability"]:
                    m = pat.search(text)
                    if m:
                        ph_profile["pH_stability_range"] = f"{m.group(1)}-{m.group(2)}"
                        break
                if ph_profile.get("pH_stability_range") is not None:
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

        if temp_profile.get("thermal_stability") is None:
            for text in search_texts:
                for pat in _TEMPERATURE_PATTERNS["thermal_stability"]:
                    m = pat.search(text)
                    if m:
                        temp_profile["thermal_stability"] = f"stable up to {m.group(1)} °C"
                        break
                if temp_profile.get("thermal_stability") is not None:
                    break

    def _extract_synthesis_method(self, record: Dict[str, Any], synthesis_texts: List[str]):
        sel = record.get("selected_nanozyme", {})
        if not isinstance(sel, dict):
            return

        if sel.get("synthesis_method") is None:
            method_scores: Dict[str, int] = {}
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
                            for struct_name in ("spinel", "perovskite", "fluorite", "cubic",
                                               "tetragonal", "hexagonal", "orthorhombic",
                                               "monoclinic", "amorphous", "crystalline",
                                               "anatase", "rutile", "brookite"):
                                if struct_name in match_text:
                                    sel["crystal_structure"] = struct_name
                                    break
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

    def _extract_morphology_from_text(self, record, char_texts):
        sel = record.get("selected_nanozyme", {})
        if not isinstance(sel, dict):
            return
        if sel.get("morphology"):
            return
        found_terms = []
        for text in char_texts:
            tl = text.lower()
            for term in self._MORPHOLOGY_TERMS:
                if term in tl and term not in found_terms:
                    found_terms.append(term)
        if found_terms:
            sel["morphology"] = ", ".join(found_terms[:3])

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
            found_terms = []
            tl = all_text.lower()
            for term in self._MORPHOLOGY_TERMS:
                if term in tl and term not in found_terms:
                    found_terms.append(term)
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

    _APP_TYPE_KEYWORDS = {
        "detection": ["detection", "sensing", "sensor", "biosensor", "assay", "monitoring", "determin"],
        "therapeutic": ["therapeutic", "antitumor", "antibacterial", "wound heal", "cytoprotect",
                        "neuroprotect", "anti-inflammator", "antiinflammator", "disinfect", "steriliz"],
        "environmental": ["pollutant", "heavy metal", "pesticide", "organophosph", "endocrine",
                          "degrad", "environmental", "drinking water", "waste water", "river",
                          "lake", "tap water", "sea water"],
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
            record["applications"].append(app)


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


class DiagnosticsBuilder:
    def build(self, record: Dict[str, Any], doc: PreprocessedDocument,
              selected_name: Optional[str], ambiguous: bool,
              table_classified: Dict, figure_summ: Dict) -> Dict[str, Any]:
        has_name = bool(record["selected_nanozyme"].get("name"))
        has_activity = bool(record["main_activity"].get("enzyme_like_type"))
        has_kinetics = any(record["main_activity"]["kinetics"].get(k) is not None for k in ("Km", "Vmax"))
        has_app = any(app.get("application_type") is not None for app in record.get("applications", []))

        is_supp = (doc.document_kind == "supplementary" or
                   record["paper"].get("document_kind") == "supplementary")

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

        needs_review = status != "complete" or bool(record["diagnostics"].get("warnings"))

        warnings = list(dict.fromkeys(record["diagnostics"].get("warnings", [])))

        if ambiguous:
            warnings.append("selected_material_ambiguous")
        if is_supp:
            warnings.append("supplementary_only")
        if not record["raw_supporting_text"].get("material") and not record["raw_supporting_text"].get("activity"):
            warnings.append("sparse_evidence")

        return {
            "status": status,
            "confidence": confidence,
            "needs_review": needs_review,
            "warnings": warnings,
        }


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
        try:
            from extraction_agents import RuleExtractorAdapter
            self.rule_ext = RuleExtractorAdapter()
            logger.info("[SMN] Using RuleExtractorAdapter (4 specialized agents)")
        except ImportError:
            logger.warning("[SMN] extraction_agents not available, using original RuleExtractor")
        self.num_val = NumericValidator()
        self.diag_builder = DiagnosticsBuilder()
        self._guard: Optional[Any] = None
        self._agentic_guard: Optional[Any] = None
        try:
            from cross_validation_agent import CrossValidationAgent
            self.cross_validator = CrossValidationAgent()
            logger.info("[SMN] CrossValidationAgent loaded")
        except ImportError:
            self.cross_validator = None
            logger.warning("[SMN] CrossValidationAgent not available")
        try:
            from consistency_agent import ConsistencyAgent
            self.consistency_agent = ConsistencyAgent()
            logger.info("[SMN] ConsistencyAgent loaded")
        except ImportError:
            self.consistency_agent = None
            logger.warning("[SMN] ConsistencyAgent not available")

    async def _call_vlm(self, vlm_tasks: List[Dict], selected_name: str) -> Optional[List[Dict]]:
        if not self.client:
            return None
        try:
            from vlm_extractor import VLMExtractor
        except ImportError:
            logger.warning("[SMN] VLMExtractor not available, skipping VLM")
            return None

        name_lower = selected_name.lower()
        variants = {name_lower}
        if "@" in name_lower:
            variants.update(p.strip() for p in name_lower.split("@") if p.strip())
        if "/" in name_lower:
            variants.update(p.strip() for p in name_lower.split("/") if p.strip())

        filtered_tasks = []
        for task in vlm_tasks:
            caption = task.get("caption", "")
            description = task.get("description", "")
            body_context = task.get("body_context", "")
            combined = f"{caption} {description} {body_context}".lower()

            mentions_selected = any(v in combined for v in variants if len(v) >= 2)
            has_kinetics = any(kw in combined for kw in ("km", "vmax", "michaelis", "kinetic", "kcat"))
            has_morphology = any(kw in combined for kw in ("tem", "sem", "afm", "morpholog", "size", "particle", "xrd", "xps", "ftir"))
            has_sensing = any(kw in combined for kw in ("detection", "sensing", "lod", "linear range"))
            has_ph_temp = any(kw in combined for kw in ("ph", "temperature", "thermal", "stability", "optimal", "optimum"))
            has_activity = any(kw in combined for kw in ("activity", "catalytic", "peroxidase", "oxidase", "enzyme"))

            if mentions_selected or has_kinetics or has_morphology or has_sensing or has_ph_temp or has_activity:
                filtered_tasks.append(task)
            else:
                logger.debug(f"[SMN] VLM skip: caption not related to selected material: {caption[:60]}")

        if not filtered_tasks:
            logger.info(f"[SMN] No relevant VLM tasks after filtering (was {len(vlm_tasks)}, now 0)")
            return None

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
                        if record["main_activity"]["kinetics"]["Km"] is None:
                            try:
                                val = float(km_item["value"])
                                record["main_activity"]["kinetics"]["Km"] = val
                                record["main_activity"]["kinetics"]["Km_unit"] = km_item.get("unit")
                                record["main_activity"]["kinetics"]["source"] = "VLM"
                            except (ValueError, TypeError):
                                pass
                        elif isinstance(record["main_activity"]["kinetics"]["Km"], (int, float)):
                            try:
                                val = float(km_item["value"])
                                if abs(val - record["main_activity"]["kinetics"]["Km"]) / max(abs(record["main_activity"]["kinetics"]["Km"]), 1e-10) > 0.5:
                                    logger.warning(
                                        f"[SMN] VLM Km={val} differs from rule Km={record['main_activity']['kinetics']['Km']}. "
                                        f"Keeping rule-based value."
                                    )
                            except (ValueError, TypeError):
                                pass

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
                        if record["main_activity"]["kinetics"]["Vmax"] is None:
                            try:
                                val = float(vmax_item["value"])
                                record["main_activity"]["kinetics"]["Vmax"] = val
                                record["main_activity"]["kinetics"]["Vmax_unit"] = vmax_item.get("unit")
                                record["main_activity"]["kinetics"]["source"] = "VLM"
                            except (ValueError, TypeError):
                                pass
                        elif isinstance(record["main_activity"]["kinetics"]["Vmax"], (int, float)):
                            try:
                                val = float(vmax_item["value"])
                                if abs(val - record["main_activity"]["kinetics"]["Vmax"]) / max(abs(record["main_activity"]["kinetics"]["Vmax"]), 1e-10) > 0.5:
                                    logger.warning(
                                        f"[SMN] VLM Vmax={val} differs from rule Vmax={record['main_activity']['kinetics']['Vmax']}. "
                                        f"Keeping rule-based value."
                                    )
                            except (ValueError, TypeError):
                                pass

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
            if observations and not record["selected_nanozyme"].get("morphology"):
                obs_text = "; ".join(str(o) for o in observations if o)
                if obs_text:
                    record["selected_nanozyme"]["morphology"] = obs_text[:200]

        return record

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
        logger.info(f"[SMN] Candidates: {len(candidates)}")
        for c in candidates[:3]:
            logger.info(f"[SMN]   {c['name']} (sources={c.get('sources',set())})")

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
            try:
                from consistency_guard_agentic import AgenticConsistencyGuard
                self._agentic_guard = AgenticConsistencyGuard(
                    selected_name, all_candidate_names, text_chunks=doc.chunks,
                    client=self.client,
                )
                logger.info(f"[SMN] AgenticConsistencyGuard initialized for '{selected_name}'")
            except ImportError:
                logger.warning("[SMN] consistency_guard_agentic not available, using base guard only")
                self._agentic_guard = None

        record["selected_nanozyme"]["name"] = selected_name
        selection_reason = (
            f"score={selected.get('score',0)}, "
            f"sources={', '.join(sorted(selected.get('sources',set())))}"
        )
        if selected.get("ambiguity_resolved_by"):
            selection_reason += f", resolved_by={selected['ambiguity_resolved_by']}"
        record["selected_nanozyme"]["selection_reason"] = selection_reason

        buckets = self.bucket_builder.build(doc, selected_name, all_candidate_names)
        logger.info(f"[SMN] Buckets: " + ", ".join(f"{k}={len(v)}" for k, v in buckets.items()))

        record["raw_supporting_text"]["material"] = buckets.get("material", [])[:10]
        record["raw_supporting_text"]["activity"] = buckets.get("activity", [])[:10]
        record["raw_supporting_text"]["kinetics"] = buckets.get("kinetics", [])[:10]
        record["raw_supporting_text"]["application"] = buckets.get("application", [])[:10]

        tables = doc.table_task.get("tables", [])
        table_classified = self.table_proc.classify_and_summarize(tables, selected_name)
        table_kinetics_values = self.table_proc.get_kinetics_values(table_classified, selected_name)
        table_sensing_values = self.table_proc.get_sensing_values(table_classified)
        logger.info(f"[SMN] Tables: kinetics={len(table_classified.get('kinetics_tables',[]))}, "
                     f"comparison={len(table_classified.get('comparison_tables',[]))}, "
                     f"sensing={len(table_classified.get('sensing_tables',[]))}")

        figure_summ = self.figure_proc.summarize(doc.vlm_tasks, selected_name)
        logger.info(f"[SMN] Figures: total={figure_summ['total']}, "
                     f"kinetics={figure_summ['kinetics_figures']}, "
                     f"morphology={figure_summ['morphology_figures']}")

        self.rule_ext.extract_from_evidence(record, buckets, table_kinetics_values, selected_name, doc=doc)
        logger.info(f"[SMN] Rule extraction: enzyme_type={record['main_activity']['enzyme_like_type']}, "
                     f"Km={record['main_activity']['kinetics'].get('Km')}, "
                     f"apps={len(record.get('applications',[]))}")

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
                    selected_name, record["selected_nanozyme"]["selection_reason"],
                    buckets, table_classified, figure_summ,
                )
            else:
                llm_result = await self._call_llm(
                    selected_name, record["selected_nanozyme"]["selection_reason"],
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
            if vlm_results:
                if self.cross_validator:
                    record = self.cross_validator.merge_results(record, {}, vlm_results)
                    logger.info("[SMN] VLM merged via CrossValidationAgent")
                else:
                    record = self._merge_vlm(record, vlm_results)
                logger.info(f"[SMN] VLM extraction succeeded, {len(vlm_results)} figures processed")
            else:
                warnings.append("vlm_failed_or_no_results")
                logger.warning("[SMN] VLM failed or no results")
        else:
            if not self.config.enable_vlm:
                warnings.append("vlm_disabled")
            elif not self.client:
                warnings.append("vlm_unavailable")
            logger.info("[SMN] VLM not available, using figure captions only")

        record, val_warnings = self.num_val.validate(record, strict=self.config.numeric_validation_strict)
        warnings.extend(val_warnings)

        self._backfill_kinetics_from_important_values(record)

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

        if table_sensing_values and not record.get("applications"):
            for sv in table_sensing_values:
                app = {"application_type": "detection", "target_analyte": None, "method": None,
                       "linear_range": None, "detection_limit": None, "sample_type": None, "notes": None}
                if sv["parameter"] == "LOD":
                    app["detection_limit"] = f"{sv['value']} {sv['unit']}"
                elif sv["parameter"] == "linear_range":
                    app["linear_range"] = f"{sv['value']} {sv['unit']}"
                record["applications"].append(app)

        if not record.get("applications"):
            record["applications_note"] = "当前文献未包含相关内容"
        else:
            record["applications_note"] = None

        record["diagnostics"]["warnings"] = warnings
        diag = self.diag_builder.build(record, doc, selected_name, ambiguous, table_classified, figure_summ)
        record["diagnostics"] = diag

        if self.consistency_agent:
            record, consistency_warnings = self.consistency_agent.normalize_output(record)
            if consistency_warnings:
                warnings.extend(consistency_warnings)
                record["diagnostics"]["warnings"] = warnings
                logger.info(f"[SMN] ConsistencyAgent warnings: {consistency_warnings}")

        record = validate_schema(record)

        logger.info(f"[SMN] Final: status={record['diagnostics']['status']}, "
                     f"confidence={record['diagnostics']['confidence']}, "
                     f"warnings={record['diagnostics']['warnings']}")

        return record

    async def _call_llm(self, selected_name: str, selection_reason: str,
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
            selection_reason=selection_reason,
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
        selection_reason: str,
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
            selection_reason=selection_reason,
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
        except ImportError:
            logger.warning("[SMN] llm_refinement not available, falling back to _call_llm")
            return await self._call_llm(
                selected_name, selection_reason, buckets, table_classified, figure_summ,
            )
        except Exception as e:
            logger.error(f"[SMN] LLM refinement call failed: {e}")
            return None

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
    }

    _APP_TYPE_NORMALIZE = {
        "sensing": "detection",
        "colorimetric detection": "detection",
        "colorimetric sensing": "detection",
        "biosensing": "detection",
        "determination": "detection",
        "monitoring": "detection",
        "assay": "detection",
        "therapeutic": "therapeutic",
        "therapy": "therapeutic",
        "catalytic therapy": "therapeutic",
        "antitumor": "therapeutic",
        "antibacterial": "therapeutic",
        "tumor therapy": "therapeutic",
        "diagnostic": "diagnostic",
        "diagnosis": "diagnostic",
        "environmental": "environmental",
        "environmental monitoring": "environmental",
        "degradation": "environmental",
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
                    from numeric_validator import normalize_unit
                    record["main_activity"]["kinetics"]["Km_unit"] = normalize_unit(unit)
                if not kin.get("source"):
                    record["main_activity"]["kinetics"]["source"] = source or "important_values"
                backfilled.append(f"Km={val}")
            elif name in ("Vmax", "VLM_Vmax", "LLM_Vmax", "LLM_Vmax_alternative") and kin.get("Vmax") is None:
                record["main_activity"]["kinetics"]["Vmax"] = val
                if unit and not kin.get("Vmax_unit"):
                    from numeric_validator import normalize_unit
                    record["main_activity"]["kinetics"]["Vmax_unit"] = normalize_unit(unit)
                if not kin.get("source"):
                    record["main_activity"]["kinetics"]["source"] = source or "important_values"
                backfilled.append(f"Vmax={val}")
            elif name in ("kcat", "VLM_kcat", "LLM_kcat", "LLM_kcat_alternative") and kin.get("kcat") is None:
                record["main_activity"]["kinetics"]["kcat"] = val
                if unit and not kin.get("kcat_unit"):
                    from numeric_validator import normalize_unit
                    record["main_activity"]["kinetics"]["kcat_unit"] = normalize_unit(unit)
                backfilled.append(f"kcat={val}")
            elif name in ("kcat_Km", "VLM_kcat_Km", "LLM_kcat_Km", "LLM_kcat_Km_alternative") and kin.get("kcat_Km") is None:
                record["main_activity"]["kinetics"]["kcat_Km"] = val
                if unit and not kin.get("kcat_Km_unit"):
                    from numeric_validator import normalize_unit
                    record["main_activity"]["kinetics"]["kcat_Km_unit"] = normalize_unit(unit)
                backfilled.append(f"kcat_Km={val}")

        if backfilled:
            logger.info(f"[SMN] Backfilled kinetics from important_values: {', '.join(backfilled)}")

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

        if pH_prof.get("pH_stability_range") is None:
            for sentence in buckets.get("activity", []):
                for pat in self._PH_STABILITY_PATTERNS:
                    m = pat.search(sentence)
                    if m:
                        pH_prof["pH_stability_range"] = f"{m.group(1)}-{m.group(2)}"
                        break
                if pH_prof.get("pH_stability_range") is not None:
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

        if temp_prof.get("thermal_stability") is None:
            for sentence in buckets.get("activity", []):
                for pat in self._THERMAL_STABILITY_PATTERNS:
                    m = pat.search(sentence)
                    if m:
                        temp_prof["thermal_stability"] = f"stable up to {m.group(1)} °C"
                        break
                if temp_prof.get("thermal_stability") is not None:
                    break

        act["pH_profile"] = pH_prof
        act["temperature_profile"] = temp_prof

    def _merge_llm(self, record: Dict[str, Any], llm: Dict[str, Any]) -> Dict[str, Any]:
        if self._guard:
            llm_check = self._guard.check_llm_result_attribution(llm)
            if llm_check["issues"]:
                logger.warning(f"[SMN] LLM attribution issues: {llm_check['issues']}")
                llm = llm_check["filtered_result"]

        if "selected_nanozyme" in llm:
            llm_sel = llm["selected_nanozyme"]
            for key in record["selected_nanozyme"]:
                if key == "synthesis_conditions" and "synthesis_conditions" in llm_sel:
                    if isinstance(llm_sel["synthesis_conditions"], dict):
                        for sk in record["selected_nanozyme"]["synthesis_conditions"]:
                            if sk in llm_sel["synthesis_conditions"] and llm_sel["synthesis_conditions"][sk] is not None:
                                record["selected_nanozyme"]["synthesis_conditions"][sk] = llm_sel["synthesis_conditions"][sk]
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
                    record["selected_nanozyme"][key] = val

        if "main_activity" in llm:
            llm_act = llm["main_activity"]
            for key in list(record["main_activity"].keys()):
                if key == "conditions" and "conditions" in llm_act:
                    for ck in record["main_activity"]["conditions"]:
                        if ck in llm_act["conditions"] and llm_act["conditions"][ck] is not None:
                            record["main_activity"]["conditions"][ck] = llm_act["conditions"][ck]
                elif key == "pH_profile" and "pH_profile" in llm_act:
                    if isinstance(llm_act["pH_profile"], dict):
                        for pk in record["main_activity"]["pH_profile"]:
                            if pk in llm_act["pH_profile"] and llm_act["pH_profile"][pk] is not None:
                                record["main_activity"]["pH_profile"][pk] = llm_act["pH_profile"][pk]
                elif key == "temperature_profile" and "temperature_profile" in llm_act:
                    if isinstance(llm_act["temperature_profile"], dict):
                        for tk in record["main_activity"]["temperature_profile"]:
                            if tk in llm_act["temperature_profile"] and llm_act["temperature_profile"][tk] is not None:
                                record["main_activity"]["temperature_profile"][tk] = llm_act["temperature_profile"][tk]
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
                                        if ratio > 100:
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
                                                    record["main_activity"]["kinetics"][f"{kk}_unit"] = llm_kinetics[f"_llm_{kk}_unit"]
                                            elif not rule_in_range and llm_in_range:
                                                logger.info(
                                                    f"[SMN] LLM {kk}={val} differs by >100x from rule {kk}={rule_val}, "
                                                    f"but rule value is outside expected magnitude range. Using LLM value."
                                                )
                                                record["main_activity"]["kinetics"][kk] = val
                                                if f"_llm_{kk}_unit" in llm_kinetics and llm_kinetics[f"_llm_{kk}_unit"]:
                                                    record["main_activity"]["kinetics"][f"{kk}_unit"] = llm_kinetics[f"_llm_{kk}_unit"]
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
                                                    record["main_activity"]["kinetics"][f"{kk}_unit"] = llm_kinetics[f"_llm_{kk}_unit"]
                                            elif not rule_in_range and llm_in_range:
                                                logger.info(
                                                    f"[SMN] LLM {kk}={val} differs by >10x from rule {kk}={rule_val}, "
                                                    f"but rule value is outside expected magnitude range. Using LLM value."
                                                )
                                                record["main_activity"]["kinetics"][kk] = val
                                                if f"_llm_{kk}_unit" in llm_kinetics and llm_kinetics[f"_llm_{kk}_unit"]:
                                                    record["main_activity"]["kinetics"][f"{kk}_unit"] = llm_kinetics[f"_llm_{kk}_unit"]
                                            elif rule_unit_abnormal:
                                                logger.info(
                                                    f"[SMN] LLM {kk}={val} differs by >10x from rule {kk}={rule_val}, "
                                                    f"but rule value has abnormal/missing unit ('{rule_unit}'). Using LLM value."
                                                )
                                                record["main_activity"]["kinetics"][kk] = val
                                                if f"_llm_{kk}_unit" in llm_kinetics and llm_kinetics[f"_llm_{kk}_unit"]:
                                                    record["main_activity"]["kinetics"][f"{kk}_unit"] = llm_kinetics[f"_llm_{kk}_unit"]
                                            else:
                                                logger.warning(
                                                    f"[SMN] LLM {kk}={val} differs by >10x from rule {kk}={rule_val}. "
                                                    f"Keeping rule-based value. LLM value saved as alternative."
                                                )
                                                record["main_activity"]["kinetics"][f"_llm_{kk}_alternative"] = val
                                            continue
                                    else:
                                        record["main_activity"]["kinetics"][f"_{kk}_source"] = "llm_supplement"
                                record["main_activity"]["kinetics"][kk] = val
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
                                    record["main_activity"]["kinetics"][f"{kk}_unit"] = llm_kinetics[f"_llm_{kk}_unit"]
                            else:
                                record["main_activity"]["kinetics"][kk] = val
                elif key == "enzyme_like_type" and "enzyme_like_type" in llm_act and llm_act["enzyme_like_type"] is not None:
                    llm_type = self._normalize_enzyme_type(llm_act["enzyme_like_type"])
                    rule_type = record["main_activity"].get("enzyme_like_type")
                    if rule_type and rule_type != "unknown" and rule_type != llm_type:
                        if "+" in rule_type or "+" in llm_type:
                            record["main_activity"]["enzyme_like_type"] = llm_type
                        elif rule_type in llm_type or llm_type in rule_type:
                            if len(llm_type) >= len(rule_type):
                                record["main_activity"]["enzyme_like_type"] = llm_type
                            else:
                                pass
                        else:
                            logger.warning(
                                f"[SMN] LLM enzyme_type='{llm_type}' conflicts with rule='{rule_type}'. "
                                f"Keeping rule-based value."
                            )
                            record["main_activity"]["_llm_enzyme_type_rejected"] = llm_type
                    else:
                        record["main_activity"]["enzyme_like_type"] = llm_type
                elif key in llm_act and llm_act[key] is not None:
                    record["main_activity"][key] = llm_act[key]

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
                valid.append(a)
            if valid:
                record["applications"] = valid

        if "important_values" in llm and isinstance(llm["important_values"], list):
            valid = [v for v in llm["important_values"] if isinstance(v, dict) and v.get("value") is not None]
            if valid:
                record["important_values"] = valid

        return record
