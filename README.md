# Hotel Demand Forecaster

Spot busy dates for a hotel early, from public signals: local events, public
holidays, long weekends and seasonal travel interest. Enter a location and a
date range. The dashboard shows a daily demand index, the busiest stretches,
and the events behind them. **Every event or travel claim links to the page it
came from**, with the time it was fetched, so you can verify it.

## Quick start (Windows / PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env    # then edit .env
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Open http://localhost:8000. Run the tests with `.venv\Scripts\python -m pytest`.

In `.env`:

- `SCRAPER_CONTACT`: an email address or URL where site operators can reach you. It is sent in the User-Agent header.
- `TICKETMASTER_API_KEY`: a free key from [developer.ticketmaster.com](https://developer.ticketmaster.com/). Optional, but it is the richest event source.

## Where the data comes from

| Source | What it gives | Key? |
|---|---|---|
| [OpenStreetMap Nominatim](https://nominatim.org/) | Turns the location you typed into coordinates, country and region | No |
| [Nager.Date](https://date.nager.at/) | National and regional public holidays, and long weekends | No |
| [Ticketmaster Discovery API](https://developer.ticketmaster.com/) | Concerts, sports and theatre within the radius, with distance | Free key |
| [Wikidata](https://www.wikidata.org/) | Notable events with an exact date in or near the city | No |
| [Wikimedia pageviews](https://wikimedia.org/api/rest_v1/) | Monthly readership of the city's Wikipedia/Wikivoyage page, used as a seasonal travel-interest index | No |
| Pages you add | City or tourism calendars, venue schedules, `.ics` feeds | No |

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
baseline(day) = 40 × seasonal factor for the month (pageviews, clamped 0.6–1.6)
pressure(day) = Σ weights of events/holidays covering the day
              + 40% of the weight of big events starting the next day (arrival night)
index(day)    = baseline + (100 − baseline) × (1 − e^(−pressure / 3))
```

Levels: Quiet < 35 ≤ Normal < 52 ≤ Busy < 70 ≤ Very busy.

Weights are rules of thumb: event type (festival, sports, conference > concert
> theatre), distance from the hotel, and venue capacity when it is published.
Multiple reports of the same event are merged, keeping every source. **The
index is not fitted to any hotel's bookings.** Treat it as an early warning of
which dates to check, not a booking forecast.

## Known limits

- Big **annual festivals** (e.g. SXSW, the Edinburgh Fringe) appear only if a
  source lists them with dates for the year you're forecasting. Usually that
  means Ticketmaster, or adding the festival's or tourism board's event page.
  Wikidata rarely has future editions.
- Pages that render their calendars with JavaScript, or that don't use schema.org
  or iCal markup, yield nothing. The source log says so for each page.
- Recurring iCal events (`RRULE`) count only their first occurrence.

## Layout

```
app/
  main.py          FastAPI app: dashboard page + POST /api/forecast
  service.py       runs all sources concurrently, then scores
  forecast.py      demand index, busy periods, duplicate merging
  fetcher.py       polite HTTP: robots.txt, throttling, caching, redaction
  sources/         geocode, holidays, ticketmaster, wikidata, pageviews, webpages
  templates/, static/   dashboard (vanilla JS + SVG, light/dark)
tests/             offline tests (HTTP mocked with respx)
```
