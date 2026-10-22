"""Phase 7: run the end-to-end evaluation against the configured local model.

Usage (from the backend/ folder, virtual environment active, Ollama running):
    python -m app.scripts.evaluate                 # all 11 scenarios (~45-60 min on CPU)
    python -m app.scripts.evaluate --only S01,S04  # a subset
    python -m app.scripts.evaluate --estimate-only # time estimate only, no model calls

Results are stored in the database (evaluation_runs / evaluation_results) and
exported to backend/data/evaluations/<run_id>.json. Exception statuses and
the operational audit trail are not changed.
"""

import argparse
import json

from app.ai.client import OllamaClient, model_is_available
from app.ai.errors import LlmError
from app.config import BACKEND_DIR, get_settings
from app.db.session import SessionLocal, init_db
from app.evaluation.baseline import BaselineModel, summarise_estimates
from app.evaluation.runner import export_run, run_evaluation
from app.evaluation.scenarios import SCENARIOS, scenario_by_id

BASELINE_PATH = BACKEND_DIR / "config" / "manual_baseline_estimates.json"
EXPORT_DIR = BACKEND_DIR / "data" / "evaluations"
CATEGORY_BY_RULE = {
    "RULE-PRODUCT-001": "PRODUCT_MISMATCH", "RULE-MAP-001": "MAPPING_INCONSISTENCY",
    "RULE-MAP-002": "MAPPING_INCONSISTENCY", "RULE-AMT-001": "AMOUNT_MISMATCH", "RULE-CCY-001": "CURRENCY_MISMATCH",
    "RULE-MAT-001": "MATURITY_MISMATCH", "RULE-REQ-001": "MISSING_FIELD", "RULE-BOOK-001": "BOOKING_FAILURE",
    "RULE-BOOK-002": "MISSING_DOWNSTREAM", "RULE-TYPE-001": "DATA_TYPE",
}


def print_estimate(summary: dict, rows: list[tuple[str, str, float, float, float]]) -> None:
    print("\nTIME COMPARISON — ESTIMATE (analyst minutes are assumptions; see config/manual_baseline_estimates.json)")
    print(f"  {'Scenario':<9}{'Category':<24}{'Manual':>8}{'AI-assisted':>13}{'(pessimistic)':>15}")
    for sid, cat, manual, ai, ai_p in rows:
        print(f"  {sid:<9}{cat:<24}{manual:>7.0f}m{ai:>12.0f}m{ai_p:>14.0f}m")
    print(f"  {'TOTAL':<33}{summary['manual_minutes']:>7.0f}m{summary['ai_assisted_analyst_minutes']:>12.0f}m"
          f"{summary['ai_assisted_analyst_minutes_pessimistic']:>14.0f}m")
    print(f"  Estimated analyst-time reduction: {summary['analyst_time_reduction_pct']}% "
          f"({summary['analyst_time_reduction_pct_pessimistic']}% if review takes twice as long)")
    if summary.get("model_minutes_measured_total") is not None:
        print(f"  Measured model time: {summary['model_minutes_measured_total']} min total, "
              f"{summary['model_minutes_measured_mean']} min per exception (unattended)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the LoanOps Intelligence evaluation.")
    parser.add_argument("--only", help="comma-separated scenario ids, e.g. S01,S04")
    parser.add_argument("--max-attempts", type=int, help="override LOANOPS_OLLAMA_MAX_ATTEMPTS")
    parser.add_argument("--estimate-only", action="store_true", help="print the time estimate without calling the model")
    args = parser.parse_args(argv)

    scenarios = [scenario_by_id(s.strip()) for s in args.only.split(",")] if args.only else list(SCENARIOS)
    baseline = BaselineModel.load(BASELINE_PATH)

    if args.estimate_only:
        estimates = [baseline.estimate(CATEGORY_BY_RULE[s.rule_id]) for s in scenarios]
        rows = [(s.scenario_id, e.category, e.manual_minutes, e.ai_analyst_minutes, e.ai_analyst_minutes_pessimistic)
                for s, e in zip(scenarios, estimates)]
        print_estimate(summarise_estimates(estimates), rows)
        return 0

    s = get_settings()
    client = OllamaClient(s.ollama_base_url, s.ollama_model, timeout_seconds=s.ollama_timeout_seconds,
                          temperature=s.ollama_temperature, num_ctx=s.ollama_num_ctx)
    try:
        if not model_is_available(s.ollama_model, client.list_models()):
            print(f"Model {s.ollama_model} is not installed. Run: ollama pull {s.ollama_model}")
            return 1
    except LlmError as exc:
        print(f"Ollama check failed [{exc.code}]: {exc.message}")
        return 1

    max_attempts = args.max_attempts or s.ollama_max_attempts
    print(f"Evaluating {len(scenarios)} scenario(s) with {s.ollama_model}, max {max_attempts} attempt(s) each.")
    print("On CPU expect roughly 3-6 minutes per scenario. Results are saved as each one finishes.\n")

    init_db()
    with SessionLocal() as session:
        run = run_evaluation(session, client, max_attempts=max_attempts, baseline=baseline,
                             scenarios=scenarios, progress=print)
        path = export_run(session, run, EXPORT_DIR)

    summary = run.summary or {}
    print(f"\n{run.run_id} {run.status}: {summary.get('succeeded')}/{summary.get('ran')} valid reports, "
          f"mean score {summary.get('mean_score_all_run')} (valid reports only: {summary.get('mean_score_valid_reports')})")
    print("Validation:", json.dumps(summary.get("validation")))
    print("Check pass rates:", json.dumps(summary.get("check_pass_rates")))
    print("Quality:", json.dumps(summary.get("quality")))
    print("Timing (s):", json.dumps(summary.get("timing_seconds")))

    by_scenario = summary.get("time_estimate", {}).get("by_scenario", [])
    rows = [(r["scenario_id"], r["category"], r["manual_minutes"], r["ai_analyst_minutes"],
             r["ai_analyst_minutes_pessimistic"]) for r in by_scenario]
    if rows:
        print_estimate(summary["time_estimate"]["summary"], rows)
    print(f"\nFull results (reports, checks, metrics): {path}")
    print(f"API: GET /api/evaluations/{run.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
