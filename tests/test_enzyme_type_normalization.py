import pytest
from nanozyme_models import EnzymeType


class TestEnzymeTypeNormalization:

    ALIAS_CASES = [
        ("peroxidase-like", "peroxidase-like"),
        ("peroxidase_like", "peroxidase-like"),
        ("peroxidase like", "peroxidase-like"),
        ("pod-like", "peroxidase-like"),
        ("pod_like", "peroxidase-like"),
        ("POD-like", "peroxidase-like"),
        ("peroxidase (pod)-like", "peroxidase-like"),
        ("oxidase-like", "oxidase-like"),
        ("oxidase_like", "oxidase-like"),
        ("oxidase like", "oxidase-like"),
        ("oxd-like", "oxidase-like"),
        ("oxd_like", "oxidase-like"),
        ("OXD-like", "oxidase-like"),
        ("oxidase (oxd)-like", "oxidase-like"),
        ("catalase-like", "catalase-like"),
        ("catalase_like", "catalase-like"),
        ("catalase like", "catalase-like"),
        ("cat-like", "catalase-like"),
        ("cat_like", "catalase-like"),
        ("CAT-like", "catalase-like"),
        ("catalase (cat)-like", "catalase-like"),
        ("superoxide-dismutase-like", "superoxide-dismutase-like"),
        ("superoxide_dismutase_like", "superoxide-dismutase-like"),
        ("sod-like", "superoxide-dismutase-like"),
        ("sod_like", "superoxide-dismutase-like"),
        ("SOD-like", "superoxide-dismutase-like"),
        ("superoxide dismutase (sod)-like", "superoxide-dismutase-like"),
        ("glucose-oxidase-like", "glucose-oxidase-like"),
        ("glucose_oxidase_like", "glucose-oxidase-like"),
        ("gox-like", "glucose-oxidase-like"),
        ("gox_like", "glucose-oxidase-like"),
        ("GOx-like", "glucose-oxidase-like"),
        ("glucose oxidase (gox)-like", "glucose-oxidase-like"),
        ("glutathione-peroxidase-like", "glutathione-peroxidase-like"),
        ("glutathione_peroxidase_like", "glutathione-peroxidase-like"),
        ("gpx-like", "glutathione-peroxidase-like"),
        ("gpx_like", "glutathione-peroxidase-like"),
        ("GPx-like", "glutathione-peroxidase-like"),
        ("glutathione peroxidase (gpx)-like", "glutathione-peroxidase-like"),
        ("glutathione-oxidase-like", "glutathione-oxidase-like"),
        ("glutathione_oxidase_like", "glutathione-oxidase-like"),
        ("gshox-like", "glutathione-oxidase-like"),
        ("gshox_like", "glutathione-oxidase-like"),
        ("glutathione oxidase (gshox)-like", "glutathione-oxidase-like"),
        ("laccase-like", "laccase-like"),
        ("laccase_like", "laccase-like"),
        ("laccase like", "laccase-like"),
        ("phosphatase-like", "phosphatase-like"),
        ("phosphatase_like", "phosphatase-like"),
        ("alp-like", "phosphatase-like"),
        ("alp_like", "phosphatase-like"),
        ("ALP-like", "phosphatase-like"),
        ("phosphatase (alp)-like", "phosphatase-like"),
        ("esterase-like", "esterase-like"),
        ("esterase_like", "esterase-like"),
        ("esterase like", "esterase-like"),
        ("nuclease-like", "nuclease-like"),
        ("nuclease_like", "nuclease-like"),
        ("nuclease like", "nuclease-like"),
        ("nitroreductase-like", "nitroreductase-like"),
        ("nitroreductase_like", "nitroreductase-like"),
        ("ntr-like", "nitroreductase-like"),
        ("ntr_like", "nitroreductase-like"),
        ("NTR-like", "nitroreductase-like"),
        ("nitroreductase (ntr)-like", "nitroreductase-like"),
        ("hydrolase-like", "hydrolase-like"),
        ("hydrolase_like", "hydrolase-like"),
        ("hydrolase like", "hydrolase-like"),
        ("haloperoxidase-like", "haloperoxidase-like"),
        ("haloperoxidase_like", "haloperoxidase-like"),
        ("vhpo-like", "haloperoxidase-like"),
        ("tyrosinase-like", "tyrosinase-like"),
        ("tyrosinase_like", "tyrosinase-like"),
        ("cascade-enzymatic", "cascade-enzymatic"),
        ("cascade_enzymatic", "cascade-enzymatic"),
    ]

    @pytest.mark.parametrize("raw,expected", ALIAS_CASES)
    def test_normalize_canonical(self, raw, expected):
        result = EnzymeType.normalize_canonical(raw)
        assert result == expected, f"normalize_canonical({raw!r}) = {result!r}, expected {expected!r}"

    def test_normalize_canonical_empty_string(self):
        assert EnzymeType.normalize_canonical("") == ""

    def test_normalize_canonical_none(self):
        assert EnzymeType.normalize_canonical(None) is None

    def test_normalize_canonical_unknown_type(self):
        result = EnzymeType.normalize_canonical("some-unknown-type")
        assert result == "some-unknown-type"

    def test_normalize_canonical_case_insensitive(self):
        assert EnzymeType.normalize_canonical("PEROXIDASE-LIKE") == "peroxidase-like"
        assert EnzymeType.normalize_canonical("Peroxidase-Like") == "peroxidase-like"

    def test_all_enum_values_self_normalize(self):
        for member in EnzymeType:
            result = EnzymeType.normalize_canonical(member.value)
            assert result == member.value, f"{member.name} value {member.value!r} normalized to {result!r}"

    def test_underscore_variants_all_covered(self):
        underscore_cases = [
            ("peroxidase_like", "peroxidase-like"),
            ("oxidase_like", "oxidase-like"),
            ("catalase_like", "catalase-like"),
            ("superoxide_dismutase_like", "superoxide-dismutase-like"),
            ("glucose_oxidase_like", "glucose-oxidase-like"),
            ("glutathione_peroxidase_like", "glutathione-peroxidase-like"),
            ("glutathione_oxidase_like", "glutathione-oxidase-like"),
            ("laccase_like", "laccase-like"),
            ("phosphatase_like", "phosphatase-like"),
            ("esterase_like", "esterase-like"),
            ("nuclease_like", "nuclease-like"),
            ("nitroreductase_like", "nitroreductase-like"),
            ("hydrolase_like", "hydrolase-like"),
            ("haloperoxidase_like", "haloperoxidase-like"),
            ("tyrosinase_like", "tyrosinase-like"),
            ("cascade_enzymatic", "cascade-enzymatic"),
        ]
        for raw, expected in underscore_cases:
            result = EnzymeType.normalize_canonical(raw)
            assert result == expected, f"normalize_canonical({raw!r}) = {result!r}, expected {expected!r}"
