"""Render the static site: copy the page assets and write one JSON the page filters client-side."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from races.config import OWNER, Pick, PicksError, load_picks, load_regions
from races.countries import name_of
from races.dedupe import fold_in
from races.geocode import Gazetteer, open_gazetteer
from races.models import Event, index_events
from races.pipeline import enrich


def inline_events(
    picks: list[Pick], regions_path: Path, gazetteer: Gazetteer | None
) -> list[Event]:
    """Races picks define themselves, one per URL, placed and tagged like source events."""
    events = list({p.event.source_id: p.event for p in reversed(picks) if p.event}.values())
    if gazetteer is None and any(e.lat is None for e in events):
        gazetteer = open_gazetteer({e.country for e in events if e.country})
    enrich(events, regions_path, gazetteer)
    return events


def attach_picks(events: list[Event], picks: list[Pick]) -> list[dict]:
    """Site records with each event's picks; a pick that names no event stops the build."""
    index = index_events(events)
    records = {e.id: e.to_dict() for e in events}
    missing = []
    for pick in picks:
        event = pick.find(index)
        if event is None:
            missing.append(pick)
            continue
        records[event.id].setdefault("picks", []).append(
            {"person": pick.person, "status": pick.status, "note": pick.note}
        )
    if missing:
        lines = [f"  {p.origin}: {p.id or p.url}" for p in missing]
        raise PicksError(
            "picks that match no race (use the event id from the site's Details, "
            "or one of its source URLs):\n" + "\n".join(lines)
        )
    return list(records.values())


def build_site(root: Path, data_path: Path, out: Path, gazetteer: Gazetteer | None = None) -> dict:
    """Picks are applied here, not at fetch, so a picks.yaml edit shows on the next build."""
    data = json.loads(data_path.read_text(encoding="utf-8"))
    regions_path = root / "config" / "regions.yaml"
    regions = load_regions(regions_path)
    picks = load_picks(root)
    events = [Event.from_dict(e) for e in data["events"]]
    events = fold_in(events, inline_events(picks, regions_path, gazetteer))
    records = attach_picks(events, picks)

    countries = sorted({e.country for e in events if e.country})
    site_data = {
        "generated_at": data.get("generated_at"),
        "sources": data.get("sources", {}),
        "owner": OWNER,
        "regions": [{"key": r.key, "label": r.label, "countries": r.countries} for r in regions],
        "countries": {c: name_of(c) for c in countries},
        "events": records,
    }

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(root / "site", out)
    (out / "events.json").write_text(
        json.dumps(site_data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    return {"events": len(events), "picks": len(picks)}
