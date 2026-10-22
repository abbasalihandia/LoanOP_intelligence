"""Simulated source-system endpoints.

These stand in for the upstream (nCino-style) and downstream (Loan IQ-style)
interfaces. They return raw payloads exactly as the simulated systems would
publish them, before any normalization. SYNTHETIC DATA ONLY.
"""

from fastapi import APIRouter, HTTPException

from app.integration.sources import MockSourceError, read_source_feed
from app.integration.vocab import SourceSystem
from app.schemas import MockFeedOut

router = APIRouter(prefix="/api/mock", tags=["simulated source systems"])


def _feed(system: SourceSystem) -> MockFeedOut:
    try:
        document = read_source_feed(system)
    except MockSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return MockFeedOut(
        source_system=system.value,
        simulated=True,
        description=str(document.get("description", "")),
        records=document["records"],
    )


@router.get("/ncino/loans", response_model=MockFeedOut, summary="Simulated nCino loan feed")
def ncino_loans() -> MockFeedOut:
    return _feed(SourceSystem.NCINO_SIM)


@router.get("/loaniq/loans", response_model=MockFeedOut, summary="Simulated Loan IQ loan feed")
def loaniq_loans() -> MockFeedOut:
    return _feed(SourceSystem.LOANIQ_SIM)
