"""Core validation engine orchestrator."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from transportations_validator.extractors.base import ExtractionResult
from transportations_validator.extractors import RustLibExtractor, JSONExtractor, LLMResponseExtractor
from transportations_validator.models.validation import (
    SourceType,
    ValidationContext,
    ValidationResult,
    ParameterValidation,
    RuleViolation,
)
from transportations_validator.models.rule import RuleType, Severity
from transportations_validator.models.parameter import FacilityType
from transportations_validator.db.postgres.repositories import ParameterRepository, RuleRepository
from transportations_validator.validators.resolvers.condition import ConditionResolver
from transportations_validator.validators.resolvers.jurisdiction import JurisdictionResolver


class ValidationEngine:
    """Core validation engine that orchestrates the validation process."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.param_repo = ParameterRepository(session)
        self.rule_repo = RuleRepository(session)
        self.condition_resolver = ConditionResolver(session)
        self.jurisdiction_resolver = JurisdictionResolver(session)

        # Initialize extractors
        self.extractors = [
            RustLibExtractor(),
            JSONExtractor(),
            LLMResponseExtractor(),
        ]

    async def validate(
        self,
        data: Any,
        source_type: SourceType | None = None,
        context: ValidationContext | None = None,
        strict: bool = False,
    ) -> tuple[ValidationResult, ExtractionResult]:
        """Validate data against rules."""
        # Extract parameters
        extraction = self._extract(data, source_type)

        if not extraction.success:
            return ValidationResult(
                is_valid=False,
                error_count=len(extraction.errors),
                warning_count=0,
                parameters=[],
            ), extraction

        # Merge provided context with extracted context
        merged_context = self._merge_context(context, extraction.context)

        # Validate each parameter
        param_validations = []
        total_errors = 0
        total_warnings = 0

        for param_key, param_data in extraction.parameters.items():
            # Skip nested segment data for now (handle separately)
            if param_key.startswith("segment_"):
                continue

            validation = await self._validate_parameter(
                param_key,
                param_data,
                extraction.facility_type,
                merged_context,
            )

            if validation:
                param_validations.append(validation)
                total_errors += len(validation.violations)
                total_warnings += len(validation.warnings)

        # Determine overall validity
        is_valid = total_errors == 0
        if strict:
            is_valid = is_valid and total_warnings == 0

        return ValidationResult(
            is_valid=is_valid,
            error_count=total_errors,
            warning_count=total_warnings,
            parameters=param_validations,
        ), extraction

    def _extract(
        self, data: Any, source_type: SourceType | None = None
    ) -> ExtractionResult:
        """Extract parameters from data using appropriate extractor."""
        if source_type:
            # Use specific extractor
            for extractor in self.extractors:
                if extractor.source_type == source_type:
                    return extractor.extract(data)

        # Auto-detect extractor
        for extractor in self.extractors:
            if extractor.can_extract(data):
                return extractor.extract(data)

        # Fallback to JSON extractor for dict data
        if isinstance(data, dict):
            return JSONExtractor().extract(data)

        return ExtractionResult(
            source_type=SourceType.UNKNOWN,
            errors=["Could not determine data source type"],
        )

    def _merge_context(
        self,
        provided: ValidationContext | None,
        extracted: ValidationContext | None,
    ) -> dict[str, Any]:
        """Merge provided context with extracted context."""
        context: dict[str, Any] = {}

        if extracted:
            context.update(extracted.model_dump(exclude_none=True))

        if provided:
            # Provided context overrides extracted
            context.update(provided.model_dump(exclude_none=True))

        return context

    async def _validate_parameter(
        self,
        param_key: str,
        param_data: dict[str, Any],
        facility_type: str | None,
        context: dict[str, Any],
    ) -> ParameterValidation | None:
        """Validate a single parameter against applicable rules."""
        value = param_data.get("value")
        if value is None:
            return None

        # Resolve parameter from database
        ft = None
        if facility_type:
            try:
                ft = FacilityType(facility_type)
            except ValueError:
                pass

        param = await self.param_repo.resolve_parameter_name(param_key, ft)

        if not param:
            # Parameter not in database, can't validate
            return ParameterValidation(
                parameter_name=param_data.get("name", param_key),
                rust_field=param_key,
                value=value,
                is_valid=True,
                violations=[],
                warnings=[],
            )

        # Get applicable rules
        rules = await self.rule_repo.get_rules_for_context(param.id, context)

        # Apply jurisdiction resolver to prioritize rules
        rules = await self.jurisdiction_resolver.prioritize_rules(
            rules, context.get("jurisdiction")
        )

        # Validate against each rule
        violations: list[RuleViolation] = []
        warnings: list[RuleViolation] = []

        for rule in rules:
            violation = self._check_rule(rule, value)
            if violation:
                if rule.severity == Severity.ERROR:
                    violations.append(violation)
                else:
                    warnings.append(violation)

        return ParameterValidation(
            parameter_name=param.name,
            rust_field=param.rust_field,
            value=value,
            is_valid=len(violations) == 0,
            violations=violations,
            warnings=warnings,
        )

    def _check_rule(self, rule: Any, value: Any) -> RuleViolation | None:
        """Check if a value violates a rule."""
        try:
            if rule.rule_type == RuleType.RANGE:
                return self._check_range(rule, value)
            elif rule.rule_type == RuleType.MIN:
                return self._check_min(rule, value)
            elif rule.rule_type == RuleType.MAX:
                return self._check_max(rule, value)
            elif rule.rule_type == RuleType.ENUM:
                return self._check_enum(rule, value)
        except (TypeError, ValueError):
            return None

        return None

    def _check_range(self, rule: Any, value: float) -> RuleViolation | None:
        """Check range constraint."""
        min_val = rule.min_value
        max_val = rule.max_value

        violation = False
        if min_val is not None:
            if rule.min_inclusive:
                violation = value < min_val
            else:
                violation = value <= min_val

        if not violation and max_val is not None:
            if rule.max_inclusive:
                violation = value > max_val
            else:
                violation = value >= max_val

        if violation:
            return RuleViolation(
                rule_id=rule.id,
                rule_name=rule.name,
                severity=rule.severity.value,
                message=rule.error_message or f"Value {value} out of range [{min_val}, {max_val}]",
                expected=f"[{min_val}, {max_val}]",
                actual=str(value),
                citation=self._get_citation(rule),
            )

        return None

    def _check_min(self, rule: Any, value: float) -> RuleViolation | None:
        """Check minimum constraint."""
        min_val = rule.min_value
        if min_val is None:
            return None

        violation = False
        if rule.min_inclusive:
            violation = value < min_val
        else:
            violation = value <= min_val

        if violation:
            return RuleViolation(
                rule_id=rule.id,
                rule_name=rule.name,
                severity=rule.severity.value,
                message=rule.error_message or f"Value {value} below minimum {min_val}",
                expected=f">= {min_val}" if rule.min_inclusive else f"> {min_val}",
                actual=str(value),
                citation=self._get_citation(rule),
            )

        return None

    def _check_max(self, rule: Any, value: float) -> RuleViolation | None:
        """Check maximum constraint."""
        max_val = rule.max_value
        if max_val is None:
            return None

        violation = False
        if rule.max_inclusive:
            violation = value > max_val
        else:
            violation = value >= max_val

        if violation:
            return RuleViolation(
                rule_id=rule.id,
                rule_name=rule.name,
                severity=rule.severity.value,
                message=rule.error_message or f"Value {value} exceeds maximum {max_val}",
                expected=f"<= {max_val}" if rule.max_inclusive else f"< {max_val}",
                actual=str(value),
                citation=self._get_citation(rule),
            )

        return None

    def _check_enum(self, rule: Any, value: Any) -> RuleViolation | None:
        """Check enum constraint."""
        if not rule.allowed_values:
            return None

        allowed = [v.strip() for v in rule.allowed_values.split(",")]
        str_value = str(value)

        if str_value not in allowed:
            return RuleViolation(
                rule_id=rule.id,
                rule_name=rule.name,
                severity=rule.severity.value,
                message=rule.error_message or f"Value '{value}' not in allowed values",
                expected=f"One of: {', '.join(allowed)}",
                actual=str_value,
                citation=self._get_citation(rule),
            )

        return None

    def _get_citation(self, rule: Any) -> str | None:
        """Get citation string from rule sources."""
        if not hasattr(rule, "sources") or not rule.sources:
            return None

        # Get primary source if available
        for src in rule.sources:
            if src.is_primary and hasattr(src, "source_ref"):
                return src.source_ref.citation

        # Otherwise use first source
        if rule.sources and hasattr(rule.sources[0], "source_ref"):
            return rule.sources[0].source_ref.citation

        return None
