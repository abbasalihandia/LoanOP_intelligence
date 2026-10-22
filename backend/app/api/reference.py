"""Read-only access to reference data (all synthetic)."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgreementClause, HistoricalException, MappingRule
from app.db.session import get_db
from app.schemas import AgreementClauseOut, HistoricalExceptionOut, MappingRuleOut

router = APIRouter(prefix="/api/reference", tags=["reference data"])


@router.get("/mapping-rules", response_model=list[MappingRuleOut])
def list_mapping_rules(
    mapping_set: str | None = None,
    version: str | None = None,
    source_value: str | None = None,
    db: Session = Depends(get_db),
) -> list[MappingRuleOut]:
    stmt = select(MappingRule)
    if mapping_set:
        stmt = stmt.where(MappingRule.mapping_set == mapping_set)
    if version:
        stmt = stmt.where(MappingRule.version == version)
    if source_value:
        stmt = stmt.where(MappingRule.source_value == source_value)
    rows = db.scalars(stmt.order_by(MappingRule.version, MappingRule.rule_id)).all()
    return [MappingRuleOut.model_validate(r) for r in rows]


@router.get("/clauses", response_model=list[AgreementClauseOut])
def list_clauses(
    loan_id: str | None = None,
    facility_id: str | None = None,
    document_type: str | None = None,
    db: Session = Depends(get_db),
) -> list[AgreementClauseOut]:
    stmt = select(AgreementClause)
    if loan_id:
        stmt = stmt.where(AgreementClause.loan_id == loan_id.strip().upper())
    if facility_id:
        stmt = stmt.where(AgreementClause.facility_id == facility_id.strip().upper())
    if document_type:
        stmt = stmt.where(AgreementClause.document_type == document_type.strip().upper())
    rows = db.scalars(stmt.order_by(AgreementClause.clause_id)).all()
    return [AgreementClauseOut.model_validate(r) for r in rows]


@router.get("/historical-exceptions", response_model=list[HistoricalExceptionOut])
def list_historical_exceptions(
    category: str | None = None,
    loan_id: str | None = None,
    db: Session = Depends(get_db),
) -> list[HistoricalExceptionOut]:
    stmt = select(HistoricalException)
    if category:
        stmt = stmt.where(HistoricalException.category == category.strip().upper())
    if loan_id:
        stmt = stmt.where(HistoricalException.loan_id == loan_id.strip().upper())
    rows = db.scalars(stmt.order_by(HistoricalException.case_id)).all()
    return [HistoricalExceptionOut.model_validate(r) for r in rows]
