"""Rule-based severity assignment (configurable, deterministic)."""

from decimal import Decimal, InvalidOperation

from app.validation.config import SEVERITY_ORDER, ValidationConfig
from app.validation.model import Finding


def _rank(severity: str) -> int:
    return SEVERITY_ORDER.index(severity)


def assign_severity(finding: Finding, config: ValidationConfig) -> str:
    """Base severity for the rule, raised by any matching override (never lowered)."""
    severity = config.base_severity.get(finding.rule_id, config.default_severity)
    metrics = finding.details.get("metrics", {})

    for override in config.overrides:
        if override.rule_id != finding.rule_id or override.metric not in metrics:
            continue
        try:
            value = Decimal(str(metrics[override.metric]))
        except InvalidOperation:
            continue
        if value >= override.gte and _rank(override.severity) > _rank(severity):
            severity = override.severity
    return severity
