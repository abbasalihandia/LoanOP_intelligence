"""Run deterministic validation and inspect the rule catalogue."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ValidationRun
from app.db.session import get_db
from app.validation.config import ValidationConfigError, get_validation_config
from app.validation.rules import RULES
from app.validation.runner import run_validation
from app.schemas import RuleOut, SeverityOverrideOut, ValidationRunOut

router = APIRouter(prefix="/api/validation", tags=["validation"])


def _config():
    try:
        return get_validation_config()
    except ValidationConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/run", response_model=ValidationRunOut, summary="Validate all current loan records")
def run(db: Session = Depends(get_db)) -> ValidationRunOut:
    return ValidationRunOut.model_validate(run_validation(db, _config()))


@router.get("/runs", response_model=list[ValidationRunOut], summary="Recent validation runs")
def list_runs(limit: int = Query(20, ge=1, le=200), db: Session = Depends(get_db)) -> list[ValidationRunOut]:
    runs = db.scalars(select(ValidationRun).order_by(ValidationRun.id.desc()).limit(limit)).all()
    return [ValidationRunOut.model_validate(r) for r in runs]


@router.get("/rules", response_model=list[RuleOut], summary="Rule catalogue with configured severity")
def list_rules() -> list[RuleOut]:
    config = _config()
    return [
        RuleOut(
            rule_id=spec.rule_id,
            category=spec.category,
            title=spec.title,
            description=spec.description,
            base_severity=config.base_severity.get(spec.rule_id, config.default_severity),
            severity_overrides=[
                SeverityOverrideOut(metric=o.metric, gte=format(o.gte, "f"), severity=o.severity)
                for o in config.overrides
                if o.rule_id == spec.rule_id
            ],
        )
        for spec in RULES.values()
    ]
