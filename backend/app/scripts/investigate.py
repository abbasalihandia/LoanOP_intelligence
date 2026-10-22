"""Run one AI investigation against the real Ollama model and print the report.

Usage (from the backend/ folder, virtual environment active):
    python -m app.scripts.investigate EXC-00001 --by analyst.jdoe
"""

import argparse
import json

from app.ai.client import OllamaClient
from app.ai.service import ExceptionClosed, ExceptionNotFound, InvestigationFailed, investigate_exception
from app.config import get_settings
from app.db.session import SessionLocal, init_db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an AI investigation for one exception.")
    parser.add_argument("exception_id")
    parser.add_argument("--by", default="analyst.cli", help="analyst identifier recorded on the investigation")
    args = parser.parse_args(argv)

    init_db()
    s = get_settings()
    client = OllamaClient(
        s.ollama_base_url, s.ollama_model,
        timeout_seconds=s.ollama_timeout_seconds, temperature=s.ollama_temperature, num_ctx=s.ollama_num_ctx,
    )
    print(f"Investigating {args.exception_id} with {s.ollama_model} (this can take a few minutes on CPU)...")

    with SessionLocal() as session:
        try:
            investigation = investigate_exception(
                session, args.exception_id, requested_by=args.by, client=client, max_attempts=s.ollama_max_attempts
            )
        except (ExceptionNotFound, ExceptionClosed) as exc:
            print(f"ERROR: {exc}")
            return 1
        except InvestigationFailed as exc:
            print(f"FAILED {exc.investigation_id} [{exc.code}]: {exc.message}")
            print(f"Full audit: GET /api/investigations/{exc.investigation_id}")
            return 1

        print(f"SUCCEEDED {investigation.investigation_id}: {investigation.attempts} attempt(s), "
              f"{(investigation.duration_ms or 0) / 1000:.1f}s")
        print(json.dumps(investigation.report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
