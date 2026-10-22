# LoanOps Intelligence — Project Log

Paste this file at the start of a new conversation to continue development consistently.

## Environment (developer machine)

- Windows, Command Prompt. Project at `D:\loanops-intelligence`
- Python 3.13.7, Node 22.19.0, npm 10.9.3, Git 2.51, Ollama 0.40.3
- Confirmed working: pytest 8.4.2, Vite dev proxy to uvicorn on 127.0.0.1:8000
- 16 GB RAM (13.8 GB usable). AMD Radeon 840M integrated GPU, sharing system RAM; assume CPU inference.
- Ollama models installed: llama3.1:latest (8B), llama3.2:3b, qwen2.5-coder:1.5b. qwen2.5:7b download pending.
- Working model: `LOANOPS_OLLAMA_MODEL=llama3.1:latest`, `LOANOPS_OLLAMA_TIMEOUT_SECONDS=600` (about 200 s per report on CPU).

## Architecture

React workbench → FastAPI backend (the single control point) → SQLite and Ollama.
The frontend never calls Ollama or the database directly.

| Module | Phase | Responsibility |
|---|---|---|
| `integration/` | 1 ✔ | Simulated feeds → normalization → versioned loan records |
| `reference/` | 1 ✔ | Mapping rules, agreement clauses, historical cases |
| `validation/` | 2 ✔ | Deterministic rules (pure), configurable severity, DB runner |
| `exception_engine/` | 2 ✔ | Exception records, re-detection and suppression, status machine and history |
| `evidence/` | 3 ✔ | Evidence registry (stable EV ids), retrieval with relevance and gaps, traceability |
| `ai/` | 4 ✔ | Evidence package → controlled prompt → Ollama → validated report → audit |
| `resolution/` | 6 ✔ | Analyst resolution (AI snapshot kept separate), feedback into history, recurrence, audit trail |
| `evaluation/` | 7 ✔ | Scenario expectations, scoring, time-estimate model, isolated runner |
| `frontend/` | 5 ✔ | Operations Workbench: dashboard, detail tabs, evidence drawer, AI report with evidence chips, resolution form, audit |

### Phase 1 data model

| Table | Holds |
|---|---|
| `ingestion_batches` | One row per feed run, with outcome counts |
| `raw_source_records` | Every payload as received, with its outcome (CREATED / UNCHANGED / STALE / REJECTED) and any error |
| `loan_records` | Canonical record per (loan, source, version). `is_current` flags the latest. `normalization_issues` holds unparseable values. |
| `mapping_rules` | PRODMAP-v1 and PRODMAP-v2 product mappings with effective dates |
| `agreement_clauses` | Facility agreement and amendment clauses |
| `historical_exceptions` | Past cases. `origin = SEED_LEGACY` for seeded rows. |

### Phase 2 data model

| Table | Holds |
|---|---|
| `validation_runs` | One row per run: counts, plus the SHA-256 of the config used |
| `exceptions` | `exception_id` (EXC-00001…, stable), `fingerprint` (loan\|rule\|field\|side), `value_signature`, severity, neutral source/target values, explanation, details (metrics, mapping info), evaluated record IDs, status, `still_detected` |
| `exception_status_changes` | Append-only history, including creation by `system:validation` |

### Phase 3–4 data model

| Table | Holds |
|---|---|
| `evidence_items` | Immutable snapshot per (source_reference, content_hash), with `evidence_id` EV-00001…. Same source and content always give the same ID. |
| `exception_evidence` | Latest retrieval links: position, retrieval_method, relevance reason, score |
| `ai_investigations` | One row per attempt (SUCCEEDED/FAILED): AI-00001…, requester, model, attempts, evidence ids + full package snapshot, prompt SHA-256, raw outputs, per-attempt validation errors, report JSON. Kept separate from the Phase 6 resolution table. |

### Phase 6 data model

| Table | Holds |
|---|---|
| `exception_resolutions` | RES-00001…, one per exception. AI side: `ai_investigation_id`, `ai_recommendation` (snapshot: causes, assessment, label "AI-generated recommendation (not confirmed)"), `ai_cause_index`. Analyst side: `analyst_decision`, `root_cause_category`, `confirmed_root_cause`, `record_in_error`, `final_action`, `outcome`, `evidence_ids`, `notes`, `resolved_by`, `resolved_at`. Also the record versions at resolution and `historical_case_id`. |

Resolution vocabularies (in `resolution/vocab.py`, served with labels by `/api/resolution/options`):
- **Decision:** AI_ACCEPTED, AI_MODIFIED, AI_REJECTED, NO_AI_REPORT
- **Record in error:** UPSTREAM, DOWNSTREAM, BOTH, NEITHER, UNDETERMINED
- **Outcome:** CORRECTED_IN_SOURCE, NO_CHANGE_REQUIRED, REFERRED_TO_OWNER
- **Root-cause category:** 10 values, including LEGITIMATE_DIFFERENCE.

### Evidence retrieval order

1. The exception's own finding
2. The evaluated upstream and downstream record versions
3. Other active findings on the same loan
4. Mapping rules (product_type only): the rule in the recorded version, plus the active rule
5. Clauses for the loan or facility matched by field keywords
6. Historical cases scored on category +3, field +2, upstream value +2, downstream value +2. Minimum score 4, top 3, other loans only.

Gaps are reported deterministically: missing record, no clauses, no relevant clauses, no mapping rule, no similar history.

### AI report validation

1. **JSON parsing.** A code fence or `<think>` block is tolerated.
2. **Pydantic.** `extra=forbid`. Evidence IDs must match `EV-\d{5}`. Facts need at least 1 ID. EVIDENCE_SUPPORTED_HYPOTHESIS needs at least 1 supporting ID. A conflict needs at least 2 distinct IDs. A check with basis EVIDENCE needs at least 1 ID. Confidence is a low/medium/high enum. If there are no causes, sufficiency must be INSUFFICIENT; INSUFFICIENT allows no high-confidence cause.
3. **Semantic checks.** The exception ID must match. Every cited ID must be in the package. A cause backed only by historical cases must be an UNVERIFIED_POSSIBILITY with low confidence.
4. **Assembly.** The backend adds the observed discrepancies (from deterministic validation), the standard root-cause statement, the confidence note, policy flags and provenance.

### Validation rules

| Rule | Category | Base severity |
|---|---|---|
| RULE-REQ-001 | MISSING_FIELD | HIGH |
| RULE-TYPE-001 | DATA_TYPE | HIGH |
| RULE-PRODUCT-001 | PRODUCT_MISMATCH | HIGH |
| RULE-CCY-001 | CURRENCY_MISMATCH | CRITICAL |
| RULE-AMT-001 | AMOUNT_MISMATCH | HIGH; CRITICAL if ≥ 10% |
| RULE-MAT-001 | MATURITY_MISMATCH | MEDIUM; HIGH if ≥ 30 days |
| RULE-MAP-001 | MAPPING_INCONSISTENCY (mapping not applied as configured) | HIGH |
| RULE-MAP-002 | MAPPING_INCONSISTENCY (retired mapping gives a different result) | MEDIUM |
| RULE-MAP-003 | MAPPING_INCONSISTENCY (version or rule not found) | MEDIUM |
| RULE-BOOK-001 | BOOKING_FAILURE | HIGH |
| RULE-BOOK-002 | MISSING_DOWNSTREAM | MEDIUM |
| RULE-BOOK-003 | ORPHAN_DOWNSTREAM | MEDIUM |

### Status lifecycle

- OPEN → UNDER_INVESTIGATION, ESCALATED, REJECTED
- UNDER_INVESTIGATION ↔ AWAITING_EVIDENCE
- UNDER_INVESTIGATION → RECOMMENDATION_GENERATED (AI service only), RESOLVED (resolution workflow only), ESCALATED, REJECTED
- RESOLVED and REJECTED are terminal.
- A reason is required for REJECTED, ESCALATED and AWAITING_EVIDENCE.
- Actors starting with `system:` are reserved for the platform.

## Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Vite instead of Create React App | CRA is deprecated; Vite is the current standard. |
| D2 | The Vite dev proxy forwards `/api` to `127.0.0.1:8000`. CORS acts only as a fallback. | One origin, no hard-coded URLs. `127.0.0.1` avoids the IPv6 `localhost` problem on Windows. |
| D3 | All settings come from `LOANOPS_*` environment variables, loaded with pydantic-settings. | Keeps configuration out of the code (principle 12). |
| D4 | The backend uses an app factory (`create_app()`). | Makes it easy to override settings in tests later. |
| D5 | The health response includes `data_mode: "synthetic"`. | Labels the simulated integrations (principle 11). |
| D6 | No component library and no CSS framework yet. | Avoids dependencies until the Phase 5 workbench needs them. |
| D7 | `requirements.txt` uses version ranges; `pip freeze` output goes to `requirements.lock.txt`. | Ranges keep installs flexible; the lock file records the exact working set. |
| D8 | SQLAlchemy 2.0 with `create_all`. Alembic is deferred. | Schema is still changing every phase. `seed --reset` rebuilds it. Revisit when data must survive schema changes. |
| D9 | Ingestion rejects only structurally unusable payloads (not an object, or no loan ID). Missing or unparseable business values are kept as `None` plus a normalization issue. | Required-field and data-type checks belong to the Phase 2 validation engine, which needs to see those records. |
| D10 | A new version is created only when the content hash changes. An older `source_updated_at` with different content is marked STALE. | Re-running a feed is idempotent, and out-of-order messages can't overwrite newer data. |
| D11 | Amounts are stored as exact decimal text (`DecimalString`), never as float. | No floating-point error in financial comparisons. |
| D12 | The canonical product vocabulary (in code) is separate from `mapping_rules` (data). | Mapping rules are the bank's interface configuration under investigation; the vocabulary is how the platform compares records. |
| D13 | Loan IDs are upper-cased. All timestamps are stored as naive UTC. | Reliable correlation across systems and unambiguous comparisons. |
| D14 | Tests run against in-memory SQLite (`LOANOPS_DATABASE_URL=sqlite://`, StaticPool). | Fast, isolated, and never touches the developer's data file. |
| D15 | `httpx2` replaces `httpx` in requirements. | Starlette's TestClient deprecated `httpx`. |
| D16 | The validation engine is pure Python over `LoanSnapshot` objects. The DB runner only loads data and persists results. | Rules can be unit-tested without a database, and evaluation is deterministic. |
| D17 | Findings report upstream and downstream values neutrally and never say which side is correct. | Principle: never assume upstream is right (see LN-1003). |
| D18 | Mapping checks are split: MAP-001 (not applied as configured) vs MAP-002 (retired version gives a different result). | Deterministically separates the LN-1001 pattern (mapping defect) from LN-1010 (mapping fine, something else changed the product). |
| D19 | Severity = base per rule, raised (never lowered) by metric overrides, all from `config/validation_rules.json`. Each run stores the config's SHA-256. | Configurable without code, and every exception is traceable to the rules that produced it. |
| D20 | Re-detection uses fingerprint + value signature. Active exceptions are updated; closed ones with the same values are suppressed; closed ones with different values recur as new exceptions. | No duplicates, no nagging about cases already closed, and real recurrences are still caught. |
| D21 | Exceptions that are no longer detected are flagged `still_detected=false`, never closed automatically. | Analysts keep control of every closure (principle 8). |
| D22 | RECOMMENDATION_GENERATED and RESOLVED can't be set through the status endpoint (`via_system` only). | They belong to the AI service (Phase 4) and the resolution workflow (Phase 6), which record what an AI suggestion or resolution actually was. |
| D23 | Validation and ingestion call `session.expire_all()` at the start. | Prevents decisions based on stale cached rows after another session (e.g. the API) changed them. |
| D24 | Evidence IDs are keyed on source reference + content hash, and content snapshots are stored. | Citations in a stored report always resolve to exactly what the model saw, even after the source changes. |
| D25 | Relevance is deterministic (keywords and attribute scoring). No vector store. | It's explainable, and sufficient for the POC data volume. Revisit in Phase 7 if recall proves weak. |
| D26 | Gaps are computed by the platform, not left to the model. | The model can't miss an absence it was explicitly told about (e.g. LN-1004 has no clauses). |
| D27 | The Ollama client uses the standard library and bypasses system proxies. | No new dependency, and a corporate proxy can't intercept local model traffic. |
| D28 | The schema is enforced twice: once as Ollama `format` (constrained decoding) and again by independent Pydantic and semantic validation. | The prompt and grammar help; validation decides. |
| D29 | Retry happens only for invalid output (feeding back the errors), bounded by `LOANOPS_OLLAMA_MAX_ATTEMPTS` (default 2). No retry on timeout, unavailable or model missing. | Retrying a validation failure often helps; repeating a multi-minute timeout rarely does. |
| D30 | Observed discrepancies in the report come from deterministic validation, not from the model. | Keeps facts separate from AI reasoning, and the model can't misstate the discrepancy. |
| D31 | The "root cause cannot be established" statement is set by the backend whenever sufficiency is INSUFFICIENT. | Required wording that doesn't depend on model phrasing. |
| D32 | Policy flags (prescriptive change steps, "X is correct" verdicts) are warnings, not rejections. | Wording varies too much to reject reliably. The structural guarantee is that the model has no tools and no write access. |
| D33 | Evidence is committed before the model call; the investigation and status changes are committed afterwards. | No SQLite write lock is held during a multi-minute LLM call. |
| D34 | Only a successful report moves the exception to RECOMMENDATION_GENERATED (as `system:ai-investigation`). A failure leaves the status unchanged. | Status reflects real outcomes. |
| D35 | Default model is `qwen2.5:7b` (configurable). | Good JSON adherence at 7B. Choose per available RAM/GPU. |
| D36 | A connect-phase timeout is reported as OLLAMA_UNAVAILABLE; only a response-phase timeout is TIMEOUT. | On Windows a closed port can time out instead of refusing. "Unreachable" and "slow model" need different remedies. |
| D37 | An EVIDENCE_SUPPORTED_HYPOTHESIS must cite at least one explanatory item: a mapping rule, a clause, a related finding, or a historical case alongside other evidence. Citing only the finding and the evaluated records is rejected. | Live run with qwen2.5-coder:1.5b produced "the product type mismatch" as the cause, with high confidence. The records show *that* values differ, not *why*. Conservative side effect: a cause like a keying error (LN-1009) must be an UNVERIFIED_POSSIBILITY unless other evidence supports it. |
| D38 | Mapping evidence carries a deterministic timeline note: where the downstream record's last update falls relative to each rule's effective period. | Live run with llama3.1 listed the v2 activation date as "missing" (it was in the evidence) and missed that LN-1001 was updated while v1 was still effective. The platform now computes timelines instead of relying on the model. |
| D39 | Prompt rules 11–12: check the evidence before declaring information missing, and compare dates using the platform's timeline notes. | Directly addresses the observed llama3.1 errors. |
| D40 | RESOLVED is reachable only through `POST …/resolution` (by a human reviewer). The exception must be UNDER_INVESTIGATION, RECOMMENDATION_GENERATED or ESCALATED. | Every resolution records a root cause, evidence and a decision about the AI recommendation. |
| D41 | A resolution stores a *snapshot* of the reviewed AI report next to the analyst's own text. AI_ACCEPTED/MODIFIED must point to a specific AI cause. | Preserves exactly what the AI said versus what the human confirmed, and enables AI acceptance metrics in Phase 7. |
| D42 | Evidence cited in a resolution must belong to the exception's evidence links or the reviewed investigation's package. | Same traceability standard as the AI. |
| D43 | `record_in_error` must agree with the outcome: CORRECTED_IN_SOURCE requires UPSTREAM/DOWNSTREAM/BOTH; NO_CHANGE_REQUIRED requires NEITHER. | Prevents incoherent records. Deciding which record was wrong is explicitly a human judgement. |
| D44 | Each resolution creates an ANALYST_CONFIRMED historical case (case_id HX-RES-n) with analyst text only. AI text is never fed back, and the model is not retrained. | Confirmed knowledge improves future retrieval without letting AI output launder itself into "history". |
| D45 | Recurrence: a RESOLVED exception with outcome CORRECTED_IN_SOURCE resurfaces as a new exception only if *newer record versions* still show the same values. Otherwise same-value findings stay suppressed. | Catches corrections that didn't land, without nagging before the corrected feed arrives. |
| D46 | The audit trail is derived from the system-of-record tables, not a duplicate log. Actor types: ANALYST, SYSTEM, AI, AI_SERVICE. | It can't drift, and it makes AI vs human actions explicit. |
| D47 | Frontend: no router or UI library; hash routing plus a small `useLoad` hook. | No new dependencies (D6). Enough for two pages. |
| D48 | UI provenance language: slate = deterministic, violet + dashed = AI (not confirmed), green = analyst-confirmed. Evidence IDs are chips that open a drawer with the snapshot and a live traceability check. | Makes "AI suggestion vs confirmed finding" visible at a glance, and makes claim-to-evidence checking one click (the Phase 4 lesson). |
| D49 | The analyst ID is typed in the header and stored in localStorage (POC, no authentication). The `system:` prefix is refused. | Every human action is attributed. Real authentication is out of POC scope. |
| D50 | The investigation request waits up to 25 min in the browser, showing elapsed time. The evidence drawer closes on tab change and on Escape. | A local CPU model needs minutes. The drawer behaviour fixes a bug found in headless-browser testing. |
| D51 | `generate_report()` is the shared investigation core (evidence → prompt → model → validation → assembly). The workbench persists it as an AiInvestigation; the evaluator stores it in `evaluation_results`. | One code path, so evaluation measures exactly what analysts get, while operational statuses and audit stay clean. |
| D52 | Scenario expectations (S01–S11) encode the Phase 1 ground truth as behaviour checks: sufficiency, expected cause (keyword groups), required citations, no misreading of corroborating rules, conflict flagged, missing information requested, correct mapping not blamed, no high confidence when evidence is thin. | Measures what matters to an analyst. Keyword checks are a lenient screening aid, not a replacement for reading the stored reports. |
| D53 | Generic quality metrics: invalid citations, possibly-false missing information (an item mentioning an identifier that is in the package), uncited mentions, high confidence despite contradicting evidence, policy flags, escalations. | Targets the specific failure modes seen in AI-00001 to AI-00003. |
| D54 | The time comparison is an explicit ESTIMATE model (`config/manual_baseline_estimates.json`): manual step minutes per category versus AI-assisted review, resolution, and residual manual steps; plus a pessimistic case with 2× review time. Only model time is measured. | The developer chose estimates over timed observations; every figure is labelled so it can't be mistaken for measurement. |
| D55 | The evaluation is llama3.1 only; no model comparison. | Developer decision (2026-10-19). |
| D56 | The evaluation aborts early on OLLAMA_UNAVAILABLE or MODEL_NOT_FOUND; each result is committed as it finishes. | No point making 11 failing calls; an interrupted long run keeps its progress. |
| D57 | SUFFICIENT_FOR_HYPOTHESIS requires at least one EVIDENCE_SUPPORTED_HYPOTHESIS; otherwise the report must say INSUFFICIENT. Enforced in the schema; stated in the prompt. | EVAL-00002: S04, S06, S08 and S09 claimed "sufficient" with only unverified causes (S06 and S09 also wrote "root cause cannot be established"). Replaying all 11 reports rejects exactly S04, S06, S07, S08, S09 and accepts the rest. |
| D59 | An EVIDENCE_SUPPORTED_HYPOTHESIS must cite at least one explanatory item for this loan: a mapping rule, a clause, or a related finding. The finding, the evaluated records and historical cases may add support but cannot qualify a cause on their own, in any combination. | EVAL-00003 S08: finding + historical case passed both D37 and the history-only rule, producing a spurious cause borrowed from another loan's pricing case. Replay confirms the report is now rejected. |
| D60 | Mislabelled causes are **rejected, not auto-downgraded** (option A, chosen by the developer 2026-10-20). No platform edits to model output; a third attempt was not added. | Honours brief principle 5 ("unsupported claims must be treated as a failure") and is simpler to defend to model-risk review. Accepted cost: an occasional correct-in-substance report is lost (EVAL-00003 S04), and the analyst gets a controlled "no valid report" with full audit. Option B (transparent weaken-only downgrade) remains documented as an alternative. |
| D58 | When D37 (or the history-only rule) downgrades every supported cause, the same feedback also states that sufficiency must then be INSUFFICIENT. | Without this, D37 then D57 would chain across attempts: the model relabels causes on retry 1, D57 rejects it, and max_attempts=2 is exhausted. That would have turned 5 valid EVAL-00002 reports into INVALID_OUTPUT. Found by replaying the real reports before release. |

### Time comparison: ESTIMATE (not measured)

| Scenario | Category | Manual (min) | AI-assisted analyst (min) | Pessimistic (2× review) |
|---|---|---|---|---|
| S01 LN-1001 | Product mismatch | 48 | 13 | 23 |
| S02 LN-1001 | Mapping inconsistency | 48 | 13 | 23 |
| S03 LN-1003 | Amount mismatch | 38 | 13 | 23 |
| S04 LN-1004 | Currency mismatch | 38 | 13 | 23 |
| S05 LN-1005 | Maturity mismatch | 38 | 13 | 23 |
| S06 LN-1006 | Missing field | 28 | 13 | 23 |
| S07 LN-1007 | Booking failure | 53 | 28 (static-data check stays manual) | 38 |
| S08 LN-1008 | Missing downstream | 26 | 19 (interface logs stay manual) | 25 |
| S09 LN-1009 | Data type | 16 | 8 | 13 |
| S10 LN-1010 | Product mismatch | 48 | 13 | 23 |
| S11 LN-1010 | Mapping inconsistency | 48 | 13 | 23 |
| **Total** | | **429 (7.2 h)** | **159 (2.7 h), −63%** | **260 (4.3 h), −39%** |

Model generation (llama3.1 on CPU) observed at 204–237 s per report. It runs unattended and is not counted as analyst time.

### Live model observations (Phase 4)

| Run | Model | Result |
|---|---|---|
| AI-00001 / EXC-00001 | qwen2.5-coder:1.5b, 53 s | Passed validation but the reasoning was poor: restated the discrepancy as the cause (high confidence), missed the mapping evidence, asked for history that was supplied, and needlessly escalated. Now rejected by D37. |
| AI-00002 / EXC-00002 | llama3.1 8B, 204 s, 1 attempt | Found the retired-PRODMAP-v1 vs v2 insight with correct citations. Errors: claimed the v2 activation date was missing (it was in EV-00006); "v1 used instead of v2" ignored that v1 was still effective at the time of the update; listed the up/down records themselves as conflicting evidence; strawman alternative explanation. Mitigated by D38 and D39. Phase 7 should measure these systematically. |
| AI-00003 / EXC-00002 (after D37–D39) | llama3.1 8B, 237 s, 1 attempt | No longer claims the v2 date is missing. Remaining errors: treated the active v2 rule as *contradicting* (it corroborates); high confidence despite listing contradicting evidence; ignored the timeline note; asked for the clause effective date (present in EV-00007); mentioned a clause without citing it. Conclusion: these are model-capacity limits of an 8B CPU model, not pipeline defects. No further validation rules; measure in Phase 7, and make claim-to-evidence checking easy in the Phase 5 UI. |

## Synthetic scenario catalogue (seed data)

| Loan | Upstream vs downstream | Evidence available | Intended investigation outcome |
|---|---|---|---|
| LN-1001 | Revolving Credit vs TERM | Booked with PRODMAP-v1, which maps RC→TERM (fixed in v2). Clause 2.1 says "revolving". Similar case HX-2024-0117. | Mapping defect is well supported. Downstream likely wrong. |
| LN-1002 | Match (GBP term loan) | — | No exception (control case). Upstream also contains an exact duplicate payload. |
| LN-1003 | 25,000,000 vs 20,000,000 | Amendment AMD-1003-01 reduced commitments to 20m. Similar case HX-2025-0031. | **Upstream is stale; downstream is correct.** |
| LN-1004 | EUR vs USD | No clauses, no similar history. | Insufficient evidence; root cause can't be determined. |
| LN-1005 | 2029-12-31 vs 2029-12-01 | Clause says Termination Date is 31 Dec 2029. Similar keying case HX-2025-0074. | Downstream keying error likely. |
| LN-1006 | Upstream maturity missing | Clause defines maturity as 12 months after first Utilisation Date (date unknown). Downstream shows 30-Nov-2026. | Missing information; needs the utilisation date. |
| LN-1007 | Booking FAILED (pricing option SORA-3M) | Clause 8.2 uses compounded SORA 3M. Similar case HX-2025-0058. | Static-data setup gap. |
| LN-1008 | No downstream record | — | Approved but never booked. |
| LN-1009 | Downstream amount `"12,5OO,000"` (letter O) | Normalization issue recorded. | Data-type exception. |
| LN-1010 | Bridge Loan vs TERM | Booked with PRODMAP-v2, which maps Bridge→BRIDGE correctly. Clause says "bridge term loan". HX-2025-0090 closed unresolved. | Mapping **not** the cause. Ambiguous wording; possible manual override. Conflicting evidence. |

Ingestion edge cases: LN-1001 has two upstream versions (Credit Review, then Approved). There are 3 rejected payloads: an upstream record with no `Name`, a downstream record with no `loanReference`, and a truncated non-JSON-object message.

## Phase status

- [x] **Phase 0** — foundation. Confirmed by the developer on 2026-10-19 (5 tests passed, frontend connected).
- [x] **Phase 1** — synthetic data and integration. Confirmed 2026-10-19 (45 tests passed; seed counts and idempotent re-seed as designed).
- [x] **Phase 2** — deterministic validation and exception management. Confirmed 2026-10-19 (105 tests passed).
- [x] **Phase 3** — evidence and context engine. Confirmed 2026-10-19 (178 tests passed after the traceability fix).
- [x] **Phase 4** — Ollama integration and AI investigation. Confirmed 2026-10-19 (178 tests passed; live runs AI-00001 to AI-00003 succeeded).
- [x] **Phase 5** — operations workbench. Confirmed 2026-10-19 (app running against the real backend).
- [x] **Phase 6** — resolution feedback and audit. Confirmed 2026-10-19 (202 tests passed).
- [x] **Phase 7** — end-to-end evaluation. 219 tests passed. Full run EVAL-00002 (llama3.1, 2026-10-19) completed; results below. Written evaluation report: deferred at the developer's request.

### EVAL-00002 results (llama3.1:latest, CPU, single run per scenario)

| Scenario | Attempts | Time | Score | Failed checks |
|---|---|---|---|---|
| S01 LN-1001 product / retired mapping | 1 | 132 s | 1.00 | — |
| S02 LN-1001 MAP-002 | 1 | 411 s | 1.00 | — |
| S03 LN-1003 amendment conflict | 1 | 166 s | 1.00 | — |
| S04 LN-1004 currency, no contract | 2 | 163 s | 0.75 | evidence_sufficiency (claimed sufficient) |
| S05 LN-1005 maturity keying | 1 | 101 s | 0.75 | expected_cause_found (possible scorer false negative; unverified) |
| S06 LN-1006 missing maturity | 2 | 182 s | 0.33 | did not cite CL-FA1006-1.1; did not ask for the utilisation date |
| S07 LN-1007 booking failure | 2 | 178 s | 1.00 | — |
| S08 LN-1008 not booked | 2 | 181 s | 0.75 | evidence_sufficiency (claimed sufficient) |
| S09 LN-1009 data type | 2 | 229 s | 1.00 | — |
| S10 LN-1010 product / mapping not the cause | 1 | 173 s | 1.00 | — |
| S11 LN-1010 MAP-001 | 1 | 173 s | 1.00 | — |

Totals:
- 11/11 valid reports: 6 on the first attempt, 5 after one retry, 0 failed.
- 84 citations, 0 invalid. Mean score 0.871.
- Quality flags: 3 possibly-false missing-information items; 1 high-confidence cause with contradicting evidence; 1 escalation.
- Model time: mean 190 s, max 411 s, total 34.9 min.

Key findings:
1. The hardest reasoning scenarios passed: S03 conflict, S10/S11 correct mapping not blamed, S02 v2 not misread this time.
2. Systematic weakness: the model never declared INSUFFICIENT. It failed on both scenarios designed for it (S04, S08), although it avoided high confidence (3/3) and asked for missing information (2/3).
3. Run-to-run variability: S01 scored 0.75 in EVAL-00001 and 1.00 in EVAL-00002 on identical evidence. Single-run scores are indicative only.

Manual review of the failing reports (S04, S05, S06, S08) in EVAL-00002.json:
- **All four failed checks were genuine; there were no scorer false negatives.** S05 was suspected but confirmed.
- **Incoherent sufficiency in S04, S06 and S08.** Each claimed SUFFICIENT_FOR_HYPOTHESIS while proposing only UNVERIFIED_POSSIBILITY causes. S06's own overall assessment says "root cause cannot be established".
- **D37 worked as designed.** Attempt 1 of S04, S06 and S08 was rejected for citing only the finding and records; the model relabelled the causes as unverified on retry. That accounts for 3 of the 5 retries.
- **S05: right fact, wrong conclusion.** The model noted that the clause (31 Dec 2029) matches upstream, but concluded "Mapping rule or clause discrepancy" with HIGH confidence. No mapping is involved, and it never named the keying error the evidence points to.
- **S06: genuine miss.** It never cited CL-FA1006-1.1 and never asked for the first utilisation date; its missing information was empty.
- **S04 invented a non-existent artifact class.** It proposed "currency mapping rules" (correctly labelled unverified, low confidence), and its overall assessment said "likely", which overstates an unverified possibility.
- **Fix implemented 2026-10-20 as D57 and D58.** Replay also caught S07 (the cause was relabelled unverified after D37, with the clause never cited as support) and S09 (the same contradiction as S06).

### EVAL-00003 (re-run of S04, S06, S07, S08, S09 after D57 and D58), with manual review of the JSON

| Scenario | Result | What actually happened |
|---|---|---|
| S04 | FAILED (INVALID_OUTPUT) | **The substance was right on both attempts:** INSUFFICIENT, asked for the agreement, and "cannot be established". But the cause was labelled EVIDENCE_SUPPORTED citing only the two records, so D37 rejected it. The model repeated the identical mislabel after feedback. The failure came from D37, not D57. |
| S06 | 0.67 (was 0.33) | Now INSUFFICIENT, consistent with its own assessment. Cites the utilisation clause, but only in a check. Asks for "record version history", not the utilisation date. |
| S07 | 0.75 (was 1.00) | D37 rejected the cause cited only to the finding and record. Given both options, the model took the weakest: relabelled it unverified, re-supported it with a *historical case*, and set INSUFFICIENT. The SORA clause was still not linked to the error. 1,004 s for two attempts (~8 min per generation versus a usual ~3); likely machine load, not a validation effect. |
| S08 | 0.50 | **Loophole confirmed.** An EVIDENCE_SUPPORTED cause backed by the finding plus a historical case passes both D37 (not all descriptive) and the history-only rule (not all history). The cause itself was spurious ("missing facility agreement clause"), borrowed from a pricing case on another loan, while the overall assessment says the cause cannot be established. |
| S09 | 1.00 | Correct: INSUFFICIENT, unverified cause, coherent. |

Conclusions:
1. D57 fixed incoherence where the model followed it (S06, S09).
2. The history-plus-descriptive loophole is real and should be closed. Historical cases must not count as explanatory support.
3. llama3.1 repeats claim_type mislabelling even after explicit feedback (S04). Rejection then discards a report whose substance was correct; this is the price of principle 5 ("unsupported claims treated as failure"). A decision is needed: keep rejecting, or apply a transparent, weaken-only downgrade.

## Release 7.3 — UI simplification (user request)

Removed from the analyst workbench (display only; no backend, API or audit change):
- Header tag "Synthetic data · POC".
- AI investigation card: the explanatory paragraph about the backend/Ollama flow and the "Model status" line. (Run button is still disabled with a reason if the model is unavailable.)
- Investigation history table: the Model column.
- AI report: the banner "AI-generated recommendation — not a confirmed finding … Model … · date".
- For consistency, the model name was also dropped from the AI-report picker and the "What the AI recommended" card in Resolution.

The model name is still recorded per investigation in the database and API, and in the audit trail. Note: the per-report AI disclaimer banner is no longer shown; the AI card provenance labels remain.

## Release 7.4 — Readability redesign: AI investigation and audit trail (user request)

Frontend only; no backend, API or data change.
- AI investigation: a launch panel with a progress bar while the model runs; history as selectable run cards (status, requester, duration, attempts, date).
- AI report reordered for reading: a verdict panel (sufficiency, escalation, overall assessment, counts) → the discrepancy as a side-by-side upstream ≠ downstream view → numbered probable-cause cards (evidence-backed vs unverified, a three-segment qualitative confidence meter, Supports/Contradicts evidence) → evidence-backed facts → numbered next steps → gaps and open questions in cards.
- Evidence chips now carry a type label (Finding, Mapping, Clause, Past case, Upstream, Downstream).
- Audit trail: filter by actor (All / Analyst decisions / Platform / AI) with counts, newest first, grouped by day, a vertical timeline with colour-coded nodes, plain-English event titles, status transitions drawn as badges, and UPPER_SNAKE values shown as words. The model name is not displayed (it stays in the stored audit data).
- Confidence remains qualitative (low/medium/high); no percentages are shown.
