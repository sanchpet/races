"""Load the editable inputs: region groups and people's picks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import yaml

from races.countries import from_name
from races.models import DISCIPLINES, Distance, Event, classify

PICK_STATUSES = ("planned", "registered", "done")
PICK_KEYS = {"id", "url", "status", "note"}
# A pick with a name defines its own race, for one no source lists.
INLINE_KEYS = {
    "name",
    "date",
    "end_date",
    "country",
    "city",
    "lat",
    "lon",
    "distances",
    "discipline",
}
OWNER = "owner"
PICKS_SOURCE = "picks"


class PicksError(ValueError):
    """A picks file the build cannot honour; the message names the file and the entry."""


@dataclass
class Region:
    key: str
    label: str
    countries: list[str]


@dataclass
class Pick:
    person: str
    id: str | None = None
    url: str | None = None
    status: str = "planned"
    note: str | None = None
    origin: str = ""
    event: Event | None = None

    def handles(self) -> set[str]:
        return {k for k in (self.id, (self.url or "").rstrip("/")) if k}

    def find(self, index: dict[str, Event]) -> Event | None:
        return next((index[k] for k in (self.id, (self.url or "").rstrip("/")) if k in index), None)


def load_regions(path: Path) -> list[Region]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    regions = []
    for key, body in raw.items():
        countries = body.get("countries", [])
        bad = [c for c in countries if not (isinstance(c, str) and len(c) == 2)]
        if bad:
            # Catches YAML's Norway problem: an unquoted NO loads as False.
            raise ValueError(f"{path}: region {key!r} has invalid country codes {bad!r}")
        countries = [c.upper() for c in countries]
        regions.append(Region(key=key, label=body.get("label", key), countries=countries))
    return regions


def region_tags(country: str | None, regions: list[Region]) -> list[str]:
    if not country:
        return []
    return [r.key for r in regions if country in r.countries]


def _load_pick_file(path: Path, person: str, label: str) -> list[Pick]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(raw, list):
        raise PicksError(f"{label}: expected a list of picks")
    picks = []
    for i, entry in enumerate(raw):
        where = f"{label} #{i + 1}"
        if not isinstance(entry, dict):
            raise PicksError(f"{where}: expected a mapping with an id or a url")
        unknown = sorted(set(entry) - PICK_KEYS - (INLINE_KEYS if "name" in entry else set()))
        if unknown:
            raise PicksError(f"{where}: unknown keys {unknown}")
        for key in ("id", "url"):
            # An all-digit id loads as a number (a leading 0 even as octal), so it never matches.
            if entry.get(key) is not None and not isinstance(entry[key], str):
                raise PicksError(f"{where}: the {key} loaded as a number; put it in quotes")
        event = _inline_event(entry, where) if "name" in entry else None
        if not (entry.get("id") or entry.get("url")):
            raise PicksError(f"{where}: needs an id or a url")
        status = entry.get("status", "planned")
        if status not in PICK_STATUSES:
            raise PicksError(f"{where}: unknown status {status!r}, expected one of {PICK_STATUSES}")
        picks.append(
            Pick(
                person=person,
                id=entry.get("id"),
                url=entry.get("url"),
                status=status,
                note=entry.get("note"),
                origin=where,
                event=event,
            )
        )
    return picks


def _date(value: object, where: str, key: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise PicksError(f"{where}: {key} {value!r} is not a YYYY-MM-DD date") from None


def _distance(value: object, where: str) -> Distance:
    if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
        return Distance(km=float(value))
    if isinstance(value, dict) and set(value) <= {"km", "climb_m"} and "km" in value:
        climb = value.get("climb_m")
        return Distance(km=float(value["km"]), elevation_gain_m=int(climb) if climb else None)
    raise PicksError(f"{where}: distance {value!r} is not a number of km or {{km, climb_m}}")


def _inline_event(entry: dict, where: str) -> Event:
    """The race a pick defines itself; source "picks" marks where it came from."""
    missing = [k for k in ("name", "date", "country", "url") if not entry.get(k)]
    if missing:
        raise PicksError(f"{where}: a race defined in a pick needs {', '.join(missing)}")
    country = from_name(str(entry["country"]))
    if country is None:
        raise PicksError(f"{where}: unknown country {entry['country']!r}, use an ISO code")
    start = _date(entry["date"], where, "date")
    end = _date(entry["end_date"], where, "end_date") if entry.get("end_date") else start
    if end < start:
        raise PicksError(f"{where}: end_date is before date")
    if ("lat" in entry) != ("lon" in entry):
        raise PicksError(f"{where}: give both lat and lon, or neither")
    lat = float(entry["lat"]) if "lat" in entry else None
    lon = float(entry["lon"]) if "lon" in entry else None
    if lat is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise PicksError(f"{where}: lat/lon {lat}, {lon} is off the globe")
    distances = [_distance(d, where) for d in entry.get("distances") or []]
    name = str(entry["name"])
    discipline = entry.get("discipline") or classify(
        name, max_km=max((d.km for d in distances), default=0.0)
    )
    if discipline not in DISCIPLINES:
        raise PicksError(f"{where}: unknown discipline {discipline!r}, expected {DISCIPLINES}")
    url = entry["url"]
    return Event(
        name=name,
        start_date=start,
        end_date=end,
        source=PICKS_SOURCE,
        source_id=url.rstrip("/"),
        source_url=url,
        country=country,
        city=entry.get("city"),
        lat=lat,
        lon=lon,
        discipline=discipline,
        distances=distances,
    )


def load_picks(root: Path) -> list[Pick]:
    """The owner's picks.yaml, plus picks/<name>.yaml per friend (phase 2)."""
    picks = []
    owner_file = root / "picks.yaml"
    if owner_file.exists():
        picks += _load_pick_file(owner_file, OWNER, owner_file.name)
    friends_dir = root / "picks"
    if friends_dir.is_dir():
        for path in sorted(friends_dir.glob("*.yaml")):
            picks += _load_pick_file(path, path.stem, f"picks/{path.name}")
    return picks
