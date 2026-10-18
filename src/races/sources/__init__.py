"""Source parsers share one contract: fetch raw pages, then parse them offline.

Splitting fetch from parse lets tests run every parser on recorded fixtures with
no network, and lets the CLI re-parse a cached fetch without hitting the source.
"""

from __future__ import annotations

from typing import Protocol

from races.http import PoliteClient
from races.models import Event


class Source(Protocol):
    name: str
    homepage: str
    # Lower wins when duplicates are merged: the richer record becomes primary.
    priority: int

    def fetch(self, client: PoliteClient) -> list[str]: ...

    def parse(self, pages: list[str], fetched_at: str) -> list[Event]: ...


def registry() -> dict[str, Source]:
    from races.sources import duv, intervals, traillab, utmb

    sources: list[Source] = [traillab.TrailLab(), utmb.Utmb(), intervals.Intervals(), duv.Duv()]
    return {s.name: s for s in sources}
