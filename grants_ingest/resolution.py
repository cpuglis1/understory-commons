"""Entity resolution — exact-match-after-normalize for funder identity.

V1 approach: zero fuzzy matching. At ~200 funders, fuzzy matching introduces
failure modes worse than the problem it solves.

Resolution order:
  1. EIN match (strongest signal) — exact match on Funder.ein.
  2. Normalized canonical name match — exact match on Funder.canonical_name_normalized.
  3. Alias match — exact match on FunderAlias.normalized.
  4. Miss — returns confidence='none', funder_id=None.
"""

from __future__ import annotations

import string
from dataclasses import dataclass

from grants_ingest.registry import Funder, FunderAlias


@dataclass
class ResolutionResult:
    funder_id: str | None
    confidence: str  # 'ein' | 'name' | 'alias' | 'none'
    matched_funder: Funder | None = None


def normalize_funder_name(raw: str) -> str:
    """Lowercase, strip punctuation, strip common suffixes, collapse whitespace."""
    suffixes = frozenset(
        {
            "foundation",
            "fund",
            "trust",
            "inc",
            "incorporated",
            "the",
            "corp",
            "corporation",
            "charitable",
            "endowment",
            "giving",
        }
    )
    name = raw.lower()
    name = name.translate(str.maketrans("", "", string.punctuation))
    tokens = name.split()
    tokens = [t for t in tokens if t not in suffixes]
    return " ".join(tokens)


def resolve_funder(name_raw: str, ein: str | None = None) -> ResolutionResult:
    """Resolve a raw funder name (+ optional EIN) to an existing Funder row.

    Each call is pure (no side-effects). Callers that want to log a
    'resolved' event should do so with the returned result.
    """
    # 1. EIN match
    if ein:
        ein_clean = ein.replace("-", "")
        try:
            funder = Funder.objects.get(ein=ein_clean)
            return ResolutionResult(
                funder_id=str(funder.id), confidence="ein", matched_funder=funder
            )
        except Funder.DoesNotExist:
            pass

    normalized = normalize_funder_name(name_raw)

    # 2. Canonical name match
    try:
        funder = Funder.objects.get(canonical_name_normalized=normalized)
        return ResolutionResult(funder_id=str(funder.id), confidence="name", matched_funder=funder)
    except Funder.DoesNotExist:
        pass
    except Funder.MultipleObjectsReturned:
        pass

    # 3. Alias match
    alias = FunderAlias.objects.filter(normalized=normalized).select_related("funder").first()
    if alias:
        return ResolutionResult(
            funder_id=str(alias.funder.id), confidence="alias", matched_funder=alias.funder
        )

    return ResolutionResult(funder_id=None, confidence="none")
