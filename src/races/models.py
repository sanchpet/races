"""The normalised event schema every source parser produces."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import date

DISCIPLINES = ("trail", "road", "ultra", "sky", "other")
REGISTRATION_STATUSES = ("open", "closed", "upcoming", "unknown")
MARATHON_KM = 42.195


def make_id(source: str, source_id: str) -> str:
    """Stable id: the same race from the same source keeps its id across runs."""
    return hashlib.sha1(f"{source}:{source_id}".encode()).hexdigest()[:12]


@dataclass
class Distance:
    km: float
    elevation_gain_m: int | None = None


@dataclass
class Registration:
    status: str = "unknown"
    opens: str | None = None
    closes: str | None = None
    url: str | None = None


@dataclass
class SourceRef:
    """Provenance: one source that lists this event."""

    source: str
    source_id: str
    source_url: str
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = make_id(self.source, self.source_id)


@dataclass
class Event:
    name: str
    start_date: date
    source: str
    source_id: str
    source_url: str
    end_date: date | None = None
    country: str | None = None
    city: str | None = None
    lat: float | None = None
    lon: float | None = None
    discipline: str = "other"
    distances: list[Distance] = field(default_factory=list)
    registration: Registration = field(default_factory=Registration)
    region_tags: list[str] = field(default_factory=list)
    sources: list[SourceRef] = field(default_factory=list)
    fetched_at: str = ""
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = make_id(self.source, self.source_id)
        if not self.sources:
            self.sources = [SourceRef(self.source, self.source_id, self.source_url, self.id)]
        if self.end_date is None:
            self.end_date = self.start_date

    @property
    def max_km(self) -> float:
        return max((d.km for d in self.distances), default=0.0)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start_date"] = self.start_date.isoformat()
        d["end_date"] = (self.end_date or self.start_date).isoformat()
        d["distances"] = sorted(d["distances"], key=lambda x: x["km"])
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Event:
        d = dict(d)
        d["start_date"] = date.fromisoformat(d["start_date"])
        d["end_date"] = date.fromisoformat(d["end_date"]) if d.get("end_date") else None
        d["distances"] = [Distance(**x) for x in d.get("distances", [])]
        d["registration"] = Registration(**d.get("registration", {}))
        d["sources"] = [SourceRef(**x) for x in d.get("sources", [])]
        return cls(**d)


def classify(name: str, *, terrain: str | None = None, max_km: float = 0.0) -> str:
    """Pick one discipline label; 'ultra' only when terrain is unknown.

    The site's ultra filter works on distance, so a 100 km trail stays 'trail'.
    """
    lowered = name.lower()
    if terrain in DISCIPLINES and terrain != "other":
        return terrain
    if "sky" in lowered or "vertical" in lowered:
        return "sky"
    if "trail" in lowered or "mountain" in lowered:
        return "trail"
    if max_km > MARATHON_KM:
        return "ultra"
    if any(w in lowered for w in ("marathon", "road", "10k", "5k", "run ")):
        return "road"
    return "other"


_KM = re.compile(r"(?<![\d.])(\d+(?:[.,]\d+)?)\s*(km|k)\b", re.I)
_MI = re.compile(r"(?<![\d.])(\d+(?:[.,]\d+)?)\s*(mi|miles?)\b", re.I)


def distances_from_text(text: str) -> list[Distance]:
    """Distances stated in a race name or blurb: '10K', '43KM', '50 miles', 'half marathon'."""
    kms: set[float] = set()
    for value, _ in _KM.findall(text):
        kms.add(round(float(value.replace(",", ".")), 1))
    for value, _ in _MI.findall(text):
        kms.add(round(float(value.replace(",", ".")) * 1.609344, 1))
    lowered = text.lower()
    if "half marathon" in lowered or "half-marathon" in lowered:
        kms.add(21.1)
    elif "marathon" in lowered and "ultramarathon" not in lowered and not kms:
        kms.add(MARATHON_KM)
    return [Distance(km=k) for k in sorted(kms) if 0 < k < 1000]
