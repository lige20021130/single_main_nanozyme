import re
import logging
from typing import Dict, List, Optional, Any

from numeric_validator import NumericValidator, normalize_unit
from activity_selector import ActivitySelector, normalize_enzyme_type, normalize_assay_method
from application_extractor import ApplicationExtractor
from table_classifier import TableClassifier
from figure_handler import FigureHandler
from diagnostics_builder import DiagnosticsBuilder

logger = logging.getLogger(__name__)

_CITE_THIS_RE = re.compile(r'(?i)cite\s+this|please\s+cite|citation|doi:\s*10\.')
_JOURNAL_PAGE_RE = re.compile(r'\b\d{4,5}\s*-\s*\d{4,5}\b')
_AUTHOR_SEPARATOR_RE = re.compile(r'[;,]|\band\b')

_REDUNDANT_SUFFIXES = (
    "nanoparticles", "nps", "nanozyme", "nanosheets", "nanorods",
    "nanofibers", "nanoclusters", "nanocubes", "nanowires", "nanotubes",
    "nanostructures", "nanocomposites", "nanoplates", "nanoflowers", "nanospheres",
)
_REDUNDANT_SUFFIX_RE = re.compile(
    r'\s+(' + '|'.join(re.escape(s) for s in _REDUNDANT_SUFFIXES) + r')\s*$',
    re.IGNORECASE,
)


def _clean_author_field(author: Optional[str]) -> Optional[str]:
    if not author:
        return None
    author = author.strip()
    if _CITE_THIS_RE.search(author):
        return None
    if _JOURNAL_PAGE_RE.search(author) and len(author) < 50:
        return None
    if len(author) > 500:
        parts = _AUTHOR_SEPARATOR_RE.split(author)
        author = "; ".join(p.strip() for p in parts[:10] if p.strip())
    return author


def _select_nanozyme(
    nanozyme_systems: List[Dict[str, Any]],
    title: str = "",
    abstract: str = "",
) -> tuple:
    if not nanozyme_systems:
        return None, False

    if len(nanozyme_systems) == 1:
        sys = nanozyme_systems[0]
        name = sys.get("material_name_raw") or sys.get("system_name") or ""
        return name, False

    title_abs = (title + " " + abstract).lower()
    scored = []
    for sys in nanozyme_systems:
        name = sys.get("material_name_raw") or sys.get("system_name") or ""
        score = 0
        name_lower = name.lower()
        if name_lower and name_lower in title_abs:
            score += 10
        evidence_refs = sys.get("evidence_refs", [])
        if isinstance(evidence_refs, list):
            score += min(len(evidence_refs), 5)
        substrates = sys.get("substrates", [])
        if isinstance(substrates, list):
            score += min(len(substrates), 3)
        activities = sys.get("activities", [])
        if isinstance(activities, list):
            score += min(len(activities), 3)
        scored.append((score, name, sys))

    scored.sort(key=lambda x: x[0], reverse=True)

    ambiguous = False
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        ambiguous = True

    best_name = scored[0][1] if scored else ""
    return best_name, ambiguous


def _extract_supporting_text(
    evidence_list: List[Dict[str, Any]],
    category: str,
) -> List[str]:
    texts: List[str] = []
    for ev in evidence_list:
        if not isinstance(ev, dict):
            continue
        ev_cat = (ev.get("category", "") or "").lower()
        ev_text = ev.get("text", "") or ev.get("evidence_text", "") or ""
        if category == "material" and ev_cat in ("material", "composition", "characterization"):
            if ev_text:
                texts.append(ev_text.strip())
        elif category == "activity" and ev_cat in ("activity", "catalytic", "enzyme"):
            if ev_text:
                texts.append(ev_text.strip())
        elif category == "kinetics" and ev_cat in ("kinetics", "kinetic_parameter", "michaelis_menten"):
            if ev_text:
                texts.append(ev_text.strip())
        elif category == "application" and ev_cat in ("application", "sensing", "detection", "therapeutic"):
            if ev_text:
                texts.append(ev_text.strip())
    return texts


class SingleRecordAssembler:
    def __init__(self):
        self.numeric_validator = NumericValidator()
        self.activity_selector = ActivitySelector()
        self.application_extractor = ApplicationExtractor()
        self.table_classifier = TableClassifier()
        self.figure_handler = FigureHandler()
        self.diagnostics_builder = DiagnosticsBuilder()

    def assemble(
        self,
        llm_results: List[Dict[str, Any]],
        vlm_results: Optional[List[Dict[str, Any]]] = None,
        table_results: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        extracted_hints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        metadata = metadata or {}
        extracted_hints = extracted_hints or {}
        vlm_results = vlm_results or []
        table_results = table_results or []

        merged = self._merge_llm_results(llm_results)

        paper_raw = merged.get("paper", {})
        nanozyme_systems = merged.get("nanozyme_systems", [])
        catalytic_activities = merged.get("catalytic_activities", [])
        raw_applications = merged.get("applications", [])
        evidence_list = merged.get("evidence", [])

        title = paper_raw.get("title", "") or metadata.get("title", "")
        abstract = metadata.get("abstract", "") or ""
        is_supplementary = metadata.get("is_supplementary", False)

        selected_nanozyme, nanozyme_ambiguous = _select_nanozyme(
            nanozyme_systems, title, abstract
        )

        classified_tables = self.table_classifier.classify_and_filter(
            table_results, selected_nanozyme
        )

        figure_output = self.figure_handler.process_vlm_results(
            vlm_results, selected_nanozyme
        )

        main_activity = self.activity_selector.select_main_activity(
            catalytic_activities, selected_nanozyme,
            title=title, abstract=abstract,
            applications=raw_applications,
        )

        kinetics_candidates = []
        if main_activity and main_activity.get("kinetics_candidates"):
            kinetics_candidates.extend(main_activity["kinetics_candidates"])

        for tbl in self.table_classifier.get_kinetics_tables():
            for rec in tbl.get("records", []):
                if isinstance(rec, dict):
                    if rec.get("Km_value") is not None:
                        kinetics_candidates.append({
                            "parameter": "Km",
                            "value": rec["Km_value"],
                            "unit": rec.get("Km_unit"),
                            "substrate": rec.get("substrate"),
                            "source": "table",
                            "evidence_text": rec.get("evidence_text", ""),
                        })
                    if rec.get("Vmax_value") is not None:
                        kinetics_candidates.append({
                            "parameter": "Vmax",
                            "value": rec["Vmax_value"],
                            "unit": rec.get("Vmax_unit"),
                            "substrate": rec.get("substrate"),
                            "source": "table",
                            "evidence_text": rec.get("evidence_text", ""),
                        })

        kinetics_candidates.extend(figure_output.get("caption_explicit_values", []))
        kinetics_candidates.extend(figure_output.get("figure_candidates", []))

        kinetics = self.numeric_validator.resolve_kinetics(
            kinetics_candidates, selected_nanozyme,
            main_activity.get("enzyme_like_type") if main_activity else None,
        )

        applications = self.application_extractor.extract_applications(
            raw_applications, selected_nanozyme,
            table_summaries=classified_tables,
            main_activity_type=main_activity.get("enzyme_like_type") if main_activity else None,
        )

        important_values = []
        important_values.extend(self.numeric_validator.get_important_values())
        important_values.extend(self.figure_handler.get_important_values())

        supporting_text = {
            "material": _extract_supporting_text(evidence_list, "material"),
            "activity": _extract_supporting_text(evidence_list, "activity"),
            "kinetics": _extract_supporting_text(evidence_list, "kinetics"),
            "application": _extract_supporting_text(evidence_list, "application"),
        }

        fig_supporting = figure_output.get("supporting_text", [])
        supporting_text["activity"].extend(fig_supporting)

        paper = self._build_paper(paper_raw, metadata)

        selected_nanozyme_dict = self._build_selected_nanozyme(
            nanozyme_systems, selected_nanozyme
        )

        main_activity_dict = self._build_main_activity_dict(
            main_activity, kinetics
        )

        has_figure_kinetics = any(
            c.get("source") == "figure_candidate"
            for c in kinetics_candidates
            if c.get("value") is not None
        )

        diagnostics = self.diagnostics_builder \
            .set_parse_status(metadata.get("parse_status")) \
            .set_supplementary(is_supplementary) \
            .set_selected_nanozyme(selected_nanozyme, nanozyme_ambiguous) \
            .set_main_activity(main_activity) \
            .set_kinetics(kinetics) \
            .set_applications(applications) \
            .add_numeric_warnings(self.numeric_validator.get_warnings()) \
            .add_table_warnings(self.table_classifier.get_warnings()) \
            .add_figure_warnings(self.figure_handler.get_warnings()) \
            .add_activity_warnings(self.activity_selector.get_warnings()) \
            .add_application_warnings(self.application_extractor.get_warnings()) \
            .set_caption_low_confidence(figure_output.get("low_confidence_count", 0) > 0) \
            .set_kinetics_from_figure(has_figure_kinetics) \
            .build()

        result = {
            "paper": paper,
            "selected_nanozyme": selected_nanozyme_dict,
            "main_activity": main_activity_dict,
            "applications": applications,
            "important_values": important_values,
            "raw_supporting_text": supporting_text,
            "diagnostics": diagnostics,
        }

        if result.get("main_activity", {}).get("kinetics"):
            kin = result["main_activity"]["kinetics"]
            for uk in ("Km_unit", "Vmax_unit", "kcat_unit", "kcat_Km_unit"):
                if kin.get(uk):
                    kin[uk] = normalize_unit(kin[uk])

        logger.info(
            f"[SingleRecordAssembler] assembled: "
            f"nanozyme={selected_nanozyme}, "
            f"activity={main_activity_dict.get('enzyme_like_type') if main_activity_dict else None}, "
            f"Km={kinetics.get('Km')}, Vmax={kinetics.get('Vmax')}, "
            f"apps={len(applications)}, "
            f"diagnostics={diagnostics['status']}/{diagnostics['confidence']}"
        )

        return result

    def _merge_llm_results(self, llm_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        merged: Dict[str, Any] = {
            "paper": {},
            "nanozyme_systems": [],
            "catalytic_activities": [],
            "applications": [],
            "evidence": [],
        }
        for r in llm_results:
            if not isinstance(r, dict):
                continue
            if r.get("_placeholder"):
                continue
            paper = r.get("paper", {})
            if isinstance(paper, dict):
                for k, v in paper.items():
                    if v and (k not in merged["paper"] or not merged["paper"][k]):
                        merged["paper"][k] = v
            for key in ("nanozyme_systems", "catalytic_activities", "applications", "evidence"):
                items = r.get(key, [])
                if isinstance(items, list):
                    merged[key].extend(items)
        return merged

    def _build_paper(
        self,
        paper_raw: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        paper: Dict[str, Any] = {}

        title = paper_raw.get("title") or metadata.get("title")
        if title:
            paper["title"] = title

        authors = paper_raw.get("authors") or metadata.get("author") or metadata.get("authors")
        authors = _clean_author_field(authors)
        if authors:
            paper["authors"] = authors

        journal = paper_raw.get("journal") or metadata.get("journal")
        if journal:
            paper["journal"] = journal

        year = paper_raw.get("year") or metadata.get("year")
        if year is not None:
            if isinstance(year, str):
                try:
                    year = int(year)
                except (ValueError, TypeError):
                    pass
            paper["year"] = year

        doi = paper_raw.get("doi") or metadata.get("doi")
        if doi:
            paper["doi"] = doi

        return paper

    def _build_selected_nanozyme(
        self,
        nanozyme_systems: List[Dict[str, Any]],
        selected_name: Optional[str],
    ) -> Dict[str, Any]:
        cleaned_name = selected_name
        if cleaned_name:
            cleaned_name = _REDUNDANT_SUFFIX_RE.sub('', cleaned_name).strip()

        result: Dict[str, Any] = {
            "material_name": cleaned_name,
            "raw_name": selected_name if selected_name and selected_name != cleaned_name else None,
            "synthesis_method": None,
            "synthesis_conditions": {
                "temperature": None, "time": None, "precursors": [],
                "method_detail": None,
            },
            "crystal_structure": None,
            "surface_area": None,
            "zeta_potential": None,
            "pore_size": None,
            "size_unit": None,
            "size_distribution": None,
        }
        if not selected_name or not nanozyme_systems:
            return result

        matched_sys = None
        sel_lower = selected_name.lower().strip()
        for sys in nanozyme_systems:
            sys_name = (sys.get("material_name_raw") or sys.get("system_name") or "").lower().strip()
            if sys_name and (sel_lower in sys_name or sys_name in sel_lower):
                matched_sys = sys
                break

        if matched_sys:
            composition = matched_sys.get("composition")
            if composition:
                result["composition"] = composition

            morphology = matched_sys.get("morphology")
            if morphology:
                result["morphology"] = morphology

            metal_center = matched_sys.get("metal_center")
            if metal_center:
                result["metal_center"] = metal_center

            characterization = matched_sys.get("characterization")
            if characterization:
                result["characterization"] = characterization

            synthesis_method = matched_sys.get("synthesis_method")
            if synthesis_method:
                result["synthesis_method"] = synthesis_method

            synth_cond = matched_sys.get("synthesis_conditions")
            if isinstance(synth_cond, dict):
                result["synthesis_conditions"] = synth_cond

            crystal_structure = matched_sys.get("crystal_structure")
            if crystal_structure:
                result["crystal_structure"] = crystal_structure

            surface_area = matched_sys.get("surface_area")
            if surface_area:
                result["surface_area"] = surface_area

            zeta_potential = matched_sys.get("zeta_potential")
            if zeta_potential:
                result["zeta_potential"] = zeta_potential

            pore_size = matched_sys.get("pore_size")
            if pore_size:
                result["pore_size"] = pore_size

            size_unit = matched_sys.get("size_unit")
            if size_unit:
                result["size_unit"] = size_unit

            size_distribution = matched_sys.get("size_distribution")
            if size_distribution:
                result["size_distribution"] = size_distribution

        return result

    def _build_main_activity_dict(
        self,
        main_activity: Optional[Dict[str, Any]],
        kinetics: Dict[str, Any],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "enzyme_like_type": "unknown",
            "assay_method": None,
            "signal": None,
            "substrates": [],
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
                "Km": None,
                "Km_unit": None,
                "Vmax": None,
                "Vmax_unit": None,
                "kcat": None,
                "kcat_unit": None,
                "kcat_Km": None,
                "kcat_Km_unit": None,
                "substrate": None,
                "source": None,
                "needs_review": False,
            },
            "mechanism": None,
        }

        if main_activity:
            result["enzyme_like_type"] = main_activity.get("enzyme_like_type", "unknown")
            result["assay_method"] = main_activity.get("assay_method")
            result["signal"] = main_activity.get("signal")
            result["substrates"] = main_activity.get("substrates", [])
            result["mechanism"] = main_activity.get("mechanism")

            conditions = main_activity.get("conditions")
            if isinstance(conditions, dict):
                result["conditions"] = conditions

            ph_profile = main_activity.get("pH_profile")
            if isinstance(ph_profile, dict):
                result["pH_profile"] = ph_profile

            temp_profile = main_activity.get("temperature_profile")
            if isinstance(temp_profile, dict):
                result["temperature_profile"] = temp_profile

        if kinetics:
            result["kinetics"] = kinetics

        return result
