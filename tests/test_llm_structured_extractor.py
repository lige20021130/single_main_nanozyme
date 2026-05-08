import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from llm_structured_extractor import LLMStructuredExtractor


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.chat_completion_text = AsyncMock()
    return client


@pytest.fixture
def extractor(mock_client):
    return LLMStructuredExtractor(mock_client)


@pytest.mark.asyncio
async def test_extract_kinetics_multi_substrate(mock_client):
    mock_client.chat_completion_text.return_value = json.dumps({
        "kinetics": {
            "Km": 0.35, "Km_unit": "mM",
            "Vmax": 44.1, "Vmax_unit": "μM/s",
            "kcat": None, "kcat_unit": None,
            "kcat_Km": None, "kcat_Km_unit": None,
            "substrate": "TMB"
        },
        "kinetics_list": [
            {"Km": 0.35, "Km_unit": "mM", "Vmax": 44.1, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "kcat_Km": None, "kcat_Km_unit": None, "substrate": "TMB"},
            {"Km": 0.89, "Km_unit": "mM", "Vmax": 0.079, "Vmax_unit": "μM/s", "kcat": None, "kcat_unit": None, "kcat_Km": None, "kcat_Km_unit": None, "substrate": "H2O2"}
        ]
    })
    ext = LLMStructuredExtractor(mock_client)
    ext.enable_self_augmentation = False
    result = await ext.extract_kinetics("Fe3O4@C", ["Km for TMB was 0.35 mM, Vmax was 4.41e-5 M/s"])
    assert result is not None
    assert result["kinetics"]["substrate"] == "TMB"
    assert len(result["kinetics_list"]) == 2


@pytest.mark.asyncio
async def test_vmax_auto_conversion_m_per_s(mock_client):
    mock_client.chat_completion_text.return_value = json.dumps({
        "kinetics": {
            "Km": 0.5, "Km_unit": "mM",
            "Vmax": 4.41e-05, "Vmax_unit": "M/s",
            "kcat": None, "kcat_unit": None,
            "kcat_Km": None, "kcat_Km_unit": None,
            "substrate": "TMB"
        },
        "kinetics_list": []
    })
    ext = LLMStructuredExtractor(mock_client)
    ext.enable_self_augmentation = False
    result = await ext.extract_kinetics("Fe3O4@C", ["Vmax was 4.41e-05 M/s"])
    assert result["kinetics"]["Vmax_unit"] == "μM/s"
    assert abs(result["kinetics"]["Vmax"] - 44.1) < 0.1


@pytest.mark.asyncio
async def test_vmax_auto_conversion_mM_per_s(mock_client):
    mock_client.chat_completion_text.return_value = json.dumps({
        "kinetics": {
            "Km": 0.5, "Km_unit": "mM",
            "Vmax": 0.0832, "Vmax_unit": "mM/s",
            "kcat": None, "kcat_unit": None,
            "kcat_Km": None, "kcat_Km_unit": None,
            "substrate": "TMB"
        },
        "kinetics_list": []
    })
    ext = LLMStructuredExtractor(mock_client)
    ext.enable_self_augmentation = False
    result = await ext.extract_kinetics("Fe3O4@C", ["Vmax was 0.0832 mM/s"])
    assert result["kinetics"]["Vmax_unit"] == "μM/s"
    assert abs(result["kinetics"]["Vmax"] - 83.2) < 0.1


@pytest.mark.asyncio
async def test_km_unrealistic_molar_clears(mock_client):
    mock_client.chat_completion_text.return_value = json.dumps({
        "kinetics": {
            "Km": 8.0, "Km_unit": "M",
            "Vmax": None, "Vmax_unit": None,
            "kcat": None, "kcat_unit": None,
            "kcat_Km": None, "kcat_Km_unit": None,
            "substrate": None
        },
        "kinetics_list": []
    })
    ext = LLMStructuredExtractor(mock_client)
    ext.enable_self_augmentation = False
    result = await ext.extract_kinetics("Fe3O4", ["Km was 8.0 M"])
    assert result["kinetics"]["Km"] is None


@pytest.mark.asyncio
async def test_km_unrealistic_mM_clears(mock_client):
    mock_client.chat_completion_text.return_value = json.dumps({
        "kinetics": {
            "Km": 1500, "Km_unit": "mM",
            "Vmax": None, "Vmax_unit": None,
            "kcat": None, "kcat_unit": None,
            "kcat_Km": None, "kcat_Km_unit": None,
            "substrate": None
        },
        "kinetics_list": []
    })
    ext = LLMStructuredExtractor(mock_client)
    ext.enable_self_augmentation = False
    result = await ext.extract_kinetics("Fe3O4", ["Km was 1500 mM"])
    assert result["kinetics"]["Km"] is None


@pytest.mark.asyncio
async def test_extract_enzyme_type(mock_client):
    mock_client.chat_completion_text.return_value = json.dumps({
        "enzyme_like_type": "peroxidase-like"
    })
    ext = LLMStructuredExtractor(mock_client)
    result = await ext.extract_enzyme_type("Fe3O4", ["Fe3O4 exhibited peroxidase-like activity"])
    assert result == "peroxidase-like"


@pytest.mark.asyncio
async def test_extract_morphology(mock_client):
    mock_client.chat_completion_text.return_value = json.dumps({
        "morphology": "core-shell spherical",
        "size": 200.0,
        "size_unit": "nm",
        "crystal_structure": None,
        "surface_area": "120.5 m²/g",
        "synthesis_method": "hydrothermal",
        "synthesis_conditions": {"temperature": 180, "time": "12 h", "precursors": ["FeCl3"]},
        "characterization": ["XRD", "TEM"]
    })
    ext = LLMStructuredExtractor(mock_client)
    result = await ext.extract_morphology("Fe3O4@C", ["core-shell structure with 200 nm diameter"])
    assert result["morphology"] == "core-shell spherical"
    assert result["size"] == 200.0


@pytest.mark.asyncio
async def test_extract_applications(mock_client):
    mock_client.chat_completion_text.return_value = json.dumps({
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
    })
    ext = LLMStructuredExtractor(mock_client)
    result = await ext.extract_applications("Fe3O4@C", ["glucose detection with LOD 0.15 μM"])
    assert len(result["applications"]) == 1
    assert result["applications"][0]["target_analyte"] == "glucose"


@pytest.mark.asyncio
async def test_no_client_returns_none(mock_client):
    ext = LLMStructuredExtractor(None)
    result = await ext.extract_kinetics("Fe3O4", ["some text"])
    assert result == {}


def test_parse_json_with_markdown():
    ext = LLMStructuredExtractor(None)
    result = ext._parse_json_response('```json\n{"key": "value"}\n```')
    assert result == {"key": "value"}


def test_parse_json_plain():
    ext = LLMStructuredExtractor(None)
    result = ext._parse_json_response('{"key": "value"}')
    assert result == {"key": "value"}


def test_parse_json_embedded():
    ext = LLMStructuredExtractor(None)
    result = ext._parse_json_response('Here is the result: {"key": "value"} end')
    assert result == {"key": "value"}


def test_parse_json_invalid():
    ext = LLMStructuredExtractor(None)
    result = ext._parse_json_response('This is not JSON at all')
    assert result is None


def test_kinetics_list_vmax_conversion():
    ext = LLMStructuredExtractor(None)
    result = {
        "kinetics": {"Vmax": 1.0, "Vmax_unit": "mM/s"},
        "kinetics_list": [
            {"Vmax": 1e-5, "Vmax_unit": "M/s", "Km": 0.5, "Km_unit": "mM"},
        ]
    }
    fixed = ext._post_process_kinetics(result)
    assert fixed["kinetics_list"][0]["Vmax_unit"] == "μM/s"
    assert abs(fixed["kinetics_list"][0]["Vmax"] - 10.0) < 0.01
