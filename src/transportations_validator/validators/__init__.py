"""
Validation and reasoning module for transportation engineering inputs.

Core validation (always available, zero dependencies):
    from transportations_validator.validators import semantic
    from transportations_validator.validators import validate, validate_highway

Forward-chaining reasoning over AFFECTS edges (zero dependencies):
    from transportations_validator.validators import forward_chain

Full validation engine (requires [api] extras):
    from transportations_validator.validators import ValidationEngine
"""

# Always available - semantic validation with zero dependencies
# Re-export semantic module for convenient access
from transportations_validator.validators import derivation, forward_chain, semantic
from transportations_validator.validators.derivation import (
    DerivationClosureResult,
    DerivationStep,
    GateVerdict,
    LLMClient,
    ProposedDerivation,
    StubLLMClient,
    derive_downstream_values,
    verify_proposal,
)
from transportations_validator.validators.forward_chain import (
    BackwardChainResult,
    ChainStep,
    ForwardChainResult,
    backward_chain,
    load_relationships_from_seed,
)
from transportations_validator.validators.semantic import (
    SPEED_RADIUS_TABLE,
    Severity,
    ValidationResult,
    Violation,
    validate,
    validate_grade,
    validate_highway,
    validate_horizontal_class,
    validate_lane_width,
    validate_passing_type,
    validate_phf,
    validate_phv,
    validate_shoulder_width,
    validate_speed_limit,
    validate_speed_radius,
    validate_vertical_class,
)

__all__ = [
    # Semantic module
    "semantic",
    # Forward-chaining reasoning module
    "forward_chain",
    # LLM-mediated derivation closure module
    "derivation",
    # Core types
    "Severity",
    "Violation",
    "ValidationResult",
    "ChainStep",
    "ForwardChainResult",
    "BackwardChainResult",
    # High-level validators
    "validate",
    "validate_highway",
    # Individual validators
    "validate_lane_width",
    "validate_shoulder_width",
    "validate_horizontal_class",
    "validate_passing_type",
    "validate_speed_radius",
    "validate_vertical_class",
    "validate_grade",
    "validate_phf",
    "validate_phv",
    "validate_speed_limit",
    # Chain-reasoning helpers
    "backward_chain",
    "load_relationships_from_seed",
    # Derivation closure types and helpers
    "ProposedDerivation",
    "GateVerdict",
    "DerivationStep",
    "DerivationClosureResult",
    "LLMClient",
    "StubLLMClient",
    "verify_proposal",
    "derive_downstream_values",
    # Constants
    "SPEED_RADIUS_TABLE",
]


# Optional imports - only available with [api] extras
# These require database dependencies (SQLAlchemy, asyncpg, neo4j, etc.)
def _try_import_api_modules():
    """Lazily import API modules only when explicitly requested."""
    try:
        from transportations_validator.validators.engine import ValidationEngine
        from transportations_validator.validators.formula import FormulaError, FormulaEvaluator

        return ValidationEngine, FormulaEvaluator, FormulaError
    except (ImportError, Exception):
        # API dependencies not installed or config error - that's fine for lightweight usage
        return None, None, None


# Don't import at module level to avoid triggering database config
# Users who need ValidationEngine should import it explicitly:
#   from transportations_validator.validators.engine import ValidationEngine
