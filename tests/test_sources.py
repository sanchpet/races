from datetime import date
from pathlib import Path

import pytest

from races.sources.duv import Duv, parse_dates, parse_distance
from races.sources.utmb import Utmb, parse_date

FIXTURES = Path(__file__).parent / "fixtures"
NOW = "2026-10-18T00:00:00+00:00"


def test_utmb_groups_races_into_events():
    events = Utmb().parse([(FIXTURES / "utmb_races.json").read_text()], NOW)
    by_url = {e.source_url: e for e in events}

    yun = by_url["https://mount-yun.utmb.world/"]
    assert yun.name == "Mount Yun by UTMB"
    assert yun.country == "CN"
    assert yun.discipline == "trail"
    assert len(yun.distances) > 1
    assert all(d.elevation_gain_m for d in yun.distances)
    assert yun.registration.status in {"open", "closed", "upcoming", "unknown"}

    tenerife = by_url["https://tenerife.utmb.world/"]
    assert tenerife.country == "ES"
    assert tenerife.start_date <= tenerife.end_date


def test_utmb_ids_are_stable_across_runs():
    page = (FIXTURES / "utmb_races.json").read_text()
    first = {e.id for e in Utmb().parse([page], NOW)}
    second = {e.id for e in Utmb().parse([page], "2026-10-19T00:00:00+00:00")}
    assert first == second


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("16th October 2026", date(2026, 10, 16)),
        ("1st May 2027", date(2027, 5, 1)),
        ("garbage", None),
    ],
)
def test_utmb_parse_date(text, expected):
    assert parse_date(text) == expected


def test_duv_parses_rows_and_maps_ioc_codes():
    events = Duv().parse([(FIXTURES / "duv_calendar.html").read_text()], NOW)
    assert len(events) > 20
    countries = {e.country for e in events}
    assert "JP" in countries  # JPN
    assert all(len(c) == 2 for c in countries if c)
    assert all(
        e.source_url.startswith("https://statistik.d-u-v.org/eventdetail.php?event=")
        for e in events
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("24.10.2026", (date(2026, 10, 24), date(2026, 10, 24))),
        ("17.-18.10.2026", (date(2026, 10, 17), date(2026, 10, 18))),
        ("30.10.-01.11.2026", (date(2026, 10, 30), date(2026, 11, 1))),
        ("31.12.2026-01.01.2027", (date(2026, 12, 31), date(2027, 1, 1))),
        ("07.-00.11.2026", (date(2026, 11, 7), date(2026, 11, 7))),  # typo in source data
        ("12.12.2026-12.12.0000", (date(2026, 12, 12), date(2026, 12, 12))),
        ("soon", None),
    ],
)
def test_duv_parse_dates(text, expected):
    assert parse_dates(text) == expected


def test_duv_parse_distance():
    assert parse_distance("100km") == 100
    assert parse_distance("50mi") == 80.5
    assert parse_distance("24h") is None


class FakeClient:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.requested: list[str] = []

    def get_text(self, url: str) -> str:
        self.requested.append(url)
        return self.pages.get(url, self.pages["default"])


def test_duv_fetch_follows_pagination():
    page = (FIXTURES / "duv_calendar.html").read_text()
    client = FakeClient({"default": page})
    pages = Duv().fetch(client)
    assert len(pages) == len(client.requested) > 1
    assert client.requested[-1].endswith("page=4")


def test_intervals_keeps_running_events_only():
    from races.sources.intervals import Intervals

    events = Intervals().parse([(FIXTURES / "intervals_cy.html").read_text()], NOW)
    names = {e.name for e in events}
    assert "Lefkara Classic" not in names  # a cycling sportive
    assert {"Olympos Man Trail Running", "Limassol Marathon"} <= names
    assert all(e.country == "CY" for e in events)
    trail = next(e for e in events if e.name == "Olympos Man Trail Running")
    assert trail.discipline == "trail"
    assert trail.start_date == date(2026, 10, 18)
    marathon = next(e for e in events if e.name == "Limassol Marathon")
    assert [d.km for d in marathon.distances] == [42.195]


def test_intervals_city_from_address():
    from races.sources.intervals import city_from_address

    assert city_from_address("Pirelli Stadium, Burton-on-Trent DE13 0AR, UK") == "Burton-on-Trent"
    assert city_from_address("Pano Lefkara 7700, Cyprus") == "Pano Lefkara"
    assert city_from_address("Cyprus") is None


def test_traillab_reads_homepage_blocks_and_detail_distances():
    from races.sources.traillab import TrailLab

    home = (FIXTURES / "traillab_home.html").read_text()
    detail = "<!-- url: https://www.traillab.ge/lisi/ -->\n<p>20KM Trail Race</p><p>63KM Ultra</p>"
    events = {e.name: e for e in TrailLab().parse([home, detail], NOW)}
    assert set(events) == {"Mestia Ultra", "Kazbegi Mountain Marathon", "Lisi Trail Festival"}
    mestia = events["Mestia Ultra"]
    assert (mestia.start_date, mestia.end_date) == (date(2026, 7, 18), date(2026, 7, 19))
    assert mestia.country == "GE" and mestia.city == "Mestia"
    assert events["Lisi Trail Festival"].source_url == "https://www.traillab.ge/lisi/"
    assert [d.km for d in events["Lisi Trail Festival"].distances] == [20, 63]
