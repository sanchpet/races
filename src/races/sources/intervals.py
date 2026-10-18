"""Intervals.icu public event calendar: one page per country, running events kept.

robots.txt allows everything and no site terms restrict automated reading (the API
terms are permissive too). About 70 country pages, fetched at the polite default rate.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime

from races.http import PoliteClient
from races.models import Event, classify, distances_from_text

BASE = "https://www.intervals.icu"
INDEX = BASE + "/events/"
RUNNING = {"Run": None, "Trail Run": "trail"}

_COUNTRY_LINK = re.compile(r'href="/events/([A-Z]{2})/"')
_CARD = re.compile(r'<a href="/events/(\d+)/" class="event-card"[^>]*>(.*?)</a>', re.S)
_DATE = re.compile(r'class="event-date"[^>]*>\s*<span[^>]*></span>\s*([^<]+?)\s*</span>', re.S)
_NAME = re.compile(r'class="event-name"[^>]*>(.*?)</h3>', re.S)
_PLACE = re.compile(r'class="mdi mdi-map-marker"[^>]*></span>\s*([^<]+?)\s*</span>', re.S)
_SPORT = re.compile(r"<i class=\"[^\"]*\"[^>]*></i>\s*([^<]+?)\s*</span>")
_PAGE_COUNTRY = re.compile(
    r'<link rel="canonical" href="https://www\.intervals\.icu/events/([A-Z]{2})/"'
)


def parse_date(text: str) -> date | None:
    try:
        return datetime.strptime(text.strip(), "%b %d, %Y").date()
    except ValueError:
        return None


def city_from_address(address: str) -> str | None:
    """'Pirelli Stadium, Princess Way, Burton-on-Trent DE13 0AR, UK' -> 'Burton-on-Trent'."""
    parts = [p.strip() for p in address.split(",")][:-1]  # last part is the country
    for part in reversed(parts):
        words = [w for w in part.split() if not any(c.isdigit() for c in w)]
        # Postcodes like "DE13 0AR" leave short all-caps fragments behind.
        words = [w for w in words if not (w.isupper() and len(w) <= 3)]
        if words:
            return " ".join(words)
    return None


class Intervals:
    name = "intervals"
    homepage = INDEX
    priority = 25

    def fetch(self, client: PoliteClient) -> list[str]:
        index = client.get_text(INDEX)
        countries = sorted(set(_COUNTRY_LINK.findall(index)))
        return [client.get_text(f"{INDEX}{cc}/") for cc in countries]

    def parse(self, pages: list[str], fetched_at: str) -> list[Event]:
        events = []
        for page in pages:
            canonical = _PAGE_COUNTRY.search(page)
            country = canonical[1] if canonical else None
            for event_id, body in _CARD.findall(page):
                sports = set(_SPORT.findall(body))
                terrains = [RUNNING[s] for s in sports if s in RUNNING]
                if not terrains:
                    continue
                when = _DATE.search(body)
                title = _NAME.search(body)
                start = parse_date(html.unescape(when[1])) if when else None
                if not start or not title:
                    continue
                name = html.unescape(title[1]).strip()
                place = _PLACE.search(body)
                distances = distances_from_text(name)
                max_km = max((d.km for d in distances), default=0)
                discipline = classify(
                    name, terrain="trail" if "trail" in terrains else None, max_km=max_km
                )
                events.append(
                    Event(
                        name=name,
                        start_date=start,
                        source=self.name,
                        source_id=event_id,
                        source_url=f"{BASE}/events/{event_id}/",
                        country=country,
                        city=city_from_address(html.unescape(place[1])) if place else None,
                        discipline="road" if discipline == "other" else discipline,
                        distances=distances,
                        fetched_at=fetched_at,
                    )
                )
        return events
