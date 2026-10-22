"""Validation configuration: tolerances, status vocabularies, severity rules.

Loaded from backend/config/validation_rules.json so thresholds can be changed
without code changes. The file's SHA-256 is recorded on every validation run,
so any exception can be traced back to the exact configuration that raised it.
"""

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

SEVERITY_ORDER: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


class ValidationConfigError(Exception):
    """The validation configuration file is missing or invalid."""


@dataclass(frozen=True)
class SeverityOverride:
    rule_id: str
    metric: str
    gte: Decimal
    severity: str


@dataclass(frozen=True)
class ValidationConfig:
    amount_tolerance: Decimal
    maturity_tolerance_days: int
    upstream_approved_statuses: frozenset[str]
    downstream_failed_statuses: frozenset[str]
    default_severity: str
    base_severity: dict[str, str]
    overrides: tuple[SeverityOverride, ...]
    fingerprint: str


def _severity(value: Any, where: str) -> str:
    if value not in SEVERITY_ORDER:
        raise ValidationConfigError(f"{where}: severity must be one of {SEVERITY_ORDER}, got {value!r}")
    return value


def _decimal(value: Any, where: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValidationConfigError(f"{where}: not a number: {value!r}") from exc
    if not result.is_finite() or result < 0:
        raise ValidationConfigError(f"{where}: must be a non-negative number, got {value!r}")
    return result


def parse_validation_config(raw_text: str) -> ValidationConfig:
    from app.validation.rules import RULES  # local import avoids a cycle

    try:
        data = json.loads(raw_text)
        tolerances = data["tolerances"]
        statuses = data["statuses"]
        severity = data["severity"]

        base = {}
        for rule_id, value in severity["by_rule"].items():
            if rule_id not in RULES:
                raise ValidationConfigError(f"severity.by_rule: unknown rule {rule_id!r}")
            base[rule_id] = _severity(value, f"severity.by_rule.{rule_id}")

        overrides = []
        for i, item in enumerate(severity.get("overrides", [])):
            if item["rule_id"] not in RULES:
                raise ValidationConfigError(f"severity.overrides[{i}]: unknown rule {item['rule_id']!r}")
            overrides.append(
                SeverityOverride(
                    rule_id=item["rule_id"],
                    metric=str(item["metric"]),
                    gte=_decimal(item["gte"], f"severity.overrides[{i}].gte"),
                    severity=_severity(item["severity"], f"severity.overrides[{i}].severity"),
                )
            )

        maturity_days = int(tolerances["maturity_days"])
        if maturity_days < 0:
            raise ValidationConfigError("tolerances.maturity_days must be >= 0")

        return ValidationConfig(
            amount_tolerance=_decimal(tolerances["amount_absolute"], "tolerances.amount_absolute"),
            maturity_tolerance_days=maturity_days,
            upstream_approved_statuses=frozenset(s.upper() for s in statuses["upstream_approved"]),
            downstream_failed_statuses=frozenset(s.upper() for s in statuses["downstream_failed"]),
            default_severity=_severity(severity["default"], "severity.default"),
            base_severity=base,
            overrides=tuple(overrides),
            fingerprint=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        )
    except ValidationConfigError:
        raise
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValidationConfigError(f"Invalid validation configuration: {exc!r}") from exc


def load_validation_config(path: Path) -> ValidationConfig:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValidationConfigError(f"Validation config not found: {path}") from exc
    return parse_validation_config(raw_text)


@lru_cache
def get_validation_config() -> ValidationConfig:
    from app.config import get_settings  # local import keeps this module dependency-free

    return load_validation_config(get_settings().validation_config_path)
