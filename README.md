# Hotel Demand Forecaster

Spot busy dates for a hotel early, from public signals: local events, public
holidays, long weekends and seasonal travel interest. Enter a location and a
date range. The dashboard shows a daily demand index, the busiest stretches,
and the events behind them. **Every event or travel claim links to the page it
came from**, with the time it was fetched, so you can verify it.

## Install (Windows desktop app)

Run **`HotelDemandForecaster-Setup-<version>.exe`**. It installs for the current
user (no administrator rights needed) and adds a Start-menu shortcut. The app
opens in its own window; source links open in your normal browser.

On first launch, open **Settings** (the gear, top right) and add:

- **Contact email**: sent with each request so site operators can reach you.
  OpenStreetMap and Wikimedia ask for this.
- **Ticketmaster API key** (optional, free): sign up at
  [developer.ticketmaster.com](https://developer.ticketmaster.com/) and copy the
  *Consumer Key* from My Apps. It is checked with Ticketmaster when you save,
  and the full key is never shown back in the app.

Where things are kept (both survive uninstall/reinstall):

| What | Where |
|---|---|
| Settings | `%APPDATA%\HotelDemandForecaster\settings.json` |
| Response cache, window storage, log (`app.log`) | `%LOCALAPPDATA%\HotelDemandForecaster\` |

The window uses the Microsoft Edge WebView2 Runtime, which is built into
Windows 11. On Windows 10 the installer warns if it's missing.

The installer isn't code-signed, so Windows SmartScreen will say "Windows
protected your PC" the first time; choose **More info → Run anyway**.

### Building the installer

```powershell
build.bat
```

This runs the tests, bundles the app with PyInstaller into
`dist\HotelDemandForecaster\`, and compiles `packaging\installer.iss` with
[Inno Setup 6](https://jrsoftware.org/isinfo.php) into
`dist\installer\HotelDemandForecaster-Setup-<version>.exe`. Install Inno Setup
with `winget install JRSoftware.InnoSetup`. Bump the version in
`app/__init__.py` before building a release. Build files live in `packaging/`.

## Running from source

Double-click **`launch.bat`** to serve the dashboard at http://localhost:8000 in
your browser, and **`terminate.bat`** to stop it. Or open the desktop window
from source with `.venv\Scripts\python -m app.desktop`. On the first run
`launch.bat` creates the virtual environment, installs dependencies and creates
`.env` from `.env.example`.

Manually, in PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Run the tests with `.venv\Scripts\python -m pytest`.

From source, settings are saved to `data\settings.json`. Values in `.env`
(`SCRAPER_CONTACT`, `TICKETMASTER_API_KEY`) are used as defaults until you
save something in Settings.

## Where the data comes from

| Source | What it gives | Key? |
|---|---|---|
| [OpenStreetMap Nominatim](https://nominatim.org/) | Turns the location you typed into coordinates, country and region | No |
| [Nager.Date](https://date.nager.at/) | National and regional public holidays, and long weekends | No |
| [Ticketmaster Discovery API](https://developer.ticketmaster.com/) | Concerts, sports and theatre within the radius, with distance | Free key |
| [Wikidata](https://www.wikidata.org/) | Notable events with an exact date in or near the city | No |
| [Wikimedia pageviews](https://wikimedia.org/api/rest_v1/) | Monthly readership of the city's Wikipedia/Wikivoyage page, used as a seasonal travel-interest index | No |
| Pages you add | City or tourism calendars, venue schedules, `.ics` feeds | No |
| Wikidata + Wikipedia infoboxes | Venue capacities, to size events | No |
| Wikipedia + Wikimedia pageviews | Headliners' monthly readership, a proxy for artist popularity | No |

For pages you add, the app reads only events the publisher marks up for
machines: schema.org `Event` JSON-LD or microdata, and iCalendar feeds,
including feeds a page advertises with `<link rel="alternate" type="text/calendar">`.
Each URL is fetched once. The app does not crawl.

### X / Facebook

These are **not** scraped. Both platforms prohibit automated collection in their
terms of service and robots.txt, so scraping them would break the ethics rules
below. The legitimate routes are the paid X API and Meta's Graph API, which
requires app review for public Page content. Either could be added later as an
API source with your own credentials.

## Ethical scraping rules (enforced in `app/fetcher.py`)

- **robots.txt is obeyed** for every web page, including rules aimed at
  `HotelDemandForecaster` specifically. Following RFC 9309, a missing
  robots.txt means the page is allowed, and an unreachable one means it is not.
- Official APIs are used under their own terms. They are rate-limited, cached
  and identified the same way as web pages.
- **One request at a time per site**, spaced by `MIN_HOST_INTERVAL` (2s by
  default). A site's `Crawl-delay` wins if it is longer. Nominatim is held to 1
  request per second, as its usage policy requires.
- **Identifying User-Agent** with your contact details.
- **Caching**: pages for 24h, APIs for 12h to 30 days. Repeat forecasts don't
  re-hit sites.
- No logins, cookies, paywalls or retries. Only http(s). A 5 MB cap per response.
- API keys are redacted from everything shown in the dashboard.

The dashboard's **Source log** lists every request the forecast made,
including ones it skipped and why.

## How the demand index works

```
event weight  = type weight × distance factor × venue-size factor × artist-popularity factor
baseline(day) = 40 × seasonal factor for the month (pageviews, clamped 0.6–1.6)
pressure(day) = Σ weights of events/holidays covering the day
              + 40% of the weight of big events starting the next day (arrival night)
              − routine event load (the typical day of that weekday in the range)
index(day)    = baseline + (100 − baseline) × (1 − e^(−pressure / 3))
```

Levels: Quiet < 35 ≤ Normal < 52 ≤ Busy < 70 ≤ Very busy.

**Type and distance.** Festival, sports and conferences weigh more than concerts,
which weigh more than theatre. Weight halves at 15 km from the hotel.

**Event size** (`app/sources/enrich.py`, `app/sizing.py`). Each multiplier is
shown on the dashboard with its source:

- *Venue capacity*: ×0.5 for a 100-seat room, ×1.3 at 10,000, up to ×1.7 for
  a stadium. Capacities come from one Wikidata query covering every venue near
  the hotel, with each venue's Wikipedia infobox as a fallback. A match needs
  a distinctive shared word in the name (not "center" or "arena") and, when
  coordinates exist, a location within 3 km. Venues found in neither source are
  **assumed small (×0.7)**. That rule is shown as a model assumption with no
  source link, because large venues are almost always documented.
- *Artist popularity* (non-sports events): average monthly English Wikipedia
  views over the last 12 months for the headliner or co-headliner. That's ×0.75
  around 1k views/month, ×1.0 at 10k, ×1.25 at 100k, up to ×1.6 for global
  stars. The article comes from Ticketmaster's own link, or from a search result
  with the same name that Wikipedia describes as a musician, band, comedian and
  so on. Up to 80 artists are looked up per forecast, biggest venues first.
- Combined sizing is capped at ×0.4–×2.5. Ticket price is deliberately not used.

**Routine event load.** Cities with shows every night would otherwise read
"busy" every day. For ranges of four weeks or more, each day's event load is
compared with the median for the same weekday (a Saturday against other
Saturdays). For two to four weeks it's compared with the median day overall,
and for shorter ranges nothing is subtracted. Holidays are never treated as
routine.

Multiple reports of the same event are merged, keeping every source. Ticketing
add-ons (parking, early entry) and multi-day bundles that duplicate nightly
listings are dropped. **The index is not fitted to any hotel's bookings.** Treat
it as an early warning of which dates to check, not a booking forecast.

## Known limits

- Big **annual festivals** (e.g. SXSW, the Edinburgh Fringe) appear only if a
  source lists them with dates for the year you're forecasting. Usually that
  means Ticketmaster, or adding the festival's or tourism board's event page.
  Wikidata rarely has future editions.
- Pages that render their calendars with JavaScript, or that don't use schema.org
  or iCal markup, yield nothing. The source log says so for each page.
- Recurring iCal events (`RRULE`) count only their first occurrence.
- Venue sizing is limited by what Wikidata and Wikipedia document. Some
  mid-size venues are missed and fall back to the "assumed small" rule, either
  because their capacity sits on an article with a different title or because
  the infobox has no capacity.
- Sports events are sized by venue only. Team popularity isn't measured, so a
  routine regular-season game at a big arena counts about the same as a rivalry game.

## Layout

```
app/
  main.py          FastAPI app: dashboard page, /api/forecast, /api/settings
  desktop.py       desktop entry: local server + native window
  config.py        settings (per-user settings.json, .env defaults from source)
  service.py       runs all sources concurrently, then scores
  forecast.py      demand index, busy periods, duplicate merging
  fetcher.py       polite HTTP: robots.txt, throttling, caching, redaction
  sizing.py        venue-size / popularity factors and name matching
  sources/         geocode, holidays, ticketmaster, wikidata, pageviews, webpages,
                   enrich (venue capacity + artist popularity)
  templates/, static/   dashboard (vanilla JS + SVG, light/dark)
packaging/         PyInstaller spec, Inno Setup script, icon, build.ps1
tests/             offline tests (HTTP mocked with respx)
```
