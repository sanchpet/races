# Race calendar sources

Which calendars the aggregator reads, which it only links to, and why. Checked on 2026-10-18; robots.txt and terms change, so re-check a source before widening what is fetched from it.

## Rules every parser follows

- Fetch only what `robots.txt` allows for our agent, and honour `Crawl-delay`. The client refuses a URL when robots.txt disallows it and stops when robots.txt is unreachable.
- Identify as `races.sanch.pet/0.1 (+https://races.sanch.pet)`.
- At most one request per host every 2 seconds (or the source's crawl delay, if longer); retry transient failures twice with backoff.
- Cache raw responses for 20 hours (`.cache/raw/`, not committed), so re-runs do not hit the source again.
- Keep facts only (name, dates, place, distances, climb, registration status) and link every race back to its source page. No descriptions, images or logos are copied.
- A site behind a bot challenge, or whose robots.txt or terms forbid automated access, is listed here as **link only** and is not parsed. Bot protection is never worked around.

## Parsed

| Source | Coverage | Access | robots.txt | Terms | Events (18 Oct 2026) |
|---|---|---|---|---|---|
| [UTMB World Series](https://utmb.world/races) | ~50 trail events worldwide, each with several distances | JSON: `api.utmb.world/search/races?lang=en&limit=100&offset=N` (the endpoint behind the site's race finder) | `utmb.world`: `Disallow:` (empty, all allowed); `api.utmb.world` has no robots.txt (404) | No clause on automated access; the IP clause forbids reproducing texts and illustrations, so only facts are kept | 52 events (255 races) |
| [DUV Ultra Marathon Statistics](https://statistik.d-u-v.org/calendar.php) | All upcoming ultras worldwide (50 km+ and timed events) | HTML table, 1000 rows per page, 4 pages; an RSS feed of the next races also exists | `Disallow: /` with `Allow: /*.php` and `Crawl-delay: 20`; the calendar is a `.php` page | No terms page; a copyright line only | 2119 events (from ~3100 rows: DUV lists each distance as its own row) |
| [Intervals.icu events](https://www.intervals.icu/events/) | Community-listed endurance events in ~70 countries; running and trail running are kept, cycling and the rest dropped | HTML: `/events/` lists countries, `/events/<CC>/` lists that country's events in cards | `User-agent: * Allow: /` | No website terms published (`/terms/` is 404); the API terms grant a broad licence | 921 running events |
| [TrailLab](https://www.traillab.ge/) | The main trail organiser in Georgia: Mestia Ultra, Kazbegi Mountain Marathon, Lisi Trail Festival, Tbilisi races | HTML: the homepage's upcoming-race blocks (name, date, link); each race page once for its distances. WordPress REST has no race type (only pages and empty posts) | `Disallow: /wp-admin/` only | Privacy policy only | 3 (all 2026 dates have passed; 2027 dates appear once the organiser publishes them) |

Fields per source:

- **UTMB:** event name, date per distance, start venue and country name, distance, elevation gain, registration status (`registration_open`, `registration_sold_out`, `registration_closed`, `available_soon`), event site URL. No coordinates.
- **DUV:** start and end date, event name, one distance or duration per row, town, IOC country code, DUV event page. No climb, no registration data.
- **Intervals.icu:** date, name, street address, sport. Distances are read from the race name ("10K", "Half Marathon").
- **TrailLab:** name, date range, race page; distances from the race page.

Coordinates for the map come from the offline [GeoNames](https://www.geonames.org/) `cities1000` dump (CC BY 4.0), matched by town name within the race's country. About 88% of races get a position.

## Link only

| Source | Coverage | Why it is not parsed |
|---|---|---|
| [ITRA race calendar](https://itra.run/Races/RaceCalendar) | Trail races worldwide with ITRA points | Every request, robots.txt included, gets an AWS WAF JavaScript challenge (`HTTP 202`, `x-amzn-waf-action: challenge`). Nothing is readable without solving it. |
| [ahotu](https://www.ahotu.com/calendar) | The largest worldwide running calendar | Cloudflare challenge on every request, robots.txt included (`HTTP 403`, `cf-mitigated: challenge`). |
| [Let's Do This](https://www.letsdothis.com/) | Worldwide, strong in the UK and US | Cloudflare challenge (`HTTP 403`). |
| [World's Marathons](https://www.worldsmarathons.com/) | Road marathons worldwide | robots.txt allows crawling, but listing pages return `HTTP 403` to an identified client. |
| [AIMS](https://aims-worldrunning.org/) | Certified road races worldwide | `Disallow: /events` |
| [RaceResult](https://my.raceresult.com/) | Timing platform event listings | `Disallow: /RREvents` (the event listing). |
| [World Athletics calendar](https://worldathletics.org/competition/calendar-results) | Labelled road races worldwide | Data is only reachable through an undocumented GraphQL API keyed with a token embedded in the site; the terms text could not be retrieved. Not used until there is a documented way in. |

## Candidates, not parsed yet

| Source | Coverage | Status |
|---|---|---|
| [Finishers](https://www.finishers.com/) / [marathons.com](https://www.marathons.com/) | Large European trail and road calendar | robots.txt allows event pages but disallows the filtered listing queries; the API returns `401 You are not authorized`. A parser would have to read ~4400 event pages from the sitemap. The legal notice forbids reproducing content (texts, photos), which a facts-only parser respects. Worth an incremental, cached crawl later. |
| [Trace de Trail](https://tracedetrail.fr/en/calendar) | Trail races, mostly France, some worldwide (Cyprus included) | robots.txt allows everything, but the calendar loads through a POST endpoint that returns `500` outside a browser session. |
| [ISF Skyrunning](https://www.skyrunning.com/) | Skyrunning races | The WordPress REST type `single-race` lists 573 races but carries no race dates. |
| [Golden Trail Series](https://goldentrailseries.com/) | One elite trail series | WordPress with a `race` type; `Crawl-delay: 10`. Small; not evaluated further. |
| [RunSignup](https://runsignup.com/API) | US races | Official public API; US-only, so out of scope for now. |

## Coverage gaps

The owner's home regions are thin. Georgia has TrailLab plus DUV ultras in the Caucasus; Cyprus has a handful of Intervals.icu and DUV entries. No source covering Armenia, Israel, Lebanon or Egypt in depth was found yet; national federation and organiser sites there are the next thing to evaluate.
