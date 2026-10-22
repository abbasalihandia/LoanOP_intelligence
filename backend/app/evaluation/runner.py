"""Run every scenario through the shared investigation core and score it.

Isolation from operations: this calls generate_report() directly, so no
AiInvestigation rows are created and no exception status changes. Each
result is committed as soon as it is scored, so an interrupted run keeps
what it has done. If Ollama is unreachable or the model is missing, the run
stops early (status ABORTED) instead of failing eleven times.
"""

import json
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import asdict
from pathlib import Path
from statistics import mean
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.client import LlmClient
from app.ai.prompt import PROMPT_VERSION
from app.ai.service import generate_report
from app.db.models import EvaluationResult, EvaluationRun, ExceptionRecord, utcnow
from app.evaluation.baseline import BaselineModel, summarise_estimates
from app.evaluation.scenarios import SCENARIOS, Scenario
from app.evaluation.scoring import score_report

STOP_CODES = {"OLLAMA_UNAVAILABLE", "MODEL_NOT_FOUND"}


def _next_run_id(session: Session) -> str:
    highest = session.scalar(select(func.max(EvaluationRun.id))) or 0
    return f"EVAL-{highest + 1:05d}"


def _find_exception(session: Session, scenario: Scenario) -> ExceptionRecord | None:
    """Latest exception for the scenario's loan and rule, whatever its status."""
    return session.scalar(
        select(ExceptionRecord)
        .where(ExceptionRecord.loan_id == scenario.loan_id, ExceptionRecord.rule_id == scenario.rule_id)
        .order_by(ExceptionRecord.id.desc())
        .limit(1)
    )


def _skipped(run: EvaluationRun, scenario: Scenario, reason: str, code: str) -> EvaluationResult:
    return EvaluationResult(
        run_pk=run.id, scenario_id=scenario.scenario_id, title=scenario.title, exception_id=None,
        loan_id=scenario.loan_id, rule_id=scenario.rule_id, category=None, status="SKIPPED",
        error_code=code, error_message=reason, score=0.0, created_at=utcnow(),
    )


def run_evaluation(
    session: Session,
    client: LlmClient,
    *,
    max_attempts: int,
    baseline: BaselineModel,
    scenarios: Iterable[Scenario] = SCENARIOS,
    progress: Callable[[str], None] | None = None,
) -> EvaluationRun:
    say = progress or (lambda _msg: None)
    scenarios = list(scenarios)
    session.expire_all()
    run = EvaluationRun(
        run_id=_next_run_id(session), model=client.model, prompt_version=PROMPT_VERSION,
        max_attempts=max_attempts, status="RUNNING", scenario_count=len(scenarios), started_at=utcnow(),
    )
    session.add(run)
    session.commit()

    stop_reason: tuple[str, str] | None = None
    for index, scenario in enumerate(scenarios, start=1):
        if stop_reason is not None:
            session.add(_skipped(run, scenario, f"Not run: {stop_reason[1]}", stop_reason[0]))
            session.commit()
            continue

        exception = _find_exception(session, scenario)
        if exception is None:
            say(f"[{index}/{len(scenarios)}] {scenario.scenario_id} skipped: no exception for "
                f"{scenario.loan_id} {scenario.rule_id} (run validation first)")
            session.add(_skipped(run, scenario, "No matching exception; run validation first.", "NO_EXCEPTION"))
            session.commit()
            continue

        say(f"[{index}/{len(scenarios)}] {scenario.scenario_id} {exception.exception_id} {scenario.title} ...")
        result = generate_report(session, exception, client=client, max_attempts=max_attempts)
        package = result.package.to_dict()
        scored = score_report(scenario, result.report, package)

        row = EvaluationResult(
            run_pk=run.id, scenario_id=scenario.scenario_id, title=scenario.title,
            exception_id=exception.exception_id, loan_id=scenario.loan_id, rule_id=scenario.rule_id,
            category=exception.category, status="SUCCEEDED" if result.report is not None else "FAILED",
            error_code=result.error_code, error_message=result.error_message, attempts=result.attempts,
            duration_ms=result.duration_ms, evidence_package=package, report=result.report,
            raw_responses=result.raw_responses, validation_errors=result.attempt_errors,
            checks=[asdict(c) for c in scored.checks], metrics=scored.metrics, score=scored.score,
            created_at=utcnow(),
        )
        session.add(row)
        session.commit()
        failed = [c.name for c in scored.checks if c.passed is False]
        say(f"      {row.status} in {result.duration_ms / 1000:.0f}s, {result.attempts} attempt(s), "
            f"score {scored.score:.2f}" + (f"; failed: {', '.join(failed)}" if failed else ""))

        if result.error_code in STOP_CODES:
            stop_reason = (result.error_code, result.error_message or result.error_code)
            say(f"      stopping: {stop_reason[1]}")

    results = list(session.scalars(select(EvaluationResult).where(EvaluationResult.run_pk == run.id)
                                   .order_by(EvaluationResult.id)).all())
    run.summary = build_summary(results, baseline)
    run.status = "ABORTED" if stop_reason else "COMPLETED"
    run.completed_at = utcnow()
    session.commit()
    return run


def _check_group(name: str) -> str:
    """Aggregate per-reference checks ("cites MAP-PROD-V1-001") into one family."""
    if name.startswith("cites "):
        return "cites_required_evidence"
    if name.startswith("does not treat "):
        return "does_not_misread_corroborating_rule"
    return name


def build_summary(results: list[EvaluationResult], baseline: BaselineModel) -> dict[str, Any]:
    ran = [r for r in results if r.status != "SKIPPED"]
    ok = [r for r in ran if r.status == "SUCCEEDED"]
    durations = [r.duration_ms / 1000 for r in ran if r.duration_ms is not None]

    check_totals: dict[str, list[bool]] = defaultdict(list)
    for r in ok:
        for check in r.checks:
            if check["passed"] is not None:
                check_totals[_check_group(check["name"])].append(bool(check["passed"]))

    def total(metric: str) -> int:
        return sum(int(r.metrics.get(metric, 0) or 0) for r in ok)

    estimates = [
        baseline.estimate(r.category or "", (r.duration_ms or 0) / 1000 if r.status != "SKIPPED" else None)
        for r in results if r.category
    ]
    return {
        "scenarios": len(results),
        "ran": len(ran),
        "succeeded": len(ok),
        "failed": sum(1 for r in ran if r.status == "FAILED"),
        "skipped": sum(1 for r in results if r.status == "SKIPPED"),
        "validation": {
            "valid_first_attempt": sum(1 for r in ok if r.attempts == 1),
            "valid_after_retry": sum(1 for r in ok if r.attempts > 1),
            "invalid_after_retries": sum(1 for r in ran if r.error_code == "INVALID_OUTPUT"),
            "timeouts": sum(1 for r in ran if r.error_code == "TIMEOUT"),
        },
        "mean_score_all_run": round(mean([r.score for r in ran]), 3) if ran else None,
        "mean_score_valid_reports": round(mean([r.score for r in ok]), 3) if ok else None,
        "check_pass_rates": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(check_totals.items())},
        "quality": {
            "citations": total("citations"),
            "invalid_citations": total("invalid_citations"),
            "possibly_false_missing_information": total("possibly_false_missing_information"),
            "high_confidence_with_contradiction": total("high_confidence_with_contradiction"),
            "reports_with_uncited_mentions": sum(1 for r in ok if r.metrics.get("uncited_mentions")),
            "policy_flags": total("policy_flags"),
            "escalations_recommended": sum(1 for r in ok if r.metrics.get("escalation_recommended")),
        },
        "timing_seconds": {
            "mean": round(mean(durations), 1) if durations else None,
            "max": round(max(durations), 1) if durations else None,
            "total": round(sum(durations), 1) if durations else None,
        },
        "per_scenario": [
            {
                "scenario_id": r.scenario_id, "exception_id": r.exception_id, "title": r.title, "status": r.status,
                "error_code": r.error_code, "attempts": r.attempts,
                "seconds": round(r.duration_ms / 1000, 1) if r.duration_ms is not None else None,
                "score": r.score, "failed_checks": [c["name"] for c in r.checks if c["passed"] is False],
            }
            for r in results
        ],
        "time_estimate": {
            "summary": summarise_estimates(estimates),
            "by_scenario": [
                {"scenario_id": r.scenario_id, **asdict(e)} for r, e in zip([r for r in results if r.category], estimates)
            ],
        },
    }


def export_run(session: Session, run: EvaluationRun, folder: Path) -> Path:
    """Write the run, its summary and every result (including reports) to JSON."""
    folder.mkdir(parents=True, exist_ok=True)
    results = session.scalars(select(EvaluationResult).where(EvaluationResult.run_pk == run.id)
                              .order_by(EvaluationResult.id)).all()
    payload = {
        "run_id": run.run_id, "model": run.model, "prompt_version": run.prompt_version,
        "max_attempts": run.max_attempts, "status": run.status,
        "started_at": run.started_at.isoformat(), "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "summary": run.summary,
        "results": [
            {
                "scenario_id": r.scenario_id, "title": r.title, "exception_id": r.exception_id, "status": r.status,
                "error_code": r.error_code, "error_message": r.error_message, "attempts": r.attempts,
                "duration_ms": r.duration_ms, "score": r.score, "checks": r.checks, "metrics": r.metrics,
                "report": r.report, "validation_errors": r.validation_errors, "raw_responses": r.raw_responses,
                "evidence_ids": [i["evidence_id"] for i in r.evidence_package.get("items", [])],
            }
            for r in results
        ],
    }
    path = folder / f"{run.run_id}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path
