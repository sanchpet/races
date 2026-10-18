"""UTMB World Series: the JSON search endpoint behind utmb.world/races.

robots.txt allows everything. The terms forbid reproducing texts and images, so
only facts (name, date, place, distance, climb, registration status) are kept and
every event links back to its official page.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime
from urllib.parse import urlsplit

from races.countries import from_name
from races.http import PoliteClient
from races.models import Distance, Event, Registration, classify

API = "https://api.utmb.world/search/races?lang=en&limit={limit}&offset={offset}"
PAGE = 100

STATUS = {
    "registration_open": "open",
    "registration_sold_out": "closed",
    "registration_closed": "closed",
    "available_soon": "upcoming",
}

_ORDINAL = re.compile(r"(\d+)(st|nd|rd|th)\b")


def parse_date(text: str) -> date | None:
    try:
        return datetime.strptime(_ORDINAL.sub(r"\1", text.strip()), "%d %B %Y").date()
    except (ValueError, AttributeError):
        return None


def _stat(race: dict, name: str) -> float | None:
    for stat in (race.get("details") or {}).get("statsUp") or []:
        if stat.get("name") == name and stat.get("value") not in (None, ""):
            try:
                return float(stat["value"])
            except (TypeError, ValueError):
                return None
    return None


class Utmb:
    name = "utmb"
    homepage = "https://utmb.world/races"
    priority = 20

    def fetch(self, client: PoliteClient) -> list[str]:
        pages = []
        offset = 0
        while True:
            text = client.get_text(API.format(limit=PAGE, offset=offset))
            pages.append(text)
            data = json.loads(text)
            offset += PAGE
            if offset >= data.get("nbHits", 0) or not data.get("races"):
                return pages

    def parse(self, pages: list[str], fetched_at: str) -> list[Event]:
        # The API lists each distance as its own race; group them back into events
        # by the event's own site (e.g. tenerife.utmb.world) and edition year.
        groups: dict[tuple[str, int], list[tuple[date, dict]]] = defaultdict(list)
        for page in pages:
            for race in json.loads(page).get("races", []):
                start = parse_date(race.get("startDate") or "")
                slug = race.get("slug") or ""
                host = urlsplit(slug).netloc
                if not start or not host:
                    continue
                groups[(host, start.year)].append((start, race))

        events = []
        for (host, year), races in groups.items():
            races.sort(key=lambda r: r[0])
            first = races[0][1]
            location = (first.get("startLocation") or "").split(", ")
            country = from_name(location[-1]) if location else None
            city = location[0] if len(location) > 1 else None

            distances = []
            statuses = set()
            all_road = True
            for _, race in races:
                km = _stat(race, "distance")
                if km:
                    gain = _stat(race, "elevationGain")
                    distances.append(Distance(km=km, elevation_gain_m=int(gain) if gain else None))
                status = (race.get("raceStatus") or {}).get("status")
                statuses.add(STATUS.get(status, "unknown"))
                if "road" not in (race.get("playgrounds") or []):
                    all_road = False

            # One open distance makes the event open for planning purposes.
            reg_status = next(
                (s for s in ("open", "upcoming", "closed") if s in statuses), "unknown"
            )
            name = first["name"].split(" - ")[0].strip()
            events.append(
                Event(
                    name=name,
                    start_date=races[0][0],
                    end_date=races[-1][0],
                    source=self.name,
                    source_id=f"{host}:{year}",
                    source_url=f"https://{host}/",
                    country=country,
                    city=city,
                    discipline=classify(name, terrain="road" if all_road else "trail"),
                    distances=distances,
                    registration=Registration(status=reg_status, url=f"https://{host}/"),
                    fetched_at=fetched_at,
                )
            )
        return events
