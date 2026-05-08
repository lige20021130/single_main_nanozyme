import pytest
from schema_constraints import (
    validate_against_schema,
    auto_fix_schema_errors,
    get_enzyme_type_enum_string,
    get_application_type_enum_string,
    _ENZYME_TYPE_ENUM,
    _APPLICATION_TYPE_ENUM,
)


def test_valid_data_passes():
    data = {
        "selected_nanozyme": {"name": "Fe3O4"},
        "main_activity": {"enzyme_like_type": "peroxidase-like"}
    }
    errors = validate_against_schema(data)
    assert len(errors) == 0


def test_missing_name_fails():
    data = {"selected_nanozyme": {}, "main_activity": {}}
    errors = validate_against_schema(data)
    assert any("name is required" in e for e in errors)


def test_invalid_enzyme_type():
    data = {
        "selected_nanozyme": {"name": "Fe3O4"},
        "main_activity": {"enzyme_like_type": "invalid-type"}
    }
    errors = validate_against_schema(data)
    assert any("not in allowed enum" in e for e in errors)


def test_all_enzyme_types_valid():
    for etype in _ENZYME_TYPE_ENUM:
        data = {
            "selected_nanozyme": {"name": "test"},
            "main_activity": {"enzyme_like_type": etype}
        }
        errors = validate_against_schema(data)
        assert not any("not in allowed enum" in e for e in errors), f"{etype} should be valid"


def test_unrealistic_km_molar():
    data = {
        "selected_nanozyme": {"name": "Fe3O4"},
        "main_activity": {
            "kinetics": {"Km": 8.0, "Km_unit": "M"}
        }
    }
    errors = validate_against_schema(data)
    assert any("unrealistically large" in e for e in errors)


def test_unrealistic_km_mM():
    data = {
        "selected_nanozyme": {"name": "Fe3O4"},
        "main_activity": {
            "kinetics": {"Km": 1500, "Km_unit": "mM"}
        }
    }
    errors = validate_against_schema(data)
    assert any("unrealistically large" in e for e in errors)


def test_reasonable_km_mM():
    data = {
        "selected_nanozyme": {"name": "Fe3O4"},
        "main_activity": {
            "kinetics": {"Km": 0.35, "Km_unit": "mM"}
        }
    }
    errors = validate_against_schema(data)
    assert not any("unrealistically large" in e for e in errors)


def test_vmax_m_per_s_conversion_needed():
    data = {
        "selected_nanozyme": {"name": "Fe3O4"},
        "main_activity": {
            "kinetics": {"Vmax": 4.41e-05, "Vmax_unit": "M/s"}
        }
    }
    errors = validate_against_schema(data)
    assert any("converted" in e for e in errors)


def test_vmax_mM_per_s_conversion_needed():
    data = {
        "selected_nanozyme": {"name": "Fe3O4"},
        "main_activity": {
            "kinetics": {"Vmax": 0.0832, "Vmax_unit": "mM/s"}
        }
    }
    errors = validate_against_schema(data)
    assert any("converted" in e for e in errors)


def test_kinetics_list_validation():
    data = {
        "selected_nanozyme": {"name": "Fe3O4"},
        "main_activity": {
            "kinetics_list": [
                {"Km": 5.0, "Km_unit": "M", "Vmax": 1e-6, "Vmax_unit": "M/s"}
            ]
        }
    }
    errors = validate_against_schema(data)
    assert any("kinetics_list[0]" in e and "unrealistically large" in e for e in errors)
    assert any("kinetics_list[0]" in e and "converted" in e for e in errors)


def test_invalid_application_type():
    data = {
        "selected_nanozyme": {"name": "Fe3O4"},
        "main_activity": {},
        "applications": [{"application_type": "invalid_type"}]
    }
    errors = validate_against_schema(data)
    assert any("not in allowed enum" in e for e in errors)


def test_auto_fix_unrealistic_km():
    data = {
        "selected_nanozyme": {"name": "Fe3O4"},
        "main_activity": {
            "kinetics": {"Km": 8.0, "Km_unit": "M"}
        }
    }
    errors = validate_against_schema(data)
    fixed = auto_fix_schema_errors(data, errors)
    assert fixed["main_activity"]["kinetics"]["Km"] is None


def test_auto_fix_vmax_conversion():
    data = {
        "selected_nanozyme": {"name": "Fe3O4"},
        "main_activity": {
            "kinetics": {"Vmax": 4.41e-05, "Vmax_unit": "M/s"}
        }
    }
    errors = validate_against_schema(data)
    fixed = auto_fix_schema_errors(data, errors)
    assert abs(fixed["main_activity"]["kinetics"]["Vmax"] - 44.1) < 0.1
    assert fixed["main_activity"]["kinetics"]["Vmax_unit"] == "μM/s"


def test_enzyme_type_enum_string():
    s = get_enzyme_type_enum_string()
    assert "peroxidase-like" in s
    assert "oxidase-like" in s


def test_application_type_enum_string():
    s = get_application_type_enum_string()
    assert "sensing" in s
    assert "therapeutic" in s
