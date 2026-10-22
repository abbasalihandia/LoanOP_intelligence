"""Load synthetic reference data from seed_data/ into the database.

Strategy: replace-all. Each load deletes the existing reference rows and
inserts the file contents, so the database always mirrors the seed files.
(Phase 6 will add analyst-confirmed cases with origin != SEED_LEGACY; those
are preserved by deleting only SEED_LEGACY historical cases.)
"""

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models import AgreementClause, HistoricalException, MappingRule

MAPPING_RULES_FILE = "mapping_rules.json"
AGREEMENT_CLAUSES_FILE = "agreement_clauses.json"
HISTORICAL_EXCEPTIONS_FILE = "historical_exceptions.json"


class ReferenceDataError(Exception):
    """A reference seed file is missing, malformed, or has a bad record."""


def _read_records(seed_dir: Path, filename: str) -> list[dict[str, Any]]:
    path = seed_dir / filename
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReferenceDataError(f"Reference file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReferenceDataError(f"Reference file is not valid JSON: {path} ({exc})") from exc

    records = document.get("records") if isinstance(document, dict) else None
    if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
        raise ReferenceDataError(f"{path} must be an object with a 'records' list of objects")
    return records


def _to_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _to_utc_naive(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _build(filename: str, index: int, factory: Any, record: dict[str, Any]) -> Any:
    try:
        return factory(record)
    except (KeyError, ValueError, TypeError) as exc:
        raise ReferenceDataError(f"{filename}, record #{index}: {exc!r}") from exc


def _mapping_rule(r: dict[str, Any]) -> MappingRule:
    return MappingRule(
        rule_id=r["rule_id"],
        mapping_set=r["mapping_set"],
        version=r["version"],
        field_name=r["field_name"],
        source_system=r["source_system"],
        target_system=r["target_system"],
        source_value=r["source_value"],
        target_value=r["target_value"],
        effective_from=date.fromisoformat(r["effective_from"]),
        effective_to=_to_date(r.get("effective_to")),
        status=r["status"],
        notes=r.get("notes"),
    )


def _agreement_clause(r: dict[str, Any]) -> AgreementClause:
    return AgreementClause(
        clause_id=r["clause_id"],
        document_ref=r["document_ref"],
        document_type=r["document_type"],
        facility_id=r.get("facility_id"),
        loan_id=r.get("loan_id"),
        clause_number=r["clause_number"],
        title=r["title"],
        text=r["text"],
        effective_date=_to_date(r.get("effective_date")),
    )


def _historical_exception(r: dict[str, Any]) -> HistoricalException:
    return HistoricalException(
        case_id=r["case_id"],
        loan_id=r["loan_id"],
        category=r["category"],
        field_name=r.get("field_name"),
        source_value=r.get("source_value"),
        target_value=r.get("target_value"),
        description=r["description"],
        confirmed_root_cause=r.get("confirmed_root_cause"),
        resolution=r.get("resolution"),
        outcome=r["outcome"],
        resolved_by=r.get("resolved_by"),
        resolved_at=_to_utc_naive(r.get("resolved_at")),
        keywords=list(r.get("keywords", [])),
        origin="SEED_LEGACY",
    )


def load_reference_data(session: Session, seed_dir: Path) -> dict[str, int]:
    """Replace reference data with the seed files. Returns row counts."""
    specs = [
        (MAPPING_RULES_FILE, _mapping_rule),
        (AGREEMENT_CLAUSES_FILE, _agreement_clause),
        (HISTORICAL_EXCEPTIONS_FILE, _historical_exception),
    ]
    # Read and build everything before touching the database, so a bad file
    # leaves existing data intact.
    built: dict[str, list[Any]] = {}
    for filename, factory in specs:
        records = _read_records(seed_dir, filename)
        built[filename] = [_build(filename, i, factory, r) for i, r in enumerate(records)]

    try:
        session.execute(delete(MappingRule))
        session.execute(delete(AgreementClause))
        session.execute(delete(HistoricalException).where(HistoricalException.origin == "SEED_LEGACY"))
        for rows in built.values():
            session.add_all(rows)
        session.commit()
    except Exception:
        session.rollback()
        raise

    return {
        "mapping_rules": len(built[MAPPING_RULES_FILE]),
        "agreement_clauses": len(built[AGREEMENT_CLAUSES_FILE]),
        "historical_exceptions": len(built[HISTORICAL_EXCEPTIONS_FILE]),
    }
