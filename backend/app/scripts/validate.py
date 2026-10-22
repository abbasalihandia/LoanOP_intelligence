"""Run deterministic validation and print the resulting exceptions.

Usage (from the backend/ folder, virtual environment active):
    python -m app.scripts.validate
"""

from sqlalchemy import select

from app.db.models import ExceptionRecord
from app.db.session import SessionLocal, init_db
from app.validation.config import get_validation_config
from app.validation.runner import run_validation


def main() -> int:
    init_db()
    config = get_validation_config()
    with SessionLocal() as session:
        run = run_validation(session, config)
        print(f"Validation run {run.run_id}")
        print(f"  config sha256   {run.config_fingerprint[:12]}...")
        print(
            f"  loans={run.loans_evaluated} findings={run.findings} created={run.created} "
            f"redetected={run.redetected} suppressed={run.suppressed} "
            f"no_longer_detected={run.no_longer_detected}"
        )

        rows = session.scalars(select(ExceptionRecord).order_by(ExceptionRecord.id)).all()
        print(f"\nExceptions ({len(rows)}):")
        print(f"  {'ID':<10} {'LOAN':<8} {'RULE':<17} {'SEVERITY':<9} {'STATUS':<20} DETECTED")
        for r in rows:
            print(
                f"  {r.exception_id:<10} {r.loan_id:<8} {r.rule_id:<17} {r.severity:<9} "
                f"{r.status:<20} {'yes' if r.still_detected else 'no'}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
