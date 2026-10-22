"""Test helpers: a scripted fake LLM and a report builder."""

import json
from collections.abc import Callable
from typing import Any

from app.ai.errors import LlmError


class FakeLlm:
    """Replays scripted responses. Each item is a str (returned), an LlmError
    (raised), or a callable(messages) -> str."""

    def __init__(self, *responses: Any, model: str = "fake-model", models: list[str] | None = None,
                 list_error: LlmError | None = None) -> None:
        self.model = model
        self._responses = list(responses)
        self._models = models if models is not None else [model]
        self._list_error = list_error
        self.calls: list[list[dict[str, str]]] = []
        self.schemas: list[dict[str, Any]] = []

    def list_models(self) -> list[str]:
        if self._list_error:
            raise self._list_error
        return self._models

    def chat(self, messages: list[dict[str, str]], response_schema: dict[str, Any]) -> str:
        self.calls.append(messages)
        self.schemas.append(response_schema)
        if not self._responses:
            raise AssertionError("FakeLlm called more times than scripted")
        response = self._responses.pop(0)
        if isinstance(response, LlmError):
            raise response
        if callable(response):
            return response(messages)
        return response


def ids_of(items: list[dict[str, Any]], evidence_type: str, contains: str = "") -> list[str]:
    """Evidence ids of a given type (optionally whose source_reference contains a string)."""
    return [
        i["evidence_id"] for i in items
        if i["evidence_type"] == evidence_type and contains in i["source_reference"]
    ]


def report(exception_id: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "exception_id": exception_id,
        "summary": "Upstream and downstream records disagree on one field.",
        "evidence_sufficiency": "SUFFICIENT_FOR_HYPOTHESIS",
        "confirmed_facts": [],
        "probable_causes": [],
        "alternative_explanations": [],
        "conflicting_evidence": [],
        "recommended_checks": [],
        "missing_information": [],
        "uncertainties": [],
        "escalation": {"recommended": False, "reason": "Routine investigation within operations."},
        "overall_assessment": "A hypothesis is supported by the evidence but must be verified.",
    }
    base.update(overrides)
    return base


def cause(text: str, supporting: list[str], *, claim_type: str = "EVIDENCE_SUPPORTED_HYPOTHESIS",
          contradicting: list[str] | None = None, confidence: str = "medium") -> dict[str, Any]:
    return {
        "cause": text,
        "claim_type": claim_type,
        "supporting_evidence_ids": supporting,
        "contradicting_evidence_ids": contradicting or [],
        "reasoning": "Explained by the cited evidence.",
        "confidence": confidence,
    }


def check(step: str, evidence_ids: list[str], basis: str = "EVIDENCE") -> dict[str, Any]:
    return {"step": step, "purpose": "Confirm or refute the hypothesis.", "basis": basis, "evidence_ids": evidence_ids}


def fact(statement: str, evidence_ids: list[str]) -> dict[str, Any]:
    return {"statement": statement, "evidence_ids": evidence_ids}


def as_json(data: dict[str, Any]) -> str:
    return json.dumps(data)


def respond_with(builder: Callable[[], dict[str, Any]]) -> Callable[[list[dict[str, str]]], str]:
    return lambda _messages: json.dumps(builder())
