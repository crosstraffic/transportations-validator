"""Formula evaluation for cross-parameter validation rules."""

import logging
import math
import re
from typing import Any

from simpleeval import EvalWithCompoundTypes, simple_eval

logger = logging.getLogger(__name__)


class FormulaEvaluator:
    """Safe expression evaluator for formula-based rules.

    Supports:
        - Arithmetic: +, -, *, /, **, %
        - Comparison: <, <=, >, >=, ==, !=
        - Logic: and, or, not
        - Functions: min, max, abs, sqrt, pow, round, floor, ceil
        - Parameter references by name
    """

    SAFE_FUNCTIONS = {
        "min": min,
        "max": max,
        "abs": abs,
        "sqrt": math.sqrt,
        "pow": pow,
        "round": round,
        "floor": math.floor,
        "ceil": math.ceil,
        "log": math.log,
        "log10": math.log10,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
    }

    SAFE_NAMES = {
        "pi": math.pi,
        "e": math.e,
        "true": True,
        "false": False,
        "True": True,
        "False": False,
    }

    # Max formula length to prevent DoS
    MAX_FORMULA_LENGTH = 1000

    def __init__(self) -> None:
        self._evaluator = EvalWithCompoundTypes(
            functions=self.SAFE_FUNCTIONS,
            names=self.SAFE_NAMES.copy(),
        )

    def evaluate(self, formula: str, params: dict[str, Any]) -> bool:
        """Evaluate a formula with given parameter values.

        Args:
            formula: The formula expression to evaluate
            params: Dictionary of parameter names to values

        Returns:
            Boolean result of the formula evaluation

        Raises:
            FormulaError: If formula is invalid or evaluation fails
        """
        if not formula:
            raise FormulaError("Empty formula")

        if len(formula) > self.MAX_FORMULA_LENGTH:
            raise FormulaError(f"Formula exceeds max length of {self.MAX_FORMULA_LENGTH}")

        # Normalize parameter names (convert rust_field names to safe identifiers)
        normalized_params = self._normalize_params(params)

        # Normalize formula (replace ${param} syntax with param)
        normalized_formula = self._normalize_formula(formula)

        try:
            result = simple_eval(
                normalized_formula,
                names={**self.SAFE_NAMES, **normalized_params},
                functions=self.SAFE_FUNCTIONS,
            )
            return bool(result)
        except Exception as e:
            raise FormulaError(f"Formula evaluation failed: {e}") from e

    def validate_formula(self, formula: str) -> list[str]:
        """Validate a formula's syntax without evaluating.

        Args:
            formula: The formula to validate

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        if not formula:
            errors.append("Formula is empty")
            return errors

        if len(formula) > self.MAX_FORMULA_LENGTH:
            errors.append(f"Formula exceeds max length of {self.MAX_FORMULA_LENGTH}")

        # Check for dangerous patterns
        dangerous_patterns = [
            r"__\w+__",  # Dunder methods
            r"\bimport\b",
            r"\bexec\b",
            r"\beval\b",
            r"\bcompile\b",
            r"\bopen\b",
            r"\bfile\b",
            r"\bgetattr\b",
            r"\bsetattr\b",
            r"\bdelattr\b",
            r"\bglobals\b",
            r"\blocals\b",
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, formula, re.IGNORECASE):
                errors.append(f"Formula contains forbidden pattern: {pattern}")

        return errors

    def extract_parameters(self, formula: str) -> set[str]:
        """Extract parameter names referenced in a formula.

        Args:
            formula: The formula to analyze

        Returns:
            Set of parameter names found in the formula
        """
        if not formula:
            return set()

        # Normalize first
        formula = self._normalize_formula(formula)

        # Find all potential variable names
        # Match identifiers that aren't function names or constants
        identifier_pattern = r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b"
        matches = re.findall(identifier_pattern, formula)

        # Filter out known functions and constants
        reserved = set(self.SAFE_FUNCTIONS.keys()) | set(self.SAFE_NAMES.keys())
        reserved |= {"and", "or", "not", "in", "is", "if", "else"}

        return {m for m in matches if m not in reserved}

    def _normalize_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Normalize parameter dictionary for evaluation.

        Converts rust_field style names and handles nested values.
        """
        normalized = {}
        for key, value in params.items():
            # Handle dict values with 'value' key (from extraction)
            if isinstance(value, dict) and "value" in value:
                actual_value = value["value"]
            else:
                actual_value = value

            # Skip None values
            if actual_value is None:
                continue

            # Normalize key (replace hyphens with underscores)
            safe_key = key.replace("-", "_")
            normalized[safe_key] = actual_value

        return normalized

    def _normalize_formula(self, formula: str) -> str:
        """Normalize formula syntax.

        Converts ${param} to param and other normalizations.
        """
        # Replace ${param} with param
        formula = re.sub(r"\$\{(\w+)\}", r"\1", formula)

        # Replace hyphens in identifiers with underscores
        formula = re.sub(r"\b(\w+)-(\w+)\b", r"\1_\2", formula)

        return formula


class FormulaError(Exception):
    """Exception raised when formula evaluation fails."""

    pass
