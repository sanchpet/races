"""Merge the same race listed by several sources, keeping every source as provenance."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import timedelta
from difflib import SequenceMatcher

from races.geocode import normalise
from races.models import Event

NAME_THRESHOLD = 0.82
DATE_SLACK = timedelta(days=1)

# Words that differ between listings of the same race and carry no identity.
_NOISE = re.compile(
    r"\b(\d+(st|nd|rd|th)|20\d\d|by utmb|utmb|edition|the|international|intl|race|"
    r"km|k|mi|miles?|\d+)\b"
)


def name_key(name: str) -> str:
    return re.sub(r"\s+", " ", _NOISE.sub(" ", normalise(name))).strip()


def _distances_compatible(a: Event, b: Event) -> bool:
    """Both list distances but share none: a marathon and a 50 km ultra in one city."""
    if not a.distances or not b.distances:
        return True
    return any(
        abs(x.km - y.km) <= max(2.0, 0.05 * max(x.km, y.km))
        for x in a.distances
        for y in b.distances
    )


def similar(a: Event, b: Event) -> bool:
    # A source never lists one race twice; parsers already fold their own rows.
    if {s.source for s in a.sources} & {s.source for s in b.sources}:
        return False
    if a.country and b.country and a.country != b.country:
        return False
    if abs(a.start_date - b.start_date) > DATE_SLACK:
        return False
    ka, kb = name_key(a.name), name_key(b.name)
    if not ka or not kb:
        return normalise(a.name) == normalise(b.name)
    if not _distances_compatible(a, b):
        return False
    shorter, longer = sorted((ka, kb), key=len)
    if ka == kb or (len(shorter) >= 8 and shorter in longer):
        return True
    return SequenceMatcher(None, ka, kb).ratio() >= NAME_THRESHOLD


def merge_into(primary: Event, other: Event) -> None:
    known = {s.id for s in primary.sources}
    primary.sources.extend(s for s in other.sources if s.id not in known)
    for dist in other.distances:
        twin = next((d for d in primary.distances if abs(d.km - dist.km) < 1.5), None)
        if twin is None:
            primary.distances.append(dist)
        elif twin.elevation_gain_m is None:
            twin.elevation_gain_m = dist.elevation_gain_m
    for attr in ("country", "city", "lat", "lon"):
        if getattr(primary, attr) is None:
            setattr(primary, attr, getattr(other, attr))
    if primary.registration.status == "unknown" and other.registration.status != "unknown":
        primary.registration = other.registration
    if primary.discipline in ("other", "ultra") and other.discipline not in ("other", "ultra"):
        primary.discipline = other.discipline
    primary.end_date = max(
        primary.end_date or primary.start_date, other.end_date or other.start_date
    )


def deduplicate(events: list[Event], priority: dict[str, int]) -> list[Event]:
    """Greedy merge within same-day buckets; the higher-priority source stays primary."""
    ordered = sorted(events, key=lambda e: (priority.get(e.source, 99), e.start_date, e.name))
    by_day: dict = defaultdict(list)
    kept: list[Event] = []
    for event in ordered:
        match = None
        for offset in (-1, 0, 1):
            day = event.start_date + timedelta(days=offset)
            match = next((k for k in by_day[day] if similar(k, event)), None)
            if match:
                break
        if match:
            merge_into(match, event)
        else:
            kept.append(event)
            by_day[event.start_date].append(event)
    return sorted(kept, key=lambda e: (e.start_date, e.name))
