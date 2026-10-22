"""Read-only index over mapping rules for fast lookups during validation."""

from collections.abc import Iterable

from app.validation.model import MappingRuleView

ACTIVE = "ACTIVE"


class MappingIndex:
    def __init__(self, rules: Iterable[MappingRuleView]) -> None:
        self._by_version_source: dict[tuple[str, str], MappingRuleView] = {}
        self._version_status: dict[str, str] = {}
        self._active: dict[tuple[str, str], MappingRuleView] = {}

        for rule in rules:
            source_key = rule.source_value.strip().lower()
            self._by_version_source[(rule.version, source_key)] = rule
            # A version counts as ACTIVE if any of its rules is active.
            if self._version_status.get(rule.version) != ACTIVE:
                self._version_status[rule.version] = rule.status
            if rule.status == ACTIVE:
                self._active[(rule.mapping_set, source_key)] = rule

    def has_version(self, version: str) -> bool:
        return version in self._version_status

    def version_status(self, version: str) -> str | None:
        return self._version_status.get(version)

    def lookup(self, version: str, source_value: str) -> MappingRuleView | None:
        return self._by_version_source.get((version, source_value.strip().lower()))

    def active_rule(self, mapping_set: str, source_value: str) -> MappingRuleView | None:
        return self._active.get((mapping_set, source_value.strip().lower()))
