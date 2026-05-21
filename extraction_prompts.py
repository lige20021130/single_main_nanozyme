import json
from typing import Dict, List, Any, Optional

from schema_constraints import (
    get_enzyme_type_enum_string,
    get_application_type_enum_string,
)
from domain_knowledge import get_domain_knowledge as _get_dk

_DK = _get_dk()

SYSTEM_PROMPT = """You are an expert nanozyme data extractor. Your task is to extract structured data from scientific literature about nanozymes (nanomaterials with enzyme-like catalytic activity).

CRITICAL DOMAIN KNOWLEDGE:
1. A nanozyme is a nanomaterial that mimics the catalytic activity of natural enzymes
2. Enzyme-like types include: {enzyme_types}
3. Application types include: {app_types}
4. Km (Michaelis constant) for nanozymes is typically 0.001-500 mM; values >1 M or >1000 mM are likely errors
5. Vmax is typically reported in μM/s or mM/s; M/s values <1.0 should be converted to μM/s (multiply by 1e6)
{substrate_knowledge}
8. When multiple substrates are tested, extract kinetics for EACH substrate separately into kinetics_list
9. Material names with @ or / (e.g., Fe3O4@C, Co-N-C) are composite/doped materials — these are MORE specific than simple oxide names
10. Morphology should be specific (e.g., "uniform hollow polyhedral", "core-shell spherical"), NOT generic (e.g., "nanoparticle")
11. When a paper compares multiple related materials (e.g., R-MnCo2O4 vs MnCo2O4), each material's kinetics MUST be in a separate kinetics_list entry with material_variant field
12. SERS (Surface-Enhanced Raman Scattering) is a detection method, not an enzyme type. Papers using SERS to monitor nanozyme reactions still have oxidase-like/peroxidase-like etc. as the enzyme type.

TABLE INTERPRETATION KNOWLEDGE:
1. When reading tables, the row labeled "this work", "our catalyst", "present work" contains data for the TARGET nanozyme
2. Rows labeled with other material names (e.g., "HRP", "natural enzyme", "Fe3O4 NPs") are REFERENCE data, not the target
3. Table headers like "Km (mM)" indicate the unit for that column — do NOT add the unit again
4. Scientific notation in tables: "4.41 × 10⁻⁵" or "4.41e-5" should be converted to decimal form (4.41e-5)

UNIT CONVERSION TABLE:
- M/s → μM/s: multiply by 1e6 (e.g., 4.41e-5 M/s = 44.1 μM/s)
- M/s → mM/s: multiply by 1e3
- mM/s → μM/s: multiply by 1e3
- M → mM: multiply by 1e3
- M → μM: multiply by 1e6
- min⁻¹ → s⁻¹: divide by 60

HARD RULES:
1. Extract ONLY information explicitly stated in the text — do NOT guess or fabricate
2. Use null for missing values (not 0, not empty string)
3. Include units exactly as reported in the paper
4. For multi-substrate kinetics, put the PRIMARY substrate in kinetics and ALL substrates in kinetics_list
5. Output valid JSON only — no Markdown fences, no comments, no explanations
6. If a value uses scientific notation (e.g., 4.41 × 10⁻⁵), convert to decimal (e.g., 4.41e-5)
7. target_analyte in applications = the molecule being DETECTED, NOT the substrate consumed or the probe used for signal
8. Probe molecules (crystal violet, methylene blue, R6G for SERS) are signal indicators, NOT target analytes
""".format(
    enzyme_types=get_enzyme_type_enum_string(),
    app_types=get_application_type_enum_string(),
    substrate_knowledge=_DK.generate_substrate_knowledge_prompt(),
)

KINETICS_EXTRACTION_PROMPT = """Extract kinetic parameters from the following text about a nanozyme named "{nanozyme_name}".

Focus on:
- Km (Michaelis constant) with unit — for EACH substrate if multiple are tested
- Vmax (maximum velocity) with unit — for EACH substrate
- kcat (turnover number) with unit — if reported
- kcat/Km (catalytic efficiency) with unit — if reported
- Substrate name for each kinetic parameter
- Material variant name — if the paper compares multiple related materials (e.g., R-MnCo2O4 vs MnCo2O4), specify which material each kinetics entry belongs to

IMPORTANT RULES:
1. If the paper tests multiple substrates (e.g., TMB AND H2O2), you MUST extract kinetics for EACH substrate into kinetics_list
2. If the paper compares multiple related material variants (e.g., pristine vs reduced, doped vs undoped), you MUST include "material_variant" for EACH kinetics entry to indicate which material it belongs to
3. If the paper uses different detection methods for the same material (e.g., SERS vs UV-vis), include "detection_method" for each entry
4. Do NOT merge kinetics data from different materials — each material variant gets its own entry in kinetics_list

HOW TO IDENTIFY MATERIAL VARIANTS:
- Look for prefixes like "R-" (reduced), "O-" (oxidized), "N-" (nitrogen-doped)
- Look for suffixes like "-400" (calcination temperature), "-Air" (annealing atmosphere)
- Look for explicit comparisons: "pristine X vs modified X", "X before/after treatment"
- Look for figure legends or table headers that distinguish materials (e.g., "Fig.3a: R-MnCo2O4", "Fig.3b: MnCo2O4")
- If a kinetic value is associated with a specific material name in the text, that name goes in material_variant

HOW TO IDENTIFY DETECTION METHODS:
- Look for phrases like "by SERS method", "by UV-vis spectroscopy", "determined by colorimetric assay"
- If the same material has different Km/Vmax values obtained by different methods, create SEPARATE entries with different detection_method values

Text:
{text}

Respond in JSON format:
{{
  "kinetics": {{
    "Km": <number or null>,
    "Km_unit": "<unit or null>",
    "Vmax": <number or null>,
    "Vmax_unit": "<unit or null>",
    "kcat": <number or null>,
    "kcat_unit": "<unit or null>",
    "kcat_Km": <number or null>,
    "kcat_Km_unit": "<unit or null>",
    "substrate": "<primary substrate name or null>",
    "detection_method": "<primary detection method or null>",
    "material_variant": "<primary material variant or null>"
  }},
  "kinetics_list": [
    {{
      "Km": <number or null>,
      "Km_unit": "<unit or null>",
      "Vmax": <number or null>,
      "Vmax_unit": "<unit or null>",
      "kcat": <number or null>,
      "kcat_unit": "<unit or null>",
      "kcat_Km": <number or null>,
      "kcat_Km_unit": "<unit or null>",
      "substrate": "<substrate name>",
      "material_variant": "<material name if multiple variants exist, otherwise null>",
      "detection_method": "<method name if multiple methods exist, otherwise null>"
    }}
  ]
}}"""

KINETICS_FEW_SHOT_EXAMPLES = [
    {
        "input": "The Michaelis-Menten constant (Km) of Fe3O4@C for TMB was 0.35 mM, and the maximum velocity (Vmax) was 4.41 × 10⁻⁵ M/s. For H2O2, Km was 0.89 mM and Vmax was 7.9 × 10⁻⁸ M/s.",
        "output": {
            "kinetics": {
                "Km": 0.35, "Km_unit": "mM",
                "Vmax": 44.1, "Vmax_unit": "μM/s",
                "kcat": None, "kcat_unit": None,
                "kcat_Km": None, "kcat_Km_unit": None,
                "substrate": "TMB"
            },
            "kinetics_list": [
                {"Km": 0.35, "Km_unit": "mM", "Vmax": 44.1, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "kcat_Km": None, "kcat_Km_unit": None, "substrate": "TMB", "material_variant": None, "detection_method": None},
                {"Km": 0.89, "Km_unit": "mM", "Vmax": 0.079, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "kcat_Km": None, "kcat_Km_unit": None, "substrate": "H2O2", "material_variant": None, "detection_method": None}
            ]
        }
    },
    {
        "input": "The apparent Km value was determined to be 18.1 mM and Vmax was 8.32 × 10⁻² μM/s for the oxidation of TMB catalyzed by Co-N3PS.",
        "output": {
            "kinetics": {
                "Km": 18.1, "Km_unit": "mM",
                "Vmax": 0.0832, "Vmax_unit": "μM/s",
                "kcat": None, "kcat_unit": None,
                "kcat_Km": None, "kcat_Km_unit": None,
                "substrate": "TMB"
            },
            "kinetics_list": [
                {"Km": 18.1, "Km_unit": "mM", "Vmax": 0.0832, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "kcat_Km": None, "kcat_Km_unit": None, "substrate": "TMB", "material_variant": None, "detection_method": None}
            ]
        }
    },
    {
        "input": "The kcat/Km of Au@Pd nanozyme for TMB substrate was 2.5 × 10⁵ M⁻¹s⁻¹, with kcat = 85200 s⁻¹ and Km = 0.3496 mM.",
        "output": {
            "kinetics": {
                "Km": 0.3496, "Km_unit": "mM",
                "Vmax": None, "Vmax_unit": None,
                "kcat": 85200.0, "kcat_unit": "s⁻¹",
                "kcat_Km": 250000.0, "kcat_Km_unit": "M⁻¹s⁻¹",
                "substrate": "TMB"
            },
            "kinetics_list": [
                {"Km": 0.3496, "Km_unit": "mM", "Vmax": None, "Vmax_unit": None, "kcat": 85200.0, "kcat_unit": "s⁻¹", "kcat_Km": 250000.0, "kcat_Km_unit": "M⁻¹s⁻¹", "substrate": "TMB", "material_variant": None, "detection_method": None}
            ]
        }
    },
    {
        "input": "The kinetic parameters of R-MnCo2O4 and MnCo2O4 nanotubes were determined. For R-MnCo2O4, the Km was 0.018 mM and Vmax was 1.2 × 10⁻⁷ M/s by SERS method, while by UV-vis method the Km was 0.14 mM and Vmax was 1.4 × 10⁻⁷ M/s. For MnCo2O4, the Km was 0.05 mM and Vmax was 1.7 × 10⁻⁷ M/s by SERS method, and by UV-vis method the Km was 0.33 mM and Vmax was 3.3 × 10⁻⁷ M/s.",
        "output": {
            "kinetics": {
                "Km": 0.018, "Km_unit": "mM",
                "Vmax": 0.12, "Vmax_unit": "μM/s",
                "kcat": None, "kcat_unit": None,
                "kcat_Km": None, "kcat_Km_unit": None,
                "substrate": "TMB"
            },
            "kinetics_list": [
                {"Km": 0.018, "Km_unit": "mM", "Vmax": 0.12, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "kcat_Km": None, "kcat_Km_unit": None, "substrate": "TMB", "material_variant": "R-MnCo2O4", "detection_method": "SERS"},
                {"Km": 0.14, "Km_unit": "mM", "Vmax": 0.14, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "kcat_Km": None, "kcat_Km_unit": None, "substrate": "TMB", "material_variant": "R-MnCo2O4", "detection_method": "UV-vis"},
                {"Km": 0.05, "Km_unit": "mM", "Vmax": 0.17, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "kcat_Km": None, "kcat_Km_unit": None, "substrate": "TMB", "material_variant": "MnCo2O4", "detection_method": "SERS"},
                {"Km": 0.33, "Km_unit": "mM", "Vmax": 0.33, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "kcat_Km": None, "kcat_Km_unit": None, "substrate": "TMB", "material_variant": "MnCo2O4", "detection_method": "UV-vis"}
            ]
        }
    },
    {
        "input": "The steady-state kinetic assay revealed that the kcat of CeO2 NPs for TMB was 3.45 × 10⁵ s⁻¹, and the Km was 0.089 mM. The catalytic efficiency (kcat/Km) was calculated to be 3.88 × 10⁶ M⁻¹s⁻¹.",
        "output": {
            "kinetics": {
                "Km": 0.089, "Km_unit": "mM",
                "Vmax": None, "Vmax_unit": None,
                "kcat": 345000.0, "kcat_unit": "s⁻¹",
                "kcat_Km": 3880000.0, "kcat_Km_unit": "M⁻¹s⁻¹",
                "substrate": "TMB"
            },
            "kinetics_list": [
                {"Km": 0.089, "Km_unit": "mM", "Vmax": None, "Vmax_unit": None, "kcat": 345000.0, "kcat_unit": "s⁻¹", "kcat_Km": 3880000.0, "kcat_Km_unit": "M⁻¹s⁻¹", "substrate": "TMB", "material_variant": None, "detection_method": None}
            ]
        }
    },
    {
        "input": "The optimal pH for the peroxidase-like activity of Au@Pt NPs was 4.0, and the optimal temperature was 40 °C. Under these conditions, the Km for TMB was 0.22 mM and Vmax was 2.15 × 10⁻⁷ M/s.",
        "output": {
            "kinetics": {
                "Km": 0.22, "Km_unit": "mM",
                "Vmax": 0.215, "Vmax_unit": "μM/s",
                "kcat": None, "kcat_unit": None,
                "kcat_Km": None, "kcat_Km_unit": None,
                "substrate": "TMB"
            },
            "kinetics_list": [
                {"Km": 0.22, "Km_unit": "mM", "Vmax": 0.215, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "kcat_Km": None, "kcat_Km_unit": None, "substrate": "TMB", "material_variant": None, "detection_method": None}
            ]
        }
    },
    {
        "input": "The turnover number (kcat) of Fe-N-C SAzyme for H2O2 substrate was 1.2 × 10³ min⁻¹, and the Km value was 0.56 mM. For TMB substrate, kcat was 8.5 × 10² min⁻¹ and Km was 0.34 mM.",
        "output": {
            "kinetics": {
                "Km": 0.56, "Km_unit": "mM",
                "Vmax": None, "Vmax_unit": None,
                "kcat": 1200.0, "kcat_unit": "min⁻¹",
                "kcat_Km": None, "kcat_Km_unit": None,
                "substrate": "H2O2"
            },
            "kinetics_list": [
                {"Km": 0.56, "Km_unit": "mM", "Vmax": None, "Vmax_unit": None, "kcat": 1200.0, "kcat_unit": "min⁻¹", "kcat_Km": None, "kcat_Km_unit": None, "substrate": "H2O2", "material_variant": None, "detection_method": None},
                {"Km": 0.34, "Km_unit": "mM", "Vmax": None, "Vmax_unit": None, "kcat": 850.0, "kcat_unit": "min⁻¹", "kcat_Km": None, "kcat_Km_unit": None, "substrate": "TMB", "material_variant": None, "detection_method": None}
            ]
        }
    },
    {
        "input": "Kinetic analysis using Lineweaver-Burk plots gave Km = 1.79 mM and Vmax = 3.72e-8 M/s for Pd nanozyme with TMB as substrate.",
        "output": {
            "kinetics": {
                "Km": 1.79, "Km_unit": "mM",
                "Vmax": 0.0372, "Vmax_unit": "μM/s",
                "kcat": None, "kcat_unit": None,
                "kcat_Km": None, "kcat_Km_unit": None,
                "substrate": "TMB"
            },
            "kinetics_list": [
                {"Km": 1.79, "Km_unit": "mM", "Vmax": 0.0372, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "kcat_Km": None, "kcat_Km_unit": None, "substrate": "TMB", "material_variant": None, "detection_method": None}
            ]
        }
    },
    {
        "input": "Table 1. Kinetic parameters of different nanozymes. Entry: Cu-HCF SSNEs, Km (mM): 105.0, Vmax (M/s): 8.32e-8, Substrate: TMB. Entry: HRP (natural enzyme), Km (mM): 0.434, Vmax (M/s): 2.47e-7, Substrate: TMB.",
        "output": {
            "kinetics": {
                "Km": 105.0, "Km_unit": "mM",
                "Vmax": 0.0832, "Vmax_unit": "μM/s",
                "kcat": None, "kcat_unit": None,
                "kcat_Km": None, "kcat_Km_unit": None,
                "substrate": "TMB"
            },
            "kinetics_list": [
                {"Km": 105.0, "Km_unit": "mM", "Vmax": 0.0832, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "kcat_Km": None, "kcat_Km_unit": None, "substrate": "TMB", "material_variant": "Cu-HCF SSNEs", "detection_method": None}
            ]
        }
    },
    {
        "input": "The Michaelis constant of Mo-SAN for TMB was determined to be 0.42 mM with a Vmax of 5.6 × 10⁻⁸ M·s⁻¹, while for H2O2 the Km was 1.24 mM and Vmax was 3.8 × 10⁻⁸ M·s⁻¹. The catalytic efficiency kcat/Km for TMB was 1.5 × 10⁵ M⁻¹s⁻¹.",
        "output": {
            "kinetics": {
                "Km": 0.42, "Km_unit": "mM",
                "Vmax": 0.056, "Vmax_unit": "μM/s",
                "kcat": None, "kcat_unit": None,
                "kcat_Km": 150000.0, "kcat_Km_unit": "M⁻¹s⁻¹",
                "substrate": "TMB"
            },
            "kinetics_list": [
                {"Km": 0.42, "Km_unit": "mM", "Vmax": 0.056, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "kcat_Km": 150000.0, "kcat_Km_unit": "M⁻¹s⁻¹", "substrate": "TMB", "material_variant": None, "detection_method": None},
                {"Km": 1.24, "Km_unit": "mM", "Vmax": 0.038, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "kcat_Km": None, "kcat_Km_unit": None, "substrate": "H2O2", "material_variant": None, "detection_method": None}
            ]
        }
    },
]

MORPHOLOGY_EXTRACTION_PROMPT = """Extract morphology and physical properties of the nanozyme "{nanozyme_name}" from the following text.

Focus on:
- Morphology: specific shape description (e.g., "uniform hollow polyhedral", "core-shell spherical", NOT just "nanoparticle")
- Size with unit (nm, μm, etc.)
- Crystal structure (e.g., "cubic spinel", "amorphous")
- Surface area with unit (e.g., "120.5 m²/g")
- Synthesis method (e.g., "hydrothermal", "co-precipitation", "solvothermal")
- Synthesis conditions: temperature, time, precursors
- Characterization techniques used (e.g., "XRD", "TEM", "XPS")

Text:
{text}

Respond in JSON format:
{{
  "morphology": "<specific shape or null>",
  "size": <number or null>,
  "size_unit": "<unit or null>",
  "crystal_structure": "<structure or null>",
  "surface_area": "<value with unit or null>",
  "synthesis_method": "<method or null>",
  "synthesis_conditions": {{
    "temperature": <number or null>,
    "time": "<time string or null>",
    "precursors": ["<precursor1>", "<precursor2>"]
  }},
  "characterization": ["<technique1>", "<technique2>"]
}}"""

MORPHOLOGY_FEW_SHOT_EXAMPLES = [
    {
        "input": "The Fe3O4@C nanoparticles exhibited a core-shell structure with an average diameter of 200 nm. TEM images revealed uniform spherical morphology. The BET surface area was 120.5 m²/g. The nanoparticles were synthesized via a hydrothermal method at 180°C for 12 h using FeCl3·6H2O as precursor. XRD, TEM, XPS and FTIR were used for characterization.",
        "output": {
            "morphology": "core-shell spherical",
            "size": 200.0,
            "size_unit": "nm",
            "crystal_structure": None,
            "surface_area": "120.5 m²/g",
            "synthesis_method": "hydrothermal",
            "synthesis_conditions": {
                "temperature": 180,
                "time": "12 h",
                "precursors": ["FeCl3·6H2O"]
            },
            "characterization": ["XRD", "TEM", "XPS", "FTIR"]
        }
    },
    {
        "input": "The Mo-SAN (single-atom nanozyme) with isolated Mo-N4 sites was synthesized by pyrolysis of Mo-PhIM at 900°C for 2 h under Ar atmosphere. TEM and HAADF-STEM confirmed the atomic dispersion of Mo. XPS and XAFS were used to analyze the electronic structure.",
        "output": {
            "morphology": "single-atom dispersed",
            "size": None,
            "size_unit": None,
            "crystal_structure": None,
            "surface_area": None,
            "synthesis_method": "pyrolysis",
            "synthesis_conditions": {
                "temperature": 900,
                "time": "2 h",
                "precursors": ["Mo-PhIM"]
            },
            "characterization": ["TEM", "HAADF-STEM", "XPS", "XAFS"]
        }
    },
    {
        "input": "ZIF-8 nanocrystals with rhombic dodecahedral morphology were prepared by mixing Zn(NO3)2 and 2-methylimidazole at room temperature for 24 h. The average particle size was 150 nm. BET surface area was 1250 m²/g. XRD confirmed the sodalite structure.",
        "output": {
            "morphology": "rhombic dodecahedral",
            "size": 150.0,
            "size_unit": "nm",
            "crystal_structure": "sodalite",
            "surface_area": "1250 m²/g",
            "synthesis_method": "room-temperature coprecipitation",
            "synthesis_conditions": {
                "temperature": 25,
                "time": "24 h",
                "precursors": ["Zn(NO3)2", "2-methylimidazole"]
            },
            "characterization": ["XRD", "BET"]
        }
    },
    {
        "input": "Fe3O4@C core-shell nanoparticles were synthesized via a solvothermal method using FeCl3·6H2O and sodium citrate at 200°C for 10 h. The particles showed uniform spherical morphology with a core diameter of 150 nm and a shell thickness of 25 nm. XRD patterns indicated an inverse spinel structure.",
        "output": {
            "morphology": "core-shell spherical",
            "size": 200.0,
            "size_unit": "nm",
            "crystal_structure": "inverse spinel",
            "surface_area": None,
            "synthesis_method": "solvothermal",
            "synthesis_conditions": {
                "temperature": 200,
                "time": "10 h",
                "precursors": ["FeCl3·6H2O", "sodium citrate"]
            },
            "characterization": ["XRD"]
        }
    },
    {
        "input": "Co-Fe LDH nanosheets were prepared by co-precipitation of Co(NO3)2 and Fe(NO3)3 with NaOH at 60°C for 30 min followed by hydrothermal aging at 120°C for 6 h. The nanosheets had a lateral size of 200-500 nm and thickness of 10-20 nm. XRD showed a layered double hydroxide structure with (003) and (006) reflections.",
        "output": {
            "morphology": "nanosheet",
            "size": 350.0,
            "size_unit": "nm",
            "crystal_structure": "layered double hydroxide",
            "surface_area": None,
            "synthesis_method": "co-precipitation with hydrothermal aging",
            "synthesis_conditions": {
                "temperature": 120,
                "time": "6 h",
                "precursors": ["Co(NO3)2", "Fe(NO3)3", "NaOH"]
            },
            "characterization": ["XRD"]
        }
    },
]

APPLICATION_EXTRACTION_PROMPT = """Extract application information of the nanozyme "{nanozyme_name}" from the following text.

Focus on:
- Application type: {app_types}
- Target analyte: what is being detected/quantified (e.g., glucose, Hg2+, dopamine, ascorbic acid)
- Detection limit (LOD) with unit (e.g., 0.15 μM)
- Detection method (e.g., colorimetric, fluorescent, electrochemical, SERS)
- Sample type (e.g., serum, water, cell, tissue)

CRITICAL SEMANTIC DISTINCTIONS — you MUST understand these roles:
1. **substrate** (in kinetics) = molecule consumed in the catalytic reaction (e.g., TMB, ABTS, OPD, H2O2, DCFH-DA)
2. **probe molecule** = molecule used to visualize/verify the catalytic activity or SERS sensitivity (e.g., crystal violet/CV for SERS, methylene blue, Rhodamine B, R6G). These are NOT target analytes! They are signal indicators.
3. **target_analyte** (in applications) = the molecule being detected/quantified through the nanozyme's catalytic reaction (e.g., glucose, dopamine, ascorbic acid, Hg2+, cancer cells)

DECISION FRAMEWORK for target_analyte:
Ask yourself: "Is this molecule the REASON for building the sensing platform, or is it just a TOOL used to demonstrate the platform works?"
- If it's the REASON (what we want to detect/measure) → it IS the target_analyte
- If it's a TOOL (used to generate signal, verify activity, or calibrate) → it is NOT the target_analyte

Common patterns:
- "detect ascorbic acid using oxidase-like reaction" → target_analyte = ascorbic acid (the detection target)
- "crystal violet (CV+) used as SERS probe" → target_analyte = null (CV+ is just a probe)
- "TMB oxidation monitored by UV-vis" → target_analyte = null (TMB is a substrate)
- "sensing platform for glucose detection" → target_analyte = glucose
- "inhibition-based detection of AA" → target_analyte = ascorbic acid (AA inhibits the reaction, enabling its detection)

KEY RULES:
- Do NOT confuse probe molecules with target analytes. Crystal violet, methylene blue, R6G are SERS probes, NOT analytes.
- The target_analyte is what the sensing platform is designed to DETECT, not what it uses as a signal indicator.
- If the paper says "detect X using Y reaction monitored by Z technique", then X is the target_analyte, Y is the substrate, Z is the detection method.
- "catalytic reactions" is NOT a valid target_analyte — it must be a specific molecule or species.
- If the paper only demonstrates catalytic activity without a specific sensing target, set target_analyte to null.
- Inhibition-based sensing: if a molecule INHIBITS the catalytic reaction and this inhibition is used to detect that molecule, then that molecule IS the target_analyte (e.g., ascorbic acid inhibiting oxidase-like activity → AA is the analyte).

Text:
{text}

Respond in JSON format:
{{
  "applications": [
    {{
      "application_type": "<type or null>",
      "target_analyte": "<analyte or null>",
      "detection_limit": <number or null>,
      "detection_limit_unit": "<unit or null>",
      "method": "<method or null>",
      "sample_type": "<sample or null>"
    }}
  ]
}}"""

APPLICATION_FEW_SHOT_EXAMPLES = [
    {
        "input": "The colorimetric detection of glucose was achieved using Fe3O4@C nanozyme with a detection limit of 0.15 μM in human serum samples. The method showed excellent selectivity against interfering substances.",
        "output": {
            "applications": [
                {
                    "application_type": "sensing",
                    "target_analyte": "glucose",
                    "detection_limit": 0.15,
                    "detection_limit_unit": "μM",
                    "method": "colorimetric",
                    "sample_type": "serum"
                }
            ]
        }
    },
    {
        "input": "The Au@Pd nanozyme was applied for antibacterial therapy against E. coli and S. aureus, achieving 99.9% killing efficiency at 100 μg/mL.",
        "output": {
            "applications": [
                {
                    "application_type": "antibacterial",
                    "target_analyte": "E. coli and S. aureus",
                    "detection_limit": None,
                    "detection_limit_unit": None,
                    "method": None,
                    "sample_type": None
                }
            ]
        }
    },
    {
        "input": "In this study, crystal violet cation (CV+) is used as a probe to evaluate the SERS sensitivity of the MnCo2O4 and R-MnCo2O4 nanotubes. Then 5 μL of R-MnCo2O4 nanotubes suspension was mixed with 45 μL of CV+ solution with different concentrations from 10 to 1000 μM for 2 h to study the detection sensitivity. We have developed a simple and highly efficient SERS sensing platform based on the oxidase-like reaction to detect ascorbic acid (AA).",
        "output": {
            "applications": [
                {
                    "application_type": "sensing",
                    "target_analyte": "ascorbic acid (AA)",
                    "detection_limit": None,
                    "detection_limit_unit": None,
                    "method": "SERS",
                    "sample_type": None
                }
            ]
        }
    },
    {
        "input": "The CeO2 nanozyme exhibited excellent peroxidase-like activity toward TMB oxidation. The catalytic reaction was monitored by UV-vis spectroscopy. The nanozyme was further applied for the detection of H2O2 with a linear range of 0.5-50 μM and LOD of 0.12 μM.",
        "output": {
            "applications": [
                {
                    "application_type": "sensing",
                    "target_analyte": "H2O2",
                    "detection_limit": 0.12,
                    "detection_limit_unit": "μM",
                    "method": "colorimetric",
                    "sample_type": None
                }
            ]
        }
    },
    {
        "input": "Methylene blue (MB) was used as a SERS probe molecule to verify the enhancement factor of the Au@Ag nanozyme substrate. The SERS substrate showed an enhancement factor of 1.5 × 10^5.",
        "output": {
            "applications": []
        }
    },
    {
        "input": "The Co3O4 nanozyme was applied for the detection of Hg2+ ions in lake water and tap water samples. The detection limit was 0.05 nM with a linear range of 0.1-100 nM. The method was based on the inhibition of peroxidase-like activity by Hg2+.",
        "output": {
            "applications": [
                {
                    "application_type": "sensing",
                    "target_analyte": "Hg2+",
                    "detection_limit": 0.05,
                    "detection_limit_unit": "nM",
                    "method": "colorimetric",
                    "sample_type": "water"
                }
            ]
        }
    },
    {
        "input": "The CeO2 nanozyme exhibited excellent ROS scavenging ability and was applied for anti-inflammatory therapy in a mouse model of arthritis. The treatment significantly reduced inflammatory cytokines TNF-α and IL-6.",
        "output": {
            "applications": [
                {
                    "application_type": "antioxidant",
                    "target_analyte": "ROS",
                    "detection_limit": None,
                    "detection_limit_unit": None,
                    "method": None,
                    "sample_type": "mouse arthritis model"
                }
            ]
        }
    },
    {
        "input": "The Au@Pd nanozyme was used as a dual-functional platform: (1) colorimetric detection of glucose in human serum with LOD of 0.08 μM, and (2) antibacterial therapy against E. coli with 99.5% killing efficiency at 200 μg/mL under NIR irradiation.",
        "output": {
            "applications": [
                {
                    "application_type": "sensing",
                    "target_analyte": "glucose",
                    "detection_limit": 0.08,
                    "detection_limit_unit": "μM",
                    "method": "colorimetric",
                    "sample_type": "serum"
                },
                {
                    "application_type": "antibacterial",
                    "target_analyte": "E. coli",
                    "detection_limit": None,
                    "detection_limit_unit": None,
                    "method": "photothermal",
                    "sample_type": None
                }
            ]
        }
    },
]

ENZYME_TYPE_EXTRACTION_PROMPT = """Identify the PRIMARY enzyme-like activity type of the nanozyme "{nanozyme_name}" from the following text.

Allowed types: {enzyme_types}

IMPORTANT RULES:
1. If the text mentions MULTIPLE enzyme-like activities, identify the one that is:
   a. Most extensively studied (most kinetic data provided)
   b. Mentioned first in the abstract or results section
   c. The focus of the application section
2. If the paper describes a cascade reaction (e.g., GOx-like + peroxidase-like), use "cascade-enzymatic"
3. If truly multiple independent activities with equal emphasis, use "multi-enzyme-like"

Text:
{text}

Respond with a single JSON object:
{{"enzyme_like_type": "<type or null>"}}"""

SELF_AUGMENTATION_PROMPT = """You previously extracted the following data from a nanozyme paper:

{previous_extraction}

Now review your extraction against the original text and check for:
1. Any missed values (especially in tables, figure captions, or supplementary sections)
2. Unit conversion errors (M/s → μM/s requires multiplying by 1e6; mM/s → μM/s requires multiplying by 1e3)
3. Incorrect enzyme type assignment (check if the paper focuses on a different activity)
4. Missing multi-substrate kinetics data (if the paper tests TMB AND H2O2, both should be in kinetics_list)
5. Overly generic morphology (should be specific, e.g., "hollow polyhedral" not "nanoparticle")
6. Substrate vs target_analyte confusion (substrates are consumed in the reaction; analytes are detected)
7. **Application semantic role validation**: For each target_analyte in applications, ask: "Is this molecule the REASON for building the sensing platform, or just a TOOL?" Probe molecules (crystal violet, methylene blue, R6G used for SERS) and substrates (TMB, ABTS used as chromogenic agents) are NOT target analytes. The target_analyte must be what the platform DETECTS.
8. **Inhibition-based sensing**: If a molecule inhibits the catalytic reaction and this inhibition is used to detect that molecule, it IS the target_analyte (e.g., ascorbic acid inhibiting oxidase-like activity → AA is the analyte).
9. **Material variant attribution**: If kinetics_list contains data for multiple related materials (e.g., R-MnCo2O4 vs MnCo2O4), ensure each entry has the correct material_variant field.

Original text:
{text}

Provide a CORRECTED extraction in the same JSON format. Only change values you are confident are wrong or missing."""


def build_kinetics_prompt(nanozyme_name: str, text: str, include_examples: bool = True) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if include_examples:
        for ex in KINETICS_FEW_SHOT_EXAMPLES:
            messages.append({"role": "user", "content": KINETICS_EXTRACTION_PROMPT.format(
                nanozyme_name=nanozyme_name, text=ex["input"]
            )})
            messages.append({"role": "assistant", "content": json.dumps(ex["output"], ensure_ascii=False)})
    messages.append({"role": "user", "content": KINETICS_EXTRACTION_PROMPT.format(
        nanozyme_name=nanozyme_name, text=text
    )})
    return messages


def build_morphology_prompt(nanozyme_name: str, text: str, include_examples: bool = True) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if include_examples:
        for ex in MORPHOLOGY_FEW_SHOT_EXAMPLES:
            messages.append({"role": "user", "content": MORPHOLOGY_EXTRACTION_PROMPT.format(
                nanozyme_name=nanozyme_name, text=ex["input"]
            )})
            messages.append({"role": "assistant", "content": json.dumps(ex["output"], ensure_ascii=False)})
    messages.append({"role": "user", "content": MORPHOLOGY_EXTRACTION_PROMPT.format(
        nanozyme_name=nanozyme_name, text=text
    )})
    return messages


def build_application_prompt(nanozyme_name: str, text: str, include_examples: bool = True) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if include_examples:
        for ex in APPLICATION_FEW_SHOT_EXAMPLES:
            messages.append({"role": "user", "content": APPLICATION_EXTRACTION_PROMPT.format(
                nanozyme_name=nanozyme_name, text=ex["input"],
                app_types=get_application_type_enum_string()
            )})
            messages.append({"role": "assistant", "content": json.dumps(ex["output"], ensure_ascii=False)})
    messages.append({"role": "user", "content": APPLICATION_EXTRACTION_PROMPT.format(
        nanozyme_name=nanozyme_name, text=text,
        app_types=get_application_type_enum_string()
    )})
    return messages


def build_enzyme_type_prompt(nanozyme_name: str, text: str) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.append({"role": "user", "content": ENZYME_TYPE_EXTRACTION_PROMPT.format(
        nanozyme_name=nanozyme_name, text=text,
        enzyme_types=get_enzyme_type_enum_string()
    )})
    return messages


def build_self_augmentation_prompt(previous_extraction: str, text: str) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.append({"role": "user", "content": SELF_AUGMENTATION_PROMPT.format(
        previous_extraction=previous_extraction, text=text
    )})
    return messages


SYNTHESIS_EXTRACTION_PROMPT = """Extract synthesis information of the nanozyme "{nanozyme_name}" from the following text.

Focus on:
- Synthesis method (e.g., hydrothermal, solvothermal, co-precipitation, pyrolysis, sol-gel, electrodeposition, microwave-assisted)
- Temperature (in °C if reported)
- Time (duration of synthesis step)
- Precursors (chemical names of starting materials)
- Solvent (if mentioned, e.g., water, ethanol, DMF)
- Atmosphere (e.g., Ar, N2, air)
- Post-treatment (e.g., calcination, annealing, reduction)

Text:
{text}

Respond in JSON format:
{{
  "synthesis_method": "<method or null>",
  "synthesis_conditions": {{
    "temperature": <number in °C or null>,
    "time": "<time string or null>",
    "precursors": ["<precursor1>", "<precursor2>"],
    "solvent": "<solvent or null>",
    "atmosphere": "<atmosphere or null>",
    "post_treatment": "<treatment or null>"
  }},
  "characterization": ["<technique1>", "<technique2>"]
}}"""

SYNTHESIS_FEW_SHOT_EXAMPLES = [
    {
        "input": "The Fe3O4@C nanoparticles were synthesized via a solvothermal method. Briefly, FeCl3·6H2O (1.35 g) and sodium citrate (0.4 g) were dissolved in 40 mL of ethylene glycol under stirring. The mixture was transferred to a Teflon-lined autoclave and heated at 200°C for 10 h. The products were washed with ethanol and dried at 60°C. XRD, TEM, XPS and VSM were used for characterization.",
        "output": {
            "synthesis_method": "solvothermal",
            "synthesis_conditions": {
                "temperature": 200,
                "time": "10 h",
                "precursors": ["FeCl3·6H2O", "sodium citrate"],
                "solvent": "ethylene glycol",
                "atmosphere": None,
                "post_treatment": "dried at 60°C"
            },
            "characterization": ["XRD", "TEM", "XPS", "VSM"]
        }
    },
    {
        "input": "Mo-SAN was prepared by pyrolysis of the Mo-PhIM precursor at 900°C for 2 h under Ar atmosphere, followed by acid etching with 0.5 M H2SO4 to remove unstable Mo species. The final product was washed with deionized water and dried under vacuum. HAADF-STEM, XAFS, and XPS confirmed the atomic dispersion of Mo.",
        "output": {
            "synthesis_method": "pyrolysis",
            "synthesis_conditions": {
                "temperature": 900,
                "time": "2 h",
                "precursors": ["Mo-PhIM"],
                "solvent": None,
                "atmosphere": "Ar",
                "post_treatment": "acid etching with 0.5 M H2SO4"
            },
            "characterization": ["HAADF-STEM", "XAFS", "XPS"]
        }
    },
    {
        "input": "Co-Fe LDH was synthesized by a co-precipitation method. Co(NO3)2·6H2O and Fe(NO3)3·9H2O (molar ratio 3:1) were dissolved in deionized water. NaOH solution (1 M) was added dropwise under vigorous stirring until pH reached 10. The suspension was aged at 60°C for 30 min, then transferred to an autoclave and heated at 120°C for 6 h. The product was collected by centrifugation, washed with water and ethanol, and dried at 60°C overnight.",
        "output": {
            "synthesis_method": "co-precipitation with hydrothermal aging",
            "synthesis_conditions": {
                "temperature": 120,
                "time": "6 h",
                "precursors": ["Co(NO3)2·6H2O", "Fe(NO3)3·9H2O", "NaOH"],
                "solvent": "deionized water",
                "atmosphere": None,
                "post_treatment": "dried at 60°C overnight"
            },
            "characterization": []
        }
    },
]

PH_TEMP_EXTRACTION_PROMPT = """Extract optimal pH and temperature conditions for the nanozyme "{nanozyme_name}" from the following text.

Focus on:
- Optimal pH value (the pH at which catalytic activity is maximum)
- pH range (the range where activity is measurable, e.g., "3.0-9.0")
- Optimal temperature (in °C, the temperature at which catalytic activity is maximum)
- Temperature range (the range where activity is measurable, e.g., "20-80°C")

HOW TO IDENTIFY OPTIMAL VALUES:
1. Direct statements: "The optimal pH was 4.0" or "maximum activity at pH 4.0"
2. From figure descriptions: "As shown in Fig. 3b, the activity reached its maximum at pH 4.0"
3. From comparison: "The activity at pH 4.0 was significantly higher than at other pH values"
4. From assay conditions: "All kinetic assays were performed at pH 4.0 and 37°C" (when this is the standard condition)
5. Temperature in °C: convert from K if needed (K - 273.15 = °C)

Text:
{text}

Respond in JSON format:
{{
  "pH_profile": {{
    "optimal_pH": <number or null>,
    "pH_range": "<range string or null>"
  }},
  "temperature_profile": {{
    "optimal_temperature": <number in °C or null>,
    "temperature_range": "<range string or null>"
  }}
}}"""

PH_TEMP_FEW_SHOT_EXAMPLES = [
    {
        "input": "The effect of pH on the peroxidase-like activity of Fe3O4@C was investigated. As shown in Fig. 4A, the optimal pH was 4.0, and the catalytic activity could be observed in the pH range of 2.0-7.0. The effect of temperature was also studied (Fig. 4B), and the maximum activity was achieved at 40°C with a temperature range of 20-70°C.",
        "output": {
            "pH_profile": {"optimal_pH": 4.0, "pH_range": "2.0-7.0"},
            "temperature_profile": {"optimal_temperature": 40, "temperature_range": "20-70°C"}
        }
    },
    {
        "input": "All catalytic experiments were performed at 37°C in acetate buffer (pH 3.5) unless otherwise stated. The nanozyme retained 80% of its activity between pH 3.0 and 5.0.",
        "output": {
            "pH_profile": {"optimal_pH": 3.5, "pH_range": "3.0-5.0"},
            "temperature_profile": {"optimal_temperature": 37, "temperature_range": None}
        }
    },
    {
        "input": "Figure 5 shows the pH-dependent and temperature-dependent activities of the Au@Pd nanozyme. The relative activity reached 100% at pH 4.0 and decreased sharply above pH 6.0. The optimal temperature was determined to be 45°C. The nanozyme maintained over 60% activity from 25 to 65°C.",
        "output": {
            "pH_profile": {"optimal_pH": 4.0, "pH_range": None},
            "temperature_profile": {"optimal_temperature": 45, "temperature_range": "25-65°C"}
        }
    },
]


def build_synthesis_prompt(nanozyme_name: str, text: str, include_examples: bool = True) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if include_examples:
        for ex in SYNTHESIS_FEW_SHOT_EXAMPLES:
            messages.append({"role": "user", "content": SYNTHESIS_EXTRACTION_PROMPT.format(
                nanozyme_name=nanozyme_name, text=ex["input"]
            )})
            messages.append({"role": "assistant", "content": json.dumps(ex["output"], ensure_ascii=False)})
    messages.append({"role": "user", "content": SYNTHESIS_EXTRACTION_PROMPT.format(
        nanozyme_name=nanozyme_name, text=text
    )})
    return messages


def build_ph_temp_prompt(nanozyme_name: str, text: str, include_examples: bool = True) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if include_examples:
        for ex in PH_TEMP_FEW_SHOT_EXAMPLES:
            messages.append({"role": "user", "content": PH_TEMP_EXTRACTION_PROMPT.format(
                nanozyme_name=nanozyme_name, text=ex["input"]
            )})
            messages.append({"role": "assistant", "content": json.dumps(ex["output"], ensure_ascii=False)})
    messages.append({"role": "user", "content": PH_TEMP_EXTRACTION_PROMPT.format(
        nanozyme_name=nanozyme_name, text=text
    )})
    return messages


TABLE_KINETICS_EXTRACTION_PROMPT = """Extract kinetic parameters from the following TABLE data about a nanozyme named "{nanozyme_name}".

This is structured table data. Pay special attention to:
1. Identify which row belongs to the TARGET nanozyme "{nanozyme_name}" — look for "this work", "our catalyst", the material name, or the first data row
2. Rows for OTHER materials (HRP, natural enzymes, other nanozymes) are REFERENCE data — extract them ONLY in kinetics_list with material_variant field
3. Column headers specify units — e.g., "Km (mM)" means the Km values are already in mM
4. Scientific notation in tables: "4.41 × 10⁻⁵" or "4.41E-05" should be converted to decimal (4.41e-5)
5. If the table has multiple substrates, extract kinetics for EACH substrate

Table data:
{text}

Respond in JSON format:
{{
  "kinetics": {{
    "Km": <number or null>,
    "Km_unit": "<unit or null>",
    "Vmax": <number or null>,
    "Vmax_unit": "<unit or null>",
    "kcat": <number or null>,
    "kcat_unit": "<unit or null>",
    "kcat_Km": <number or null>,
    "kcat_Km_unit": "<unit or null>",
    "substrate": "<primary substrate or null>",
    "detection_method": "<method or null>",
    "material_variant": "<material name or null>"
  }},
  "kinetics_list": [
    {{
      "Km": <number or null>,
      "Km_unit": "<unit or null>",
      "Vmax": <number or null>,
      "Vmax_unit": "<unit or null>",
      "kcat": <number or null>,
      "kcat_unit": "<unit or null>",
      "kcat_Km": <number or null>,
      "kcat_Km_unit": "<unit or null>",
      "substrate": "<substrate name>",
      "material_variant": "<material name>",
      "detection_method": "<method or null>"
    }}
  ]
}}"""

TABLE_KINETICS_FEW_SHOT_EXAMPLES = [
    {
        "input": """| Catalyst | Substrate | Km (mM) | Vmax (M/s) |
|----------|-----------|---------|------------|
| Fe3O4@C (this work) | TMB | 0.35 | 4.41 × 10⁻⁵ |
| Fe3O4@C (this work) | H2O2 | 0.89 | 7.9 × 10⁻⁸ |
| HRP | TMB | 0.434 | 2.47 × 10⁻⁷ |""",
        "output": {
            "kinetics": {
                "Km": 0.35, "Km_unit": "mM",
                "Vmax": 44.1, "Vmax_unit": "μM/s",
                "kcat": None, "kcat_unit": None,
                "kcat_Km": None, "kcat_Km_unit": None,
                "substrate": "TMB",
                "detection_method": None,
                "material_variant": "Fe3O4@C"
            },
            "kinetics_list": [
                {"Km": 0.35, "Km_unit": "mM", "Vmax": 44.1, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "kcat_Km": None, "kcat_Km_unit": None, "substrate": "TMB", "material_variant": "Fe3O4@C", "detection_method": None},
                {"Km": 0.89, "Km_unit": "mM", "Vmax": 0.079, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "kcat_Km": None, "kcat_Km_unit": None, "substrate": "H2O2", "material_variant": "Fe3O4@C", "detection_method": None},
                {"Km": 0.434, "Km_unit": "mM", "Vmax": 0.247, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "kcat_Km": None, "kcat_Km_unit": None, "substrate": "TMB", "material_variant": "HRP", "detection_method": None}
            ]
        }
    },
    {
        "input": """Table 2. Comparison of kinetic parameters.
| Sample | Km (mM) | Vmax (10⁻⁸ M/s) | kcat (s⁻¹) |
|--------|---------|------------------|-------------|
| Au@Pd | 0.35 | 5.6 | 85200 |
| Au NPs | 0.82 | 2.1 | 34500 |
| Pd NPs | 1.24 | 1.8 | 22100 |""",
        "output": {
            "kinetics": {
                "Km": 0.35, "Km_unit": "mM",
                "Vmax": 0.056, "Vmax_unit": "μM/s",
                "kcat": 85200.0, "kcat_unit": "s⁻¹",
                "kcat_Km": None, "kcat_Km_unit": None,
                "substrate": "TMB",
                "detection_method": None,
                "material_variant": "Au@Pd"
            },
            "kinetics_list": [
                {"Km": 0.35, "Km_unit": "mM", "Vmax": 0.056, "Vmax_unit": "μM/s", "kcat": 85200.0, "kcat_unit": "s⁻¹", "kcat_Km": None, "kcat_Km_unit": None, "substrate": "TMB", "material_variant": "Au@Pd", "detection_method": None},
                {"Km": 0.82, "Km_unit": "mM", "Vmax": 0.021, "Vmax_unit": "μM/s", "kcat": 34500.0, "kcat_unit": "s⁻¹", "kcat_Km": None, "kcat_Km_unit": None, "substrate": "TMB", "material_variant": "Au NPs", "detection_method": None},
                {"Km": 1.24, "Km_unit": "mM", "Vmax": 0.018, "Vmax_unit": "μM/s", "kcat": 22100.0, "kcat_unit": "s⁻¹", "kcat_Km": None, "kcat_Km_unit": None, "substrate": "TMB", "material_variant": "Pd NPs", "detection_method": None}
            ]
        }
    },
    {
        "input": """| Material | Substrate | Km | Vmax | kcat/Km |
|----------|-----------|-----|------|---------|
| R-MnCo2O4 | TMB | 0.018 mM | 1.2 × 10⁻⁷ M/s | - |
| MnCo2O4 | TMB | 0.05 mM | 1.7 × 10⁻⁷ M/s | - |""",
        "output": {
            "kinetics": {
                "Km": 0.018, "Km_unit": "mM",
                "Vmax": 0.12, "Vmax_unit": "μM/s",
                "kcat": None, "kcat_unit": None,
                "kcat_Km": None, "kcat_Km_unit": None,
                "substrate": "TMB",
                "detection_method": None,
                "material_variant": "R-MnCo2O4"
            },
            "kinetics_list": [
                {"Km": 0.018, "Km_unit": "mM", "Vmax": 0.12, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "kcat_Km": None, "kcat_Km_unit": None, "substrate": "TMB", "material_variant": "R-MnCo2O4", "detection_method": None},
                {"Km": 0.05, "Km_unit": "mM", "Vmax": 0.17, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "kcat_Km": None, "kcat_Km_unit": None, "substrate": "TMB", "material_variant": "MnCo2O4", "detection_method": None}
            ]
        }
    },
]


def build_table_kinetics_prompt(nanozyme_name: str, text: str, include_examples: bool = True) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if include_examples:
        for ex in TABLE_KINETICS_FEW_SHOT_EXAMPLES:
            messages.append({"role": "user", "content": TABLE_KINETICS_EXTRACTION_PROMPT.format(
                nanozyme_name=nanozyme_name, text=ex["input"]
            )})
            messages.append({"role": "assistant", "content": json.dumps(ex["output"], ensure_ascii=False)})
    messages.append({"role": "user", "content": TABLE_KINETICS_EXTRACTION_PROMPT.format(
        nanozyme_name=nanozyme_name, text=text
    )})
    return messages


VERIFICATION_PROMPT = """You are a nanozyme data verification expert. Review the following extraction result against the original text and identify any errors.

Nanozyme name: "{nanozyme_name}"

Original text:
{text}

Extraction result:
{extraction_result}

Check for these common errors:
1. WRONG VALUES: Km, Vmax, kcat values that don't match the text
2. WRONG UNITS: Unit mismatch (e.g., text says mM but extraction says μM)
3. MISSING DATA: Values present in text but missing from extraction
4. FABRICATED DATA: Values in extraction not found in text
5. WRONG SUBSTRATE: Substrate name doesn't match text
6. UNIT CONVERSION ERRORS: Incorrect conversion (e.g., M/s to μM/s should multiply by 1e6)

If you find errors, provide the CORRECTED extraction result. If no errors, return the original result unchanged.

Respond in JSON format:
{{
  "has_errors": <true or false>,
  "errors_found": ["<description of error 1>", "<description of error 2>"],
  "corrected_result": <the corrected extraction result, same structure as input>
}}"""


def build_verification_prompt(nanozyme_name: str, text: str, extraction_result: str) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.append({"role": "user", "content": VERIFICATION_PROMPT.format(
        nanozyme_name=nanozyme_name,
        text=text,
        extraction_result=extraction_result,
    )})
    return messages
