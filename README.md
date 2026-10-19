# races

A calendar of trail, road and ultra races worldwide, aggregated from public race calendars and served as a static site at [races.sanch.pet](https://races.sanch.pet). Races the site owner plans to run are highlighted.

## How it works

1. `races fetch` runs one parser per source (`src/races/sources/`), normalises every race into one schema, geocodes towns offline against [GeoNames](https://www.geonames.org/), merges races listed by several sources and writes `data/events.json`.
2. `races build` copies `site/` into `dist/` with one JSON file; the page filters it in the browser.
3. A daily GitHub Actions run fetches, commits the refreshed `data/events.json` to `main` and force-pushes the built site as a single commit to the `public` branch, which the web server pulls.

Which sources are parsed, which are only linked, and why: [docs/sources.md](docs/sources.md).

## Run locally

Requires [uv](https://docs.astral.sh/uv/) (`mise install` provides it).

```sh
uv sync
uv run races fetch          # about a minute: DUV asks for 20 s between requests
uv run races build
python3 -m http.server -d dist 8000   # open http://localhost:8000
```

`races fetch --only utmb` refreshes one source and keeps the others' last data. Raw responses are cached in `.cache/raw/` for 20 hours, so re-running is cheap and polite.

Checks:

```sh
uv run ruff check . && uv run ruff format --check .
uv run pytest      # recorded fixtures, no network
```

## Configuration

- `config/regions.yaml` — the region groups in the filter (a label and a list of ISO country codes each). Edit and rebuild; no code changes needed.
- `picks.yaml` — the owner's picks: an event `id` (shown under "Details" on each race) or any of its source URLs, with an optional `status` (`planned`, `registered`, `done`) and `note`. A race no source lists can be defined in the pick itself (name, date, country, url; see the file's header); it merges with a source's record once a parser finds the same race. A pick that matches no race fails `races build`. Picks apply at build time, so an edit shows on the next push without a fetch. Friends' picks will go to `picks/<name>.yaml` in the same format.

## Adding a source

Add `src/races/sources/<name>.py` with a class that has `name`, `homepage`, `priority`, `fetch(client) -> list[str]` and `parse(pages, fetched_at) -> list[Event]`, register it in `sources/__init__.py`, record a trimmed response in `tests/fixtures/` and test the parser on it. Fetch only through `PoliteClient`: it sends an identifying User-Agent, obeys `robots.txt` (including `Crawl-delay`), rate-limits per host and caches. Check the source's terms before writing the parser and record the verdict in `docs/sources.md`.

## Data and licence

Race facts belong to their sources and organisers; every race links back to them. Code is MIT-licensed. Place coordinates derive from GeoNames (CC BY 4.0); map tiles © OpenStreetMap contributors.
