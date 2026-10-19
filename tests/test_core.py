import json
import re
from datetime import date
from pathlib import Path

import httpx
import pytest

from races.build import attach_picks, build_site
from races.config import PicksError, Region, load_picks, region_tags
from races.dedupe import deduplicate
from races.geocode import Gazetteer
from races.http import PoliteClient, RobotsDisallowed
from races.models import Distance, Event, Registration
from races.pipeline import write_events

ROOT = Path(__file__).resolve().parent.parent


def event(source, sid, name, day, country="GE", **kw):
    return Event(
        name=name,
        start_date=day,
        source=source,
        source_id=sid,
        source_url=f"https://{source}.example/{sid}",
        country=country,
        **kw,
    )


def test_dedupe_merges_across_sources_and_keeps_provenance():
    rich = event(
        "utmb",
        "1",
        "Kullamannen by UTMB",
        date(2026, 10, 30),
        "SE",
        distances=[Distance(173, 3000)],
        registration=Registration("open"),
    )
    poor = event(
        "duv",
        "9",
        "Kullamannen by UTMB 100 Miles",
        date(2026, 10, 30),
        "SE",
        distances=[Distance(172.5), Distance(50)],
    )
    merged = deduplicate([poor, rich], {"utmb": 20, "duv": 30})
    assert len(merged) == 1
    m = merged[0]
    assert m.source == "utmb"
    assert {s.source for s in m.sources} == {"utmb", "duv"}
    assert sorted(d.km for d in m.distances) == [50, 173]


def test_dedupe_keeps_distinct_events():
    a = event("utmb", "1", "Tbilisi Trail", date(2027, 5, 1))
    b = event("duv", "2", "Kazbegi Ultra", date(2027, 5, 1))
    c = event("duv", "3", "Tbilisi Trail", date(2027, 5, 1), country="AM")
    d = event("duv", "4", "Tbilisi Trail", date(2027, 6, 1))
    assert len(deduplicate([a, b, c, d], {})) == 4


def test_dedupe_never_merges_within_one_source():
    a = event("duv", "1", "Batumi Ultra", date(2027, 5, 1))
    b = event("duv", "2", "Batumi Ultra Night", date(2027, 5, 1))
    assert len(deduplicate([a, b], {})) == 2


def test_region_tags_allow_overlap():
    regions = [Region("caucasus", "Caucasus", ["GE", "TR"]), Region("europe", "Europe", ["TR"])]
    assert region_tags("TR", regions) == ["caucasus", "europe"]
    assert region_tags(None, regions) == []


def test_repo_regions_config_is_valid():
    from races.config import load_regions

    regions = load_regions(ROOT / "config" / "regions.yaml")
    keys = [r.key for r in regions]
    assert "georgia-caucasus" in keys and "cyprus-neighbours" in keys
    assert all(len(c) == 2 for r in regions for c in r.countries)


def test_picks_owner_and_friends(tmp_path):
    (tmp_path / "picks.yaml").write_text("- id: abc\n  status: registered\n")
    (tmp_path / "picks").mkdir()
    (tmp_path / "picks" / "nino.yaml").write_text("- url: https://x.example/\n")
    picks = load_picks(tmp_path)
    assert [(p.person, p.status) for p in picks] == [("owner", "registered"), ("nino", "planned")]


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ("- note: no key\n", "needs an id or a url"),
        ("- id: x\n  status: maybe\n", "unknown status"),
        ("id: x\n", "expected a list"),
        ("- id: 123456789012\n", "put it in quotes"),
        ("- id: 012345670123\n", "put it in quotes"),
        ("- id: '000000000000'\n  staus: done\n", "unknown keys ['staus']"),
    ],
)
def test_picks_reject_bad_entries(tmp_path, body, error):
    (tmp_path / "picks.yaml").write_text(body)
    with pytest.raises(PicksError, match=re.escape(error)):
        load_picks(tmp_path)


def test_seeded_picks_file_loads():
    assert load_picks(ROOT) == []


def test_attach_picks_by_id_secondary_id_and_url():
    from races.config import Pick
    from races.models import SourceRef

    e = event("utmb", "1", "Race", date(2027, 1, 1))
    e.sources.append(SourceRef("duv", "7", "https://d.example/7", "dupid"))
    other = event("duv", "8", "Other race", date(2027, 1, 2))
    records = attach_picks(
        [e, other],
        [
            Pick("owner", id=e.id),
            Pick("nino", id="dupid", status="done"),
            Pick("gio", url="https://d.example/7/"),
        ],
    )
    assert [p["person"] for p in records[0]["picks"]] == ["owner", "nino", "gio"]
    assert "picks" not in records[1]


def test_pick_matching_no_race_fails_the_build(tmp_path):
    data = tmp_path / "events.json"
    write_events(data, [event("utmb", "1", "Race", date(2027, 1, 1))], {})
    root = tmp_path / "root"
    (root / "picks").mkdir(parents=True)
    (root / "site").symlink_to(ROOT / "site")
    (root / "config").symlink_to(ROOT / "config")
    (root / "picks.yaml").write_text("- id: deadbeef0000\n")
    (root / "picks" / "nino.yaml").write_text("- url: https://nowhere.example/race\n")
    with pytest.raises(PicksError) as err:
        build_site(root, data, tmp_path / "dist")
    assert "picks.yaml #1: deadbeef0000" in str(err.value)
    assert "picks/nino.yaml #1: https://nowhere.example/race" in str(err.value)
    assert not (tmp_path / "dist").exists()


def test_gazetteer_locates_town_inside_venue_or_name():
    row = [
        "1",
        "Bariloche",
        "Bariloche",
        "San Carlos de Bariloche",
        "-41.1",
        "-71.3",
        "P",
        "PPL",
        "AR",
        "",
        "",
        "",
        "",
        "",
        "100000",
        "",
        "",
        "",
        "",
    ]
    g = Gazetteer([row])
    assert g.locate("AR", "Centro Civico Bariloche") == (-41.1, -71.3)
    assert g.locate("AR", None, "Bariloche Patagonia by UTMB") == (-41.1, -71.3)
    assert g.locate("CL", "Bariloche") is None


def test_polite_client_obeys_robots_with_wildcards(tmp_path):
    robots = "User-agent: *\nDisallow: /\nAllow: /*.php\n"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        return httpx.Response(200, text="ok")

    client = PoliteClient(cache_dir=tmp_path, min_delay_s=0, transport=httpx.MockTransport(handler))
    assert client.get_text("https://duv.example/calendar.php?page=1") == "ok"
    with pytest.raises(RobotsDisallowed):
        client.get_text("https://duv.example/events/1")


def test_build_site_writes_page_and_data(tmp_path):
    data = tmp_path / "events.json"
    write_events(
        data, [event("utmb", "1", "Race", date(2027, 1, 1))], {"utmb": {"status": "ok", "count": 1}}
    )
    out = tmp_path / "dist"
    stats = build_site(ROOT, data, out)
    assert stats == {"events": 1, "picks": 0}
    assert (out / "index.html").exists() and (out / "app.js").exists()
    site = json.loads((out / "events.json").read_text())
    assert site["countries"] == {"GE": "Georgia"}
    assert {r["key"] for r in site["regions"]} >= {"europe", "asia"}


def test_dedupe_does_not_merge_marathon_with_same_city_ultra():
    marathon = event(
        "intervals", "1", "Boston Marathon", date(2027, 4, 19), "US", distances=[Distance(42.195)]
    )
    ultra = event(
        "duv",
        "2",
        "31st TARC Don't Run Boston (DRB) 50 Miles",
        date(2027, 4, 19),
        "US",
        distances=[Distance(80.5)],
    )
    dallas = event("intervals", "3", "Dallas Marathon", date(2027, 12, 13), "US")
    dallas_ultra = event("duv", "4", "8th Dallas 50 km Race", date(2027, 12, 13), "US")
    assert len(deduplicate([marathon, ultra, dallas, dallas_ultra], {})) == 4


def test_unchanged_events_keep_their_timestamp():
    from races.pipeline import keep_unchanged_timestamps

    old = event("utmb", "1", "Race", date(2027, 1, 1), fetched_at="2026-10-01T00:00:00+00:00")
    same = event("utmb", "1", "Race", date(2027, 1, 1), fetched_at="2026-10-18T00:00:00+00:00")
    moved = event("utmb", "1", "Race", date(2027, 1, 2), fetched_at="2026-10-18T00:00:00+00:00")
    keep_unchanged_timestamps([same], [old])
    keep_unchanged_timestamps([moved], [old])
    assert same.fetched_at == "2026-10-01T00:00:00+00:00"
    assert moved.fetched_at == "2026-10-18T00:00:00+00:00"


def test_picked_race_outlives_race_day_and_its_source():
    from races.config import Pick
    from races.pipeline import carry_picked, finalise

    today = date(2027, 6, 1)
    done = event("utmb", "1", "Kazbegi Ultra", date(2027, 5, 1))
    dropped = event("duv", "2", "Mestia Ultra", date(2027, 7, 1))
    stale = event("duv", "3", "Batumi Run", date(2027, 5, 2))
    picks = [Pick("owner", id=done.id, status="done"), Pick("nino", url=dropped.source_url + "/")]

    current = [done]  # the source still lists the finished race; duv no longer lists Mestia
    carried = carry_picked(current, [done, dropped, stale], picks)
    assert carried == [dropped]
    kept = finalise(current + carried + [stale], {}, today, picks)
    assert [e.name for e in kept] == ["Kazbegi Ultra", "Mestia Ultra"]
