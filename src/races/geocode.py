"""Offline geocoding against the GeoNames cities dump (CC BY 4.0).

An offline gazetteer keeps thousands of daily lookups off public geocoding APIs,
whose usage policies forbid bulk queries.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import unicodedata
import zipfile
from pathlib import Path

import httpx

from races.http import USER_AGENT

DUMP_URL = "https://download.geonames.org/export/dump/cities1000.zip"
DEFAULT_PATH = Path(".cache/geonames/cities1000.zip")

log = logging.getLogger(__name__)


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def download(path: Path = DEFAULT_PATH) -> Path:
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    log.info("GET %s", DUMP_URL)
    with httpx.stream(
        "GET", DUMP_URL, headers={"User-Agent": USER_AGENT}, timeout=120, follow_redirects=True
    ) as resp:
        resp.raise_for_status()
        tmp = path.with_suffix(".part")
        with tmp.open("wb") as fh:
            for chunk in resp.iter_bytes():
                fh.write(chunk)
        tmp.rename(path)
    return path


class Gazetteer:
    def __init__(self, rows: list[list[str]], countries: set[str] | None = None) -> None:
        # (country, normalised name) -> (population, lat, lon); the most populous wins.
        self._index: dict[tuple[str, str], tuple[int, float, float]] = {}
        for row in rows:
            cc = row[8]
            if countries is not None and cc not in countries:
                continue
            pop = int(row[14] or 0)
            point = (pop, float(row[4]), float(row[5]))
            names = {row[1], row[2], *row[3].split(",")} if row[3] else {row[1], row[2]}
            for name in names:
                key = (cc, normalise(name))
                if key[1] and (key not in self._index or self._index[key][0] < pop):
                    self._index[key] = point

    @classmethod
    def from_zip(cls, path: Path, countries: set[str] | None = None) -> Gazetteer:
        with zipfile.ZipFile(path) as zf, zf.open("cities1000.txt") as fh:
            reader = csv.reader(
                io.TextIOWrapper(fh, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE
            )
            return cls(list(reader), countries)

    def locate(self, country: str | None, *places: str | None) -> tuple[float, float] | None:
        """Try each place whole, then its comma parts, then its word n-grams, longest first.

        Sources often give a venue ("Centro Civico Bariloche") or only the race name,
        so the n-gram pass digs the town out of them; it stays inside the country.
        """
        if not country:
            return None
        for place in places:
            for candidate in _candidates(place or ""):
                hit = self._index.get((country, candidate))
                if hit:
                    return hit[1], hit[2]
        return None


# Venue and race words that also happen to be names of some village somewhere.
_STOPWORDS = {
    "by",
    "the",
    "of",
    "de",
    "del",
    "la",
    "le",
    "and",
    "utmb",
    "hoka",
    "trail",
    "ultra",
    "race",
    "races",
    "runs",
    "run",
    "festival",
    "marathon",
    "square",
    "park",
    "church",
    "resort",
    "center",
    "centre",
    "plaza",
    "station",
    "stadium",
    "beach",
    "river",
    "garden",
    "national",
    "ski",
    "mountain",
    "mountains",
    "gate",
    "tunnel",
    "scenic",
    "world",
    "town",
    "hq",
    "series",
    "half",
    "night",
    "sky",
    "vertical",
    "km",
    "endurance",
    "running",
    "challenge",
    "cup",
}


def _candidates(place: str) -> list[str]:
    whole = normalise(place)
    if not whole:
        return []
    out = [whole]
    out += [normalise(p) for p in re.split(r"[,/()\-]", place) if normalise(p)]
    words = [w for w in whole.split() if not w.isdigit()]
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            gram = words[i : i + n]
            if n == 1 and (gram[0] in _STOPWORDS or len(gram[0]) < 4):
                continue
            if gram[0] in _STOPWORDS or gram[-1] in _STOPWORDS:
                continue
            out.append(" ".join(gram))
    return list(dict.fromkeys(out))
