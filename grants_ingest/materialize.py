"""Materializer — reads CorpusEvent rows and applies them to registry tables.

Idempotent: calling apply_events(since_event_id=0) replays the full event
stream and produces the same registry state as the incremental run.

Event handlers:
  funder_upserted          -> Funder.objects.update_or_create keyed on EIN
  funder_enriched          -> updates notes/accepts_unsolicited on existing Funder
  historical_grant_recorded -> HistoricalGrant.objects.get_or_create
"""

import logging
from decimal import Decimal, InvalidOperation

from grants_ingest.corpus_event import CorpusEvent, CorpusEventType
from grants_ingest.historical_grant import HistoricalGrant
from grants_ingest.raw_record import RawRecord
from grants_ingest.registry import Funder, FunderType

logger = logging.getLogger(__name__)


def apply_events(since_event_id: int = 0) -> int:
    """Apply all CorpusEvents with id > since_event_id to the registry tables.

    Returns the highest event id applied (or since_event_id if none found).
    Safe to call repeatedly from the same since_event_id — idempotent.
    """
    events = (
        CorpusEvent.objects.filter(id__gt=since_event_id).order_by("id").iterator(chunk_size=500)
    )
    last_id = since_event_id
    for event in events:
        try:
            _dispatch(event)
        except Exception as exc:
            logger.error("Failed to apply event %d (%s): %s", event.id, event.event_type, exc)
        last_id = event.id
    return last_id


def _dispatch(event: CorpusEvent) -> None:
    if event.event_type == CorpusEventType.FUNDER_UPSERTED:
        _apply_funder_upserted(event)
    elif event.event_type == CorpusEventType.FUNDER_ENRICHED:
        _apply_funder_enriched(event)
    elif event.event_type == CorpusEventType.HISTORICAL_GRANT_RECORDED:
        _apply_historical_grant_recorded(event)


def _apply_funder_upserted(event: CorpusEvent) -> None:
    payload = event.payload
    ein = payload.get("ein") or None
    name = payload.get("canonical_name", "")
    funder_type = payload.get("funder_type", FunderType.UNKNOWN)

    defaults = {
        "canonical_name": name,
        "canonical_name_normalized": _normalize_name(name),
        "funder_type": funder_type,
        "notes": payload.get("notes", {}),
    }

    if ein:
        Funder.objects.update_or_create(ein=ein, defaults=defaults)
    else:
        normalized = _normalize_name(name)
        existing = Funder.objects.filter(canonical_name_normalized=normalized).first()
        if existing:
            for k, v in defaults.items():
                setattr(existing, k, v)
            existing.save()
        else:
            Funder.objects.create(ein=None, **defaults)


def _apply_funder_enriched(event: CorpusEvent) -> None:
    payload = event.payload
    ein = payload.get("ein")
    if not ein:
        return
    try:
        funder = Funder.objects.get(ein=ein)
    except Funder.DoesNotExist:
        logger.warning("funder_enriched: Funder EIN %s not found, skipping", ein)
        return

    notes = funder.notes or {}
    notes.update(payload.get("notes", {}))
    funder.notes = notes

    if "accepts_unsolicited" in payload:
        funder.accepts_unsolicited = payload["accepts_unsolicited"]
    funder.save()


def _apply_historical_grant_recorded(event: CorpusEvent) -> None:
    payload = event.payload
    ein = payload.get("funder_ein")
    if not ein:
        return
    try:
        funder = Funder.objects.get(ein=ein)
    except Funder.DoesNotExist:
        logger.warning("historical_grant_recorded: Funder EIN %s not found, skipping", ein)
        return

    source_sha = event.content_sha
    if not source_sha:
        return
    try:
        source_record = RawRecord.objects.get(content_sha=source_sha)
    except RawRecord.DoesNotExist:
        logger.warning("historical_grant_recorded: RawRecord %s not found, skipping", source_sha)
        return

    try:
        amount = Decimal(str(payload.get("amount", "0")))
    except InvalidOperation:
        logger.warning("historical_grant_recorded: invalid amount %s", payload.get("amount"))
        return

    HistoricalGrant.objects.get_or_create(
        source_record=source_record,
        recipient_name_raw=payload.get("recipient_name_raw", ""),
        amount=amount,
        tax_year=payload.get("tax_year", 0),
        defaults={
            "funder": funder,
            "funder_ein": ein,
            "recipient_address_raw": payload.get("recipient_address_raw", ""),
            "recipient_ein": payload.get("recipient_ein", ""),
            "purpose": payload.get("purpose", ""),
            "relationship_flag": payload.get("relationship_flag", ""),
        },
    )


def _normalize_name(name: str) -> str:
    """Lightweight normalisation used inside the materializer for name-keyed upserts.

    The authoritative normaliser lives in resolution.py — this copy handles
    the materializer's own dedup logic and is intentionally kept in sync.
    """
    import string

    suffixes = {
        "foundation",
        "fund",
        "trust",
        "inc",
        "incorporated",
        "the",
        "corp",
        "corporation",
    }
    name = name.lower()
    name = name.translate(str.maketrans("", "", string.punctuation))
    tokens = name.split()
    tokens = [t for t in tokens if t not in suffixes]
    return " ".join(tokens)
