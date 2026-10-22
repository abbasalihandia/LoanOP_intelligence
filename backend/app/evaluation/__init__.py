"""End-to-end evaluation (Phase 7).

scenarios.py, scoring.py and baseline.py are pure Python. runner.py uses the
database and the shared investigation core, but never changes exception
statuses or creates AI investigation records: evaluation results are stored
in their own tables.
"""
