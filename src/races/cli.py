"""Command line: `races fetch` refreshes data/events.json, `races build` renders dist/."""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from races.build import build_site
from races.config import load_picks, load_regions
from races.geocode import Gazetteer, download
from races.http import PoliteClient
from races.pipeline import (
    carry_picked,
    collect,
    enrich,
    finalise,
    keep_unchanged_timestamps,
    load_events,
    write_events,
)
from races.sources import registry

log = logging.getLogger("races")


def cmd_fetch(args: argparse.Namespace) -> int:
    sources = registry()
    if args.only:
        unknown = set(args.only) - set(sources)
        if unknown:
            log.error("unknown sources: %s (known: %s)", ", ".join(unknown), ", ".join(sources))
            return 2
        sources = {k: v for k, v in sources.items() if k in args.only}

    picks = load_picks(args.root)
    _, previous = load_events(args.data)
    with PoliteClient(cache_dir=None if args.no_cache else Path(".cache/raw")) as client:
        events, report = collect(sources, client, previous)
    if args.only:
        # A partial fetch must not drop the sources it skipped.
        kept = [e for e in previous if e.source not in sources]
        for e in kept:
            e.sources = [s for s in e.sources if s.source not in sources]
        events += kept
    events += carry_picked(events, previous, picks)

    gazetteer = None
    if not args.no_geocode:
        try:
            countries = {e.country for e in events if e.country}
            gazetteer = Gazetteer.from_zip(download(), countries)
        except Exception as exc:  # map pins are optional; the calendar still works
            log.error("geocoding disabled: %s", exc)

    enrich(events, args.root / "config" / "regions.yaml", gazetteer)
    merged = finalise(events, sources, date.today(), picks)
    keep_unchanged_timestamps(merged, previous)
    write_events(args.data, merged, report)

    print_summary(merged, report, args.root)
    return 0 if any(r["status"] == "ok" for r in report.values()) else 1


def print_summary(events, report: dict, root: Path) -> None:
    print(f"{len(events)} events after deduplication")
    for name, r in report.items():
        print(f"  source {name:10} {r['status']:6} {r['count']:6} parsed")
    by_source = Counter(s.source for e in events for s in e.sources)
    print("  provenance (events listing each source):", dict(by_source))
    print(f"  merged across sources: {sum(1 for e in events if len(e.sources) > 1)}")
    print(f"  with map position: {sum(1 for e in events if e.lat is not None)}")
    for region in load_regions(root / "config" / "regions.yaml"):
        n = sum(1 for e in events if region.key in e.region_tags)
        print(f"  region {region.label:22} {n:6}")


def cmd_build(args: argparse.Namespace) -> int:
    stats = build_site(args.root, args.data, args.out)
    print(f"built {args.out}: {stats['events']} events, {stats['unmatched_picks']} unmatched picks")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="races")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--data", type=Path, default=Path("data/events.json"))
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="fetch sources and write data/events.json")
    fetch.add_argument("--only", nargs="+", help="fetch only these sources")
    fetch.add_argument("--no-cache", action="store_true", help="ignore the raw response cache")
    fetch.add_argument("--no-geocode", action="store_true", help="skip GeoNames lookup")
    fetch.set_defaults(func=cmd_fetch)

    build = sub.add_parser("build", help="render the static site")
    build.add_argument("--out", type=Path, default=Path("dist"))
    build.set_defaults(func=cmd_build)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
