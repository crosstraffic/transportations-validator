"""Coverage/abstention reporting on semantic validation results."""

from transportations_validator.validators import semantic


def test_covered_when_every_supplied_param_is_checked():
    result = semantic.validate_highway({
        "lane_width": 11.0,
        "shoulder_width": 6.0,
        "segments": [{"passing_type": 0, "spl": 50, "grade": 2.0, "phf": 0.95, "phv": 5.0}],
    })
    assert result.is_valid
    assert result.params_supplied == 7
    assert result.constraints_checked == 7
    assert result.coverage == "covered"
    assert result.abstained is False


def test_partial_when_a_param_has_no_rule():
    result = semantic.validate_highway({
        "lane_width": 11.0,
        "apd": 12.0,
        "segments": [],
    })
    assert result.coverage == "partial"
    assert result.abstained is False


def test_none_when_no_rule_fires():
    result = semantic.validate_highway({"apd": 12.0, "segments": []})
    assert result.constraints_checked == 0
    assert result.coverage == "none"
    assert result.abstained is True
    assert result.is_valid  # vacuously valid, which is exactly why abstained must be surfaced


def test_flat_validate_reports_coverage_too():
    result = semantic.validate({"lane_width": 11.0})
    assert result.coverage == "covered"
    d = result.to_dict()
    assert d["coverage"] == "covered"
    assert d["abstained"] is False
