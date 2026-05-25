"""Shared types for the adapter layer."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FetchTask:
    url: str
    expected_mime: str
    extra_metadata: dict = field(default_factory=dict)


@dataclass
class AdapterRunResult:
    source_id: str
    fetched: int = 0
    stored_new: int = 0
    parse_errors: int = 0
    robots_blocked: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "fetched": self.fetched,
            "stored_new": self.stored_new,
            "parse_errors": self.parse_errors,
            "robots_blocked": self.robots_blocked,
            "errors": self.errors,
        }
