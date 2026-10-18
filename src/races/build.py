"""Render the static site: copy the page assets and write one JSON the page filters client-side."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from races.config import OWNER, Pick, load_picks, load_regions
from races.countries import name_of

log = logging.getLogger(__name__)


def attach_picks(events: list[dict], picks: list[Pick]) -> list[Pick]:
    """Mark events picked by someone; returns the picks that matched nothing."""
    by_key: dict[str, dict] = {}
    for event in events:
        by_key[event["id"]] = event
        for ref in event.get("sources", []):
            by_key[ref["id"]] = event
            by_key[ref["source_url"].rstrip("/")] = event
        if event["registration"].get("url"):
            by_key.setdefault(event["registration"]["url"].rstrip("/"), event)

    unmatched = []
    for pick in picks:
        event = by_key.get(pick.id or "") or by_key.get((pick.url or "").rstrip("/"))
        if event is None:
            unmatched.append(pick)
            continue
        event.setdefault("picks", []).append(
            {"person": pick.person, "status": pick.status, "note": pick.note}
        )
    return unmatched


def build_site(root: Path, data_path: Path, out: Path) -> dict:
    data = json.loads(data_path.read_text(encoding="utf-8"))
    events = data["events"]
    regions = load_regions(root / "config" / "regions.yaml")
    unmatched = attach_picks(events, load_picks(root))
    for pick in unmatched:
        log.warning("pick by %s matches no event: %s", pick.person, pick.id or pick.url)

    countries = sorted({e["country"] for e in events if e.get("country")})
    site_data = {
        "generated_at": data.get("generated_at"),
        "sources": data.get("sources", {}),
        "owner": OWNER,
        "regions": [{"key": r.key, "label": r.label, "countries": r.countries} for r in regions],
        "countries": {c: name_of(c) for c in countries},
        "events": events,
        "unmatched_picks": [
            {"person": p.person, "id": p.id, "url": p.url, "status": p.status, "note": p.note}
            for p in unmatched
        ],
    }

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(root / "site", out)
    (out / "events.json").write_text(
        json.dumps(site_data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    return {"events": len(events), "unmatched_picks": len(unmatched)}
