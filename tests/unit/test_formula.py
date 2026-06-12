"""Tests for the formula evaluator."""

import pytest

from transportations_validator.validators.formula import FormulaError, FormulaEvaluator


class TestFormulaEvaluator:
    """Test cases for FormulaEvaluator."""

    @pytest.fixture
    def evaluator(self):
        return FormulaEvaluator()

    # Basic arithmetic tests
    def test_simple_addition(self, evaluator):
        assert evaluator.evaluate("a + b > 10", {"a": 5, "b": 6}) is True
        assert evaluator.evaluate("a + b > 10", {"a": 5, "b": 4}) is False

    def test_multiplication(self, evaluator):
        assert evaluator.evaluate("a * b == 20", {"a": 4, "b": 5}) is True

    def test_division(self, evaluator):
        assert evaluator.evaluate("a / b < 1", {"a": 3, "b": 4}) is True

    def test_power(self, evaluator):
        assert evaluator.evaluate("a ** 2 == 16", {"a": 4}) is True

    # Comparison tests
    def test_greater_than(self, evaluator):
        assert evaluator.evaluate("speed >= 55", {"speed": 55}) is True
        assert evaluator.evaluate("speed >= 55", {"speed": 54}) is False

    def test_less_than(self, evaluator):
        assert evaluator.evaluate("grade <= 8", {"grade": 8}) is True
        assert evaluator.evaluate("grade <= 8", {"grade": 9}) is False

    def test_equality(self, evaluator):
        assert evaluator.evaluate("lanes == 4", {"lanes": 4}) is True
        assert evaluator.evaluate("lanes != 4", {"lanes": 3}) is True

    # Cross-parameter tests
    def test_cross_param_sum(self, evaluator):
        params = {"lane_width": 12, "shoulder_width": 4}
        assert evaluator.evaluate("lane_width + shoulder_width >= 14", params) is True

    def test_cross_param_comparison(self, evaluator):
        params = {"design_speed": 70, "speed_limit": 65}
        assert evaluator.evaluate("design_speed >= speed_limit + 5", params) is True
        assert evaluator.evaluate("design_speed >= speed_limit + 10", params) is False

    # Function tests
    def test_sqrt(self, evaluator):
        assert evaluator.evaluate("sqrt(a) < 5", {"a": 16}) is True
        assert evaluator.evaluate("sqrt(a) == 4", {"a": 16}) is True

    def test_min_max(self, evaluator):
        assert evaluator.evaluate("min(a, b) == 3", {"a": 3, "b": 5}) is True
        assert evaluator.evaluate("max(a, b) == 5", {"a": 3, "b": 5}) is True

    def test_abs(self, evaluator):
        assert evaluator.evaluate("abs(a) == 5", {"a": -5}) is True

    def test_pow(self, evaluator):
        assert evaluator.evaluate("pow(a, 2) == 9", {"a": 3}) is True

    def test_round(self, evaluator):
        assert evaluator.evaluate("round(a) == 4", {"a": 3.7}) is True

    def test_floor_ceil(self, evaluator):
        assert evaluator.evaluate("floor(a) == 3", {"a": 3.7}) is True
        assert evaluator.evaluate("ceil(a) == 4", {"a": 3.2}) is True

    # Logic tests
    def test_and(self, evaluator):
        params = {"a": 5, "b": 10}
        assert evaluator.evaluate("a > 3 and b > 8", params) is True
        assert evaluator.evaluate("a > 3 and b > 12", params) is False

    def test_or(self, evaluator):
        params = {"a": 5, "b": 10}
        assert evaluator.evaluate("a > 10 or b > 8", params) is True
        assert evaluator.evaluate("a > 10 or b > 12", params) is False

    def test_not(self, evaluator):
        assert evaluator.evaluate("not a > 10", {"a": 5}) is True

    # Transportation-specific formula tests
    def test_stopping_sight_distance(self, evaluator):
        """Test simplified stopping sight distance formula."""
        params = {
            "ssd": 500,
            "design_speed": 60,
            "grade": 0,
        }
        # Simplified SSD formula: ssd >= 1.47 * speed * 2.5 + speed^2 / (30 * 0.35)
        # 1.47 * 60 * 2.5 + 3600 / 10.5 = 220.5 + 342.86 = 563.36
        formula = "ssd >= 1.47 * design_speed * 2.5 + pow(design_speed, 2) / (30 * 0.35)"
        assert evaluator.evaluate(formula, params) is False  # 500 < 563

        params["ssd"] = 600
        assert evaluator.evaluate(formula, params) is True  # 600 > 563

    def test_lane_count_balance(self, evaluator):
        """Test lane balance at diverge."""
        params = {
            "lanes_before": 4,
            "lanes_after": 3,
            "ramp_lanes": 1,
        }
        formula = "lanes_after == lanes_before - 1 + ramp_lanes"
        assert evaluator.evaluate(formula, params) is False  # 3 != 4 - 1 + 1 = 4

        params["ramp_lanes"] = 0
        assert evaluator.evaluate(formula, params) is True  # 3 == 4 - 1 + 0 = 3

    # Syntax normalization tests
    def test_dollar_syntax(self, evaluator):
        """Test ${param} syntax normalization."""
        assert evaluator.evaluate("${a} + ${b} > 10", {"a": 5, "b": 6}) is True

    def test_hyphen_normalization(self, evaluator):
        """Test parameter names with hyphens."""
        params = {"lane_width": 12}
        assert evaluator.evaluate("lane_width >= 10", params) is True

    # Parameter extraction tests
    def test_extract_parameters(self, evaluator):
        formula = "design_speed >= speed_limit + 5 and lane_width > 10"
        params = evaluator.extract_parameters(formula)
        assert params == {"design_speed", "speed_limit", "lane_width"}

    def test_extract_ignores_functions(self, evaluator):
        formula = "sqrt(lane_width) > min(a, b)"
        params = evaluator.extract_parameters(formula)
        assert "sqrt" not in params
        assert "min" not in params
        assert params == {"lane_width", "a", "b"}

    # Error handling tests
    def test_empty_formula(self, evaluator):
        with pytest.raises(FormulaError, match="Empty formula"):
            evaluator.evaluate("", {"a": 1})

    def test_invalid_formula(self, evaluator):
        with pytest.raises(FormulaError):
            evaluator.evaluate("a @ b", {"a": 1, "b": 2})  # @ operator not supported

    def test_missing_parameter(self, evaluator):
        """Missing parameters should raise an error."""
        with pytest.raises(FormulaError):
            evaluator.evaluate("a + b > 10", {"a": 5})  # b is missing

    def test_formula_too_long(self, evaluator):
        long_formula = "a + " * 300 + "a > 0"
        with pytest.raises(FormulaError, match="exceeds max length"):
            evaluator.evaluate(long_formula, {"a": 1})

    # Validation tests
    def test_validate_formula_empty(self, evaluator):
        errors = evaluator.validate_formula("")
        assert "empty" in errors[0].lower()

    def test_validate_formula_dangerous(self, evaluator):
        errors = evaluator.validate_formula("__import__('os')")
        assert len(errors) > 0

    def test_validate_formula_valid(self, evaluator):
        errors = evaluator.validate_formula("a + b > 10")
        assert errors == []

    # Dict value handling tests
    def test_handles_dict_values(self, evaluator):
        """Test that param dicts with 'value' key are unwrapped."""
        params = {
            "a": {"value": 5, "unit": "ft"},
            "b": {"value": 6, "unit": "ft"},
        }
        # The evaluator normalizes these in _normalize_params
        normalized = evaluator._normalize_params(params)
        assert normalized["a"] == 5
        assert normalized["b"] == 6

    def test_skips_none_values(self, evaluator):
        """Test that None values are skipped."""
        params = {"a": 5, "b": None}
        normalized = evaluator._normalize_params(params)
        assert "a" in normalized
        assert "b" not in normalized


class TestImpliesConnective:
    """The rule corpus writes conditionals as 'a implies b'; without the
    desugaring these rules raised FormulaError and silently never fired."""

    def setup_method(self):
        from transportations_validator.validators.formula import FormulaEvaluator

        self.evaluator = FormulaEvaluator()

    def test_implies_true_antecedent_violated(self):
        # curvature in class-0 band but hor_class says otherwise -> False
        assert (
            self.evaluator.evaluate(
                "curvature < 0.000128 implies hor_class == 0",
                {"curvature": 0.0001, "hor_class": 2},
            )
            is False
        )

    def test_implies_true_antecedent_satisfied(self):
        assert (
            self.evaluator.evaluate(
                "curvature < 0.000128 implies hor_class == 0",
                {"curvature": 0.0001, "hor_class": 0},
            )
            is True
        )

    def test_implies_false_antecedent_vacuously_true(self):
        assert (
            self.evaluator.evaluate(
                "curvature < 0.000128 implies hor_class == 0",
                {"curvature": 0.5, "hor_class": 4},
            )
            is True
        )

    def test_implies_chain_right_associative(self):
        # a implies (b implies c): a=True, b=True, c=False -> False
        assert (
            self.evaluator.evaluate(
                "a == 1 implies b == 1 implies c == 1",
                {"a": 1, "b": 1, "c": 0},
            )
            is False
        )

    def test_implies_not_extracted_as_parameter(self):
        refs = self.evaluator.extract_parameters(
            "curvature < 0.000128 implies hor_class == 0"
        )
        assert refs == {"curvature", "hor_class"}
