"""Simulated source systems.

Each simulated system is a JSON feed under seed_data/. In a real deployment
these functions would be replaced by adapters calling nCino / Loan IQ
interfaces; nothing downstream of fetch_loan_payloads() would change.
"""

import json
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.integration.vocab import SourceSystem

SOURCE_FEED_FILES: dict[SourceSystem, str] = {
    SourceSystem.NCINO_SIM: "upstream_ncino_sim.json",
    SourceSystem.LOANIQ_SIM: "downstream_loaniq_sim.json",
}


class MockSourceError(Exception):
    """The simulated feed file is missing or malformed."""


def read_source_feed(source_system: SourceSystem, seed_dir: Path | None = None) -> dict[str, Any]:
    folder = seed_dir or get_settings().seed_data_dir
    path = folder / SOURCE_FEED_FILES[source_system]
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MockSourceError(f"Feed file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise MockSourceError(f"Feed file is not valid JSON: {path} ({exc})") from exc

    if not isinstance(document, dict) or not isinstance(document.get("records"), list):
        raise MockSourceError(f"Feed file must be an object with a 'records' list: {path}")
    return document


def fetch_loan_payloads(source_system: SourceSystem, seed_dir: Path | None = None) -> list[Any]:
    """Return the raw loan payloads published by a simulated source system."""
    return read_source_feed(source_system, seed_dir)["records"]
