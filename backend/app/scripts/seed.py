"""Load synthetic reference data and ingest the simulated source feeds.

Usage (from the backend/ folder, virtual environment active):
    python -m app.scripts.seed            # create tables if needed, load/refresh data
    python -m app.scripts.seed --reset    # DROP all tables first, then load

Re-running without --reset is safe: reference data is replaced, and loan
records that have not changed are reported as UNCHANGED or STALE rather than
duplicated.
"""

import argparse
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import SessionLocal, init_db, reset_db
from app.integration.ingestion import IngestionSummary, ingest_payloads
from app.integration.sources import fetch_loan_payloads
from app.integration.vocab import SourceSystem
from app.reference.loader import load_reference_data


@dataclass
class SeedReport:
    reference_counts: dict[str, int]
    ingestion: list[IngestionSummary]


def run_seed(session: Session, seed_dir: Path, trigger: str = "seed") -> SeedReport:
    reference_counts = load_reference_data(session, seed_dir)
    summaries = [
        ingest_payloads(session, system, fetch_loan_payloads(system, seed_dir), trigger=trigger)
        for system in SourceSystem
    ]
    return SeedReport(reference_counts=reference_counts, ingestion=summaries)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the LoanOps Intelligence database (synthetic data).")
    parser.add_argument("--reset", action="store_true", help="drop and recreate all tables first")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.reset:
        reset_db()
        print("Tables dropped and recreated.")
    else:
        init_db()

    with SessionLocal() as session:
        report = run_seed(session, settings.seed_data_dir)

    print(f"Database: {settings.database_url}")
    print("Reference data loaded:")
    for name, count in report.reference_counts.items():
        print(f"  {name:<24}{count}")
    print("Source ingestion:")
    for s in report.ingestion:
        print(
            f"  {s.source_system.value:<11} received={s.received} created={s.created} "
            f"unchanged={s.unchanged} stale={s.stale} rejected={s.rejected}"
        )
        for rejection in s.rejections:
            print(f"      rejected #{rejection['position']}: {rejection['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
