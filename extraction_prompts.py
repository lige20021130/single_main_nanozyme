import json
from typing import Dict, List, Any, Optional

from schema_constraints import (
    get_enzyme_type_enum_string,
    get_application_type_enum_string,
)

SYSTEM_PROMPT = """You are an expert nanozyme data extractor. Your task is to extract structured data from scientific literature about nanozymes (nanomaterials with enzyme-like catalytic activity).

CRITICAL DOMAIN KNOWLEDGE:
1. A nanozyme is a nanomaterial that mimics the catalytic activity of natural enzymes
2. Enzyme-like types include: {enzyme_types}
3. Application types include: {app_types}
4. Km (Michaelis constant) for nanozymes is typically 0.001-500 mM; values >1 M or >1000 mM are likely errors
5. Vmax is typically reported in μM/s or mM/s; M/s values <1.0 should be converted to μM/s (multiply by 1e6)
6. Common substrates for peroxidase-like: TMB, ABTS, DAB, OPD, H2O2
7. Common substrates for oxidase-like: glucose, ascorbic acid, uric acid
8. When multiple substrates are tested, extract kinetics for EACH substrate separately into kinetics_list
9. Material names with @ or / (e.g., Fe3O4@C, Co-N-C) are composite/doped materials — these are MORE specific than simple oxide names
10. Morphology should be specific (e.g., "uniform hollow polyhedral", "core-shell spherical"), NOT generic (e.g., "nanoparticle")

HARD RULES:
1. Extract ONLY information explicitly stated in the text — do NOT guess or fabricate
2. Use null for missing values (not 0, not empty string)
3. Include units exactly as reported in the paper
4. For multi-substrate kinetics, put the PRIMARY substrate in kinetics and ALL substrates in kinetics_list
5. Output valid JSON only — no Markdown fences, no comments, no explanations
6. If a value uses scientific notation (e.g., 4.41 × 10⁻⁵), convert to decimal (e.g., 4.41e-5)
""".format(
    enzyme_types=get_enzyme_type_enum_string(),
    app_types=get_application_type_enum_string(),
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
    "substrate": "<primary substrate name or null>"
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
