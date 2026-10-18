"""Fetch every source, normalise, deduplicate and write data/events.json."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path

from races.config import load_regions, region_tags
from races.dedupe import deduplicate
from races.geocode import Gazetteer
from races.http import PoliteClient
from races.models import Event
from races.sources import Source

log = logging.getLogger(__name__)


def load_events(path: Path) -> tuple[dict, list[Event]]:
    if not path.exists():
        return {}, []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data, [Event.from_dict(e) for e in data.get("events", [])]


def collect(
    sources: dict[str, Source], client: PoliteClient, previous: list[Event]
) -> tuple[list[Event], dict[str, dict]]:
    """Run each source; a failing source keeps its last good events instead of vanishing."""
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    events: list[Event] = []
    report: dict[str, dict] = {}
    for name, source in sources.items():
        try:
            parsed = source.parse(source.fetch(client), now)
            report[name] = {"status": "ok", "count": len(parsed), "fetched_at": now}
        except Exception as exc:  # one broken source must not take the calendar down
            log.error("source %s failed: %s", name, exc)
            parsed = [e for e in previous if e.source == name]
            for e in parsed:
                e.sources = [s for s in e.sources if s.source == name]
            report[name] = {"status": "stale", "count": len(parsed), "error": str(exc)}
        events += parsed
    return events, report


def enrich(events: list[Event], regions_path: Path, gazetteer: Gazetteer | None) -> None:
    regions = load_regions(regions_path)
    for event in events:
        if gazetteer and event.lat is None:
            point = gazetteer.locate(event.country, event.city, event.name)
            if point:
                event.lat, event.lon = point
        event.region_tags = region_tags(event.country, regions)


def finalise(events: list[Event], sources: dict[str, Source], today: date) -> list[Event]:
    upcoming = [e for e in events if (e.end_date or e.start_date) >= today]
    return deduplicate(upcoming, {name: s.priority for name, s in sources.items()})


def keep_unchanged_timestamps(events: list[Event], previous: list[Event]) -> None:
    """An unchanged record keeps its old fetched_at, so the daily data commit only
    touches races that actually changed instead of rewriting every line."""
    old = {e.id: e.to_dict() for e in previous}
    for event in events:
        before = old.get(event.id)
        if before is None:
            continue
        now = event.to_dict()
        if {**before, "fetched_at": ""} == {**now, "fetched_at": ""}:
            event.fetched_at = before["fetched_at"]


def write_events(path: Path, events: list[Event], report: dict[str, dict]) -> None:
    payload = {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "sources": report,
        "events": [e.to_dict() for e in events],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
