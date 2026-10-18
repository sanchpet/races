"""DUV ultra-marathon statistics: the worldwide calendar of upcoming ultras.

robots.txt disallows everything except *.php pages and asks for a 20 s crawl
delay; the calendar is a few PHP pages of 1000 rows each, so a full fetch is a
handful of requests. No terms of use beyond a copyright line, so only facts are
kept and every event links back to its DUV page.
"""

from __future__ import annotations

import html
import re
from datetime import date

from races.countries import from_ioc
from races.geocode import normalise
from races.http import PoliteClient
from races.models import Distance, Event, classify

BASE = "https://statistik.d-u-v.org/"
CALENDAR = BASE + "calendar.php?language=EN&page={page}"
MILE_KM = 1.609344

_ROW = re.compile(r"<tr class='(?:even|odd)'>(.*?)</tr>", re.S)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_LINK = re.compile(r"eventdetail\.php\?event=(\d+)'>(.*?)</a>", re.S)
_PLACE = re.compile(r"^(.*?)\s*\(([A-Z]{3})\)\s*$")


def parse_dates(text: str) -> tuple[date, date] | None:
    """DUV writes 24.10.2026, 17.-18.10.2026, 30.10.-01.11.2026 or 31.12.2026-01.01.2027.

    Typos such as 07.-00.11.2026 occur in the data; such rows are skipped, and an
    impossible end date (year 0000) falls back to the start date.
    """
    text = text.strip().replace(".-", "-")
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", text)
    try:
        if m:
            d = date(int(m[3]), int(m[2]), int(m[1]))
            return d, d
        m = re.match(r"^(\d{2})\.?(?:(\d{2})\.?)?(?:(\d{4}))?-(\d{2})\.(\d{2})\.(\d{4})$", text)
        if not m:
            return None
        end_year = int(m[6]) or int(m[3] or 0)
        start = date(int(m[3] or end_year), int(m[2] or m[5]), int(m[1]))
        try:
            end = date(end_year, int(m[5]), int(m[4]))
        except ValueError:
            end = start
        return start, max(start, end)
    except ValueError:
        return None


def parse_distance(text: str) -> float | None:
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(km|mi)$", text.strip())
    if not m:
        return None  # timed events (6h, 24h, 6d) have no fixed distance
    km = float(m[1]) * (MILE_KM if m[2] == "mi" else 1)
    return round(km, 1)


class Duv:
    name = "duv"
    homepage = "https://statistik.d-u-v.org/calendar.php"
    priority = 30

    def fetch(self, client: PoliteClient) -> list[str]:
        first = client.get_text(CALENDAR.format(page=1))
        last = max(
            (int(p) for p in re.findall(r"calendar\.php\?[^'\"]*page=(\d+)", first)), default=1
        )
        return [first] + [client.get_text(CALENDAR.format(page=p)) for p in range(2, last + 1)]

    def parse(self, pages: list[str], fetched_at: str) -> list[Event]:
        events: dict[tuple, Event] = {}
        for page in pages:
            for row in _ROW.findall(page):
                cells = _CELL.findall(row)
                if len(cells) < 4:
                    continue
                dates = parse_dates(html.unescape(cells[0]))
                link = _LINK.search(cells[1])
                if not dates or not link:
                    continue
                event_id, name = link[1], html.unescape(link[2]).strip()
                place = _PLACE.match(html.unescape(cells[3]).strip())
                city = place[1].split(",")[0].strip() if place else None
                country = from_ioc(place[2]) if place else None
                km = parse_distance(html.unescape(cells[2]))

                # One row per distance: fold rows of the same event together.
                key = (dates[0], name, city, country)
                event = events.get(key)
                if event is None:
                    event = Event(
                        name=name,
                        start_date=dates[0],
                        end_date=dates[1],
                        source=self.name,
                        source_id=event_id,
                        source_url=f"{BASE}eventdetail.php?event={event_id}",
                        country=country,
                        city=city,
                        fetched_at=fetched_at,
                    )
                    events[key] = event
                if km and all(d.km != km for d in event.distances):
                    event.distances.append(Distance(km=km))

        return fold_editions(list(events.values()))


# Words too generic to tie two DUV rows to one event.
_GENERIC = {
    "trail",
    "ultra",
    "ultramarathon",
    "marathon",
    "race",
    "run",
    "running",
    "backyard",
    "night",
    "festival",
    "medium",
    "advanced",
    "international",
    "hour",
    "hours",
    "stundenlauf",
    "miles",
    "mile",
    "path",
    "nature",
    "challenge",
    "endurance",
    "short",
    "long",
    "classic",
    "edition",
    "series",
    "mountain",
    "the",
    "and",
    "des",
    "der",
    "die",
    "del",
    "della",
}


def _significant(name: str) -> set[str]:
    words = normalise(name).split()
    return {w for w in words if len(w) >= 4 and w not in _GENERIC and not w[0].isdigit()}


def _common_name(names: list[str], flagship: str) -> str:
    split = [n.split() for n in names]
    prefix = []
    for words in zip(*split, strict=False):
        if len(set(words)) != 1:
            break
        prefix.append(words[0])
    joined = " ".join(prefix).rstrip(" -–(:,")
    return joined if len(prefix) >= 2 else flagship


def fold_editions(events: list[Event]) -> list[Event]:
    """DUV lists each distance of an event as its own row, often under its own name
    ("Marmaris Ultra Trail 100km", "Marmaris Medium Trail 48km"). Rows in the same town
    within three days that share a distinctive word are folded into one event."""
    events = sorted(events, key=lambda e: e.start_date)
    kept: list[Event] = []
    names: dict[int, list[str]] = {}
    flagship: dict[int, tuple[float, str]] = {}
    for event in events:
        words = _significant(event.name)
        target = next(
            (
                k
                for k in reversed(kept)
                if k.city == event.city
                and k.country == event.country
                and (event.start_date - k.start_date).days <= 3
                and words & _significant(" ".join(names[id(k)]))
            ),
            None,
        )
        if target is None:
            kept.append(event)
            names[id(event)] = [event.name]
            flagship[id(event)] = (event.max_km, event.name)
            continue
        names[id(target)].append(event.name)
        flagship[id(target)] = max(flagship[id(target)], (event.max_km, event.name))
        target.end_date = max(target.end_date, event.end_date)
        for dist in event.distances:
            if all(d.km != dist.km for d in target.distances):
                target.distances.append(dist)
    for event in kept:
        # Without a shared prefix, the longest distance's name stands for the event.
        event.name = _common_name(names[id(event)], flagship[id(event)][1])
        # Every row's name counts: "Medium Trail" marks the whole event as trail.
        event.discipline = classify(" ".join(names[id(event)]), max_km=max(event.max_km, 43.0))
    return kept
