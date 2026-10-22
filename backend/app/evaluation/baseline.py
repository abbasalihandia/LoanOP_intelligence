"""Manual vs AI-assisted investigation time: an explicit ESTIMATE model (pure).

All minutes come from config/manual_baseline_estimates.json. Only the model
generation time is measured; everything else is an assumption, and outputs
are labelled accordingly.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TimeEstimate:
    category: str
    manual_minutes: float
    ai_analyst_minutes: float
    ai_analyst_minutes_pessimistic: float
    model_minutes_measured: float | None
    manual_steps: list[str]
    residual_steps: list[str]


class BaselineModel:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.steps: dict[str, dict[str, Any]] = config["manual_steps"]
        self.by_category: dict[str, list[str]] = config["manual_steps_by_category"]
        ai = config["ai_assisted"]
        self.review: dict[str, float] = ai["review_minutes"]
        self.resolution_minutes: float = ai["resolution_minutes"]
        self.residual: dict[str, list[str]] = ai.get("residual_manual_steps_by_category", {})
        self.sensitivity: float = ai.get("review_sensitivity_factor", 1.0)

    @classmethod
    def load(cls, path: Path) -> "BaselineModel":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def _minutes(self, steps: list[str]) -> float:
        return float(sum(self.steps[s]["minutes"] for s in steps))

    def estimate(self, category: str, model_seconds: float | None = None) -> TimeEstimate:
        manual_steps = self.by_category.get(category, ["compare_records", "write_up"])
        residual = self.residual.get(category, [])
        review = float(self.review.get(category, self.review["default"]))
        residual_minutes = self._minutes(residual)
        return TimeEstimate(
            category=category,
            manual_minutes=self._minutes(manual_steps),
            ai_analyst_minutes=review + self.resolution_minutes + residual_minutes,
            ai_analyst_minutes_pessimistic=review * self.sensitivity + self.resolution_minutes + residual_minutes,
            model_minutes_measured=round(model_seconds / 60, 1) if model_seconds is not None else None,
            manual_steps=[self.steps[s]["label"] for s in manual_steps],
            residual_steps=[self.steps[s]["label"] for s in residual],
        )


def summarise_estimates(estimates: list[TimeEstimate]) -> dict[str, Any]:
    manual = sum(e.manual_minutes for e in estimates)
    ai = sum(e.ai_analyst_minutes for e in estimates)
    ai_pessimistic = sum(e.ai_analyst_minutes_pessimistic for e in estimates)
    measured = [e.model_minutes_measured for e in estimates if e.model_minutes_measured is not None]
    return {
        "label": "ESTIMATE — analyst minutes are assumptions, not measurements; model minutes are measured.",
        "exceptions": len(estimates),
        "manual_minutes": manual,
        "ai_assisted_analyst_minutes": ai,
        "ai_assisted_analyst_minutes_pessimistic": ai_pessimistic,
        "analyst_time_reduction_pct": round(100 * (1 - ai / manual), 1) if manual else None,
        "analyst_time_reduction_pct_pessimistic": round(100 * (1 - ai_pessimistic / manual), 1) if manual else None,
        "model_minutes_measured_total": round(sum(measured), 1) if measured else None,
        "model_minutes_measured_mean": round(sum(measured) / len(measured), 1) if measured else None,
    }
