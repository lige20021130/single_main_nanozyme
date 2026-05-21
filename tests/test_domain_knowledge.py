import pytest


def test_load_domain_knowledge():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    assert dk.enzyme_types is not None
    assert len(dk.enzyme_types) > 20


def test_get_enzyme_type_values():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    values = dk.get_enzyme_type_values()
    assert "peroxidase-like" in values
    assert "oxidase-like" in values
    assert isinstance(values, list)


def test_get_enzyme_alias_map():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    alias_map = dk.get_enzyme_alias_map()
    assert alias_map["pod-like"] == "peroxidase-like"
    assert alias_map["peroxidase-mimicking"] == "peroxidase-like"
    assert alias_map["cat-like"] == "catalase-like"


def test_get_application_alias_map():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    alias_map = dk.get_application_alias_map()
    assert alias_map["detection"] == "sensing"
    assert alias_map["biosensor"] == "sensing"


def test_get_application_type_values():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    values = dk.get_application_type_values()
    assert "sensing" in values
    assert "therapeutic" in values


def test_get_probe_molecule_names():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    names = dk.get_probe_molecule_names()
    assert "crystal violet" in names
    assert "methylene blue" in names


def test_get_substrate_enzyme_mapping():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    mapping = dk.get_substrate_enzyme_mapping()
    assert "TMB" in mapping
    assert "peroxidase-like" in mapping["TMB"]


def test_get_numeric_ranges():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    km_range = dk.get_numeric_range("Km")
    assert km_range["typical_min"] == 0.001
    assert km_range["typical_max"] == 500


def test_generate_enzyme_type_prompt_snippet():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    snippet = dk.generate_enzyme_type_prompt_snippet()
    assert "peroxidase-like" in snippet
    assert "oxidase-like" in snippet


def test_generate_substrate_prompt_snippet():
    from domain_knowledge import DomainKnowledge
    dk = DomainKnowledge()
    snippet = dk.generate_substrate_prompt_snippet()
    assert "TMB" in snippet


def test_singleton_pattern():
    from domain_knowledge import get_domain_knowledge
    dk1 = get_domain_knowledge()
    dk2 = get_domain_knowledge()
    assert dk1 is dk2
