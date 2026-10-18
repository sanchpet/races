"""TrailLab: the main trail race organiser in Georgia (Kazbegi, Mestia, Lisi, Tbilisi).

robots.txt allows everything but /wp-admin/. The site has no feed or REST type for
races, so the homepage's "upcoming" blocks (heading, date, Detail link) are read, and
each linked race page is read once for its distances.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime

from races.http import PoliteClient
from races.models import Distance, Event, classify

HOME = "https://www.traillab.ge/"

_BLOCK = re.compile(
    r'<h2 class="elementor-heading-title[^"]*">(?P<name>[^<]+)</h2>.{0,600}?'
    r"<p>(?P<date>[^<]*\d{4})</p>.{0,900}?"
    r'<a class="elementor-button[^"]*" href="(?P<url>https://(?:www\.)?traillab\.ge/[^"]+)"',
    re.S,
)
_DATE = re.compile(r"^(\d{1,2})(?:\s*-\s*(\d{1,2}))?\s+([A-Za-z]+)\s+(\d{4})$")
# Race pages print distances in capitals ("43KM Trail Marathon"); lower-case "k"
# elsewhere on the page is noise.
_KM = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s?KM\b")
_TAGS = re.compile(r"<script.*?</script>|<style.*?</style>|<[^>]+>", re.S)

# Towns for the map; race names alone do not resolve in a gazetteer.
TOWNS = {"kazbegi": "Stepantsminda", "mestia": "Mestia", "lisi": "Tbilisi", "tbilisi": "Tbilisi"}


def parse_dates(text: str) -> tuple[date, date] | None:
    m = _DATE.match(" ".join(text.split()))
    if not m:
        return None
    try:
        end = datetime.strptime(f"{m[2] or m[1]} {m[3]} {m[4]}", "%d %B %Y").date()
    except ValueError:
        return None
    return end.replace(day=int(m[1])), end


def canonical(url: str) -> str:
    return url.replace("https://traillab.ge/", HOME).rstrip("/") + "/"


def town_for(name: str, url: str) -> str | None:
    key = (name + " " + url).lower()
    return next((town for word, town in TOWNS.items() if word in key), None)


class TrailLab:
    name = "traillab"
    homepage = HOME
    priority = 10

    def fetch(self, client: PoliteClient) -> list[str]:
        home = client.get_text(HOME)
        urls = dict.fromkeys(canonical(m["url"]) for m in _BLOCK.finditer(home))
        return [home] + [f"<!-- url: {u} -->\n" + client.get_text(u) for u in urls]

    def parse(self, pages: list[str], fetched_at: str) -> list[Event]:
        home, details = pages[0], pages[1:]
        detail_text = {}
        for page in details:
            url = re.match(r"<!-- url: (\S+) -->", page)
            if url:
                detail_text[url[1]] = html.unescape(_TAGS.sub(" ", page))

        events = {}
        for block in _BLOCK.finditer(home):
            dates = parse_dates(html.unescape(block["date"]))
            if not dates:
                continue
            name = " ".join(html.unescape(block["name"]).split()).title()
            url = canonical(block["url"])
            if (url, dates[0]) in events:
                continue
            kms = sorted({float(k) for k in _KM.findall(detail_text.get(url, ""))})
            distances = [Distance(km=k) for k in kms if 0 < k < 400]
            events[(url, dates[0])] = Event(
                name=name,
                start_date=dates[0],
                end_date=dates[1],
                source=self.name,
                source_id=f"{url.rstrip('/').rsplit('/', 1)[-1]}:{dates[0].year}",
                source_url=url,
                country="GE",
                city=town_for(name, url),
                discipline=classify(name, terrain="trail"),
                distances=distances,
                fetched_at=fetched_at,
            )
        return list(events.values())
