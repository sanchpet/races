"""Write the feed: one JSON with every race and its picks, which the site filters client-side."""

from __future__ import annotations

import json
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


def feed_record(event: Event) -> dict:
    """What the page reads, and no more: the feed is downloaded whole by every reader."""
    d = event.to_dict()
    record = {
        "id": d["id"],
        "name": d["name"],
        "start_date": d["start_date"],
        "end_date": d["end_date"],
        "country": d["country"],
        "city": d["city"],
        "lat": d["lat"],
        "lon": d["lon"],
        "discipline": d["discipline"],
        "distances": [
            {"km": x["km"], "climb_m": x["elevation_gain_m"]}
            if x["elevation_gain_m"]
            else {"km": x["km"]}
            for x in d["distances"]
        ],
        "sources": [{"source": s["source"], "url": s["source_url"]} for s in d["sources"]],
    }
    registration = d["registration"]
    if registration["status"] != "unknown" or registration["url"]:
        record["registration"] = {"status": registration["status"], "url": registration["url"]}
    return {k: v for k, v in record.items() if v is not None}


def attach_picks(events: list[Event], picks: list[Pick]) -> list[dict]:
    """Feed records with each event's picks; a pick that names no event stops the build."""
    index = index_events(events)
    records = {e.id: feed_record(e) for e in events}
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


def build_feed(root: Path, data_path: Path, out: Path, gazetteer: Gazetteer | None = None) -> dict:
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
        "regions": [{"key": r.key, "labels": r.labels, "countries": r.countries} for r in regions],
        "countries": {c: name_of(c) for c in countries},
        "events": records,
    }

    out.mkdir(parents=True, exist_ok=True)
    (out / "events.json").write_text(
        json.dumps(site_data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    return {"events": len(events), "picks": len(picks)}
