"""Load the editable inputs: region groups and people's picks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

PICK_STATUSES = ("planned", "registered", "done")
OWNER = "owner"


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


def _load_pick_file(path: Path, person: str) -> list[Pick]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a list of picks")
    picks = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict) or not (entry.get("id") or entry.get("url")):
            raise ValueError(f"{path}: pick #{i + 1} needs an id or a url")
        status = entry.get("status", "planned")
        if status not in PICK_STATUSES:
            raise ValueError(f"{path}: pick #{i + 1} has unknown status {status!r}")
        picks.append(
            Pick(
                person=person,
                id=entry.get("id"),
                url=entry.get("url"),
                status=status,
                note=entry.get("note"),
            )
        )
    return picks


def load_picks(root: Path) -> list[Pick]:
    """The owner's picks.yaml, plus picks/<name>.yaml per friend (phase 2)."""
    picks = []
    owner_file = root / "picks.yaml"
    if owner_file.exists():
        picks += _load_pick_file(owner_file, OWNER)
    friends_dir = root / "picks"
    if friends_dir.is_dir():
        for path in sorted(friends_dir.glob("*.yaml")):
            picks += _load_pick_file(path, path.stem)
    return picks
