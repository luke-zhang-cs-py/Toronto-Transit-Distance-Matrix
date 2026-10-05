# Code audit

*The newest pass is the first section below. After it come the 160-test
pass, kept as it was, and the [27 September pass](#27-september-2026-235-tests-100)
at the end.*

## 5 October 2026: 239 tests, 100% of statements

Baseline: 235 passed, flake8's real-error set (`E9,F63,F7,F82` plus
`F401,F811,F841`) clean, 1,055 statements none missed, 304 branches with 3
partial. After: 239 passed, flake8 clean, 1,060 statements none missed, the
same 3 partial branches. Every fix below has a test that was run against the
unfixed code and failed there.

### Bugs fixed

| # | Class | What was wrong | Test |
|---|---|---|---|
| 1 | Functional / integration | `realtime._feed` fell back to the last good parse with no age limit. With the feed down all afternoon, a morning closure kept routing people around a line that had reopened, headways were from another hour, and `/api/live` and every trip still said `live: true`. Now the fallback stands for `LAST_GOOD_MAX_AGE_SECONDS` (10 minutes); after that the answer is the static model, labelled as such. This was in the 27 September "left alone" list. | `test_a_last_good_reading_too_old_to_trust_is_dropped`, `test_a_last_good_reading_with_no_time_is_not_trusted` |
| 2 | Workflow (race) | `planTrip` drew whichever `/api/trips` answer arrived last. The minute timer in `when.js` replans "leave now", so picking a new destination while a replan was in flight could put the old trip back over the new one. Requests are numbered and only the latest is drawn. | `test_only_the_latest_trip_plan_is_drawn` |
| 3 | Workflow | "New trip" and choosing a new origin left `lastTrip` set, so the minute timer kept replanning the finished trip and drew its route on the map while the next origin was being chosen. `forgetTrip()` clears it and drops anything in flight. | same test |
| 4 | Runtime | A `/api/trips` request that failed outright (offline, or an HTML error page that is not JSON) was an unhandled rejection, and the previous trip's options and route stayed on screen. It now clears them and says the planner did not answer; a reply with no options still says "No trip found". | same test |
| 5 | Functional | `here.js`: Android Chrome fires `deviceorientationabsolute` and a relative `deviceorientation` beside it. The relative one replaced the location note with "recalibrate the magnetometer" many times a second on a compass that was working. The advice now only shows while no true bearing has arrived. | `test_a_working_compass_does_not_ask_to_be_recalibrated` |

The page tests load the real `static/js/app.js` and `here.js` in Node behind a
small stub of the DOM and Leaflet (`PAGE_STUBS` in `tests/test_static_build.py`),
with `fetch` held open so answers can be delivered out of order. `docs/app/` was
rebuilt with `python tools/build_static.py`, and `tools/refresh_figures.py`
updated the published counts.

### Checklist

- **Dispensables.** Fixed: `network/buses.py` had `BUS_WAIT_MIN = 7`, read by
  nothing, beside the `WAIT_BY_MODE["bus"] = 7` that is actually used, with a
  comment calling it the fallback; it also re-exported an unused `chain`
  import. `.coveragerc` still omitted `tools_build_schedule.py` and
  `tools_build_buses.py`, names that stopped existing when the tools moved
  into `tools/` (`tools/*` already covers them), and `.gitignore` named the
  old path. A typo in `gtfs.fetch`'s docstring. Nothing else stale in the
  comments read.
- **Bloaters.** Left: `itinerary._search` and `_to_legs` (about 80 lines
  each), `schedule.departures_after` and `tools/build_buses._stitch_islands`
  stay over complexity 10, as before, and `realtime._feed` reaches 11 with
  the age check (radon: C). Each
  is one algorithm read top to bottom. `static/js/app.js` is a 500-line global
  script by design (no build step for the Flask page).
- **Abusers.** Left: `lineColor` in `app.js` is an `if` chain over line-name
  prefixes; a table would read the same and is a matter of taste.
- **Couplers, change preventers.** Nothing new. The page scripts share state
  through globals (`lastTrip`, `tripOptions`), and `when.js` reaches into
  `app.js`'s `planTrip` and `lastTrip`; `forgetTrip()` is now the one place a
  trip ends.
- **Global data, magic numbers, naming.** The new age limit is a named
  constant with its reason. `app._count` accepts `true` as 1 and `2.7` as 2;
  left, since nothing sends those.
- **Security.** Every `innerHTML` in the page scripts goes through `esc()` or
  is a constant; the stop-name check from 27 September still holds. `app.py`
  runs Werkzeug with `debug=True`, which includes the interactive debugger:
  acceptable only because `app.run` binds to 127.0.0.1 and the README says the
  app runs on your own machine; never run it with `host="0.0.0.0"` as is. No
  secrets or personal data in tracked files.

### Coverage

`python -m coverage run --branch -m pytest` then `coverage report -m`, Python
3.14.6.

| module | statements | branches | before | after |
|---|---|---|---|---|
| `feeds/realtime.py` | 242 -> 248 | 72 | 100% lines, 1 partial (`_alert_text`'s empty-translation skip) | 100% lines, the same partial |
| `trips/itinerary.py` | 229 | 78 | 100%, 1 partial | unchanged |
| `trips/routing.py` | 99 | 38 | 100%, 1 partial (`_charge_boarding_wait` with no ride) | unchanged |
| `network/buses.py` | 32 -> 31 | 12 | 100% | 100% |
| `app.py`, `feeds/gtfs.py`, `feeds/schedule.py`, `network/*`, `trips/geo.py` | 453 | 104 | 100% | 100% |
| **total** | **1,055 -> 1,060** | **304** | **100% lines, 99% with branches** | **same** |

The browser code has no line measurement. What runs under test: the static
build's Dijkstra port against the Python (`static-reach.js`), `when.js`'s
Toronto clock, and now `app.js` loading, `planTrip`, `forgetTrip` and the "New
trip" handler, and `here.js`'s orientation handling. Not exercised: map
drawing, the option list and itinerary markup, the heat radar, geolocation
fixes, and `docs/app`'s `static-api.js` / `static-ui.js`.

### Maintenance

- **Corrective:** bugs 1 to 5, the stale `.coveragerc` and `.gitignore` names.
- **Adaptive:** the local `schedule_index.json` covers 6 September to 31
  October 2026 (the board period). From 1 November every wait falls back to
  headways or the model until `python tools/build_schedule.py` is run against
  the new GTFS; `scheduleAvailable` already reports this per date. CI's
  `actions/checkout@v5` and `setup-python@v6` are current. The published
  statement counts are measured with 3.14 and CI runs 3.10 and 3.12, which the
  figures test already allows for.
- **Perfective:** a failed trip request says so instead of leaving the last
  trip on screen; the compass note stops flickering on Android.
- **Preventive:** the page-script stub makes the front end's request handling
  testable from the existing suite; the age limit stops a dead feed from
  posing as a live one.

### Left for later

- `snapshot()["ageSeconds"]` is the age of the last refresh, not of the data
  in it; within the 10-minute window a fallback reading still looks fresh
  there. `feedTimestamp` tells the truth.
- `setOrigin` has the same shape as bug 2 for `/api/reach`: two quick clicks
  can paint the first origin's times. Rarer (no timer drives it); not fixed.
- `_later_departures` and the three partial branches, as noted on 27 September.

Static analysis (flake8, radon), a 160-test suite, and a coverage report.

```bash
pytest -q --cov=. --cov-report=term-missing
python -m flake8 . --select=E9,F63,F7,F82,F401,F402,F811,F841,E722,E741
python -m radon cc . -s -n C --exclude ".git/*,tests/*"
```

The repository has roughly tripled since the last pass — `realtime.py`,
`schedule.py`, `itinerary.py`, 28 generated bus routes, two GTFS build tools
and three browser modules. Most of what follows is the cost of that growth.

## Coverage

**160 tests, 93%.**

| Module | Cover | | Module | Cover |
|---|---|---|---|---|
| `geo.py` | **100%** | | `app.py` | 94% |
| `network/__init__.py` | **100%** | | `network/graph.py` | 93% |
| `network/regional.py` | **100%** | | `gtfs.py` | 92% |
| `network/streetcars.py` | **100%** | | `realtime.py` | 84% |
| `network/subway.py` | **100%** | | `network/buses.py` | 81% |
| `routing.py` | 98% | | | |
| `itinerary.py` | 97% | | | |
| `schedule.py` | 95% | | | |

`schedule.py` was 68% and `gtfs.py` was 0%. Both are now covered, and in both
cases the untested half was the part that matters when something is missing:
no index built, a corrupt file, a stop that is not in the index, a time of
night with no service. Those paths decide whether a trip degrades gracefully
or reports nonsense.

The build tools are excluded in `.coveragerc`. Exercising them means shipping
a 36 MB GTFS archive; their shared logic is now in `gtfs.py`, which is
tested, and that is where the subtleties live.

## Findings

### Dispensables — duplicate code

**Haversine existed three times.** `routing.haversine_km`, and a `metres`
function in each build tool, byte-identical to each other. Three copies of
eleven lines is not expensive, and it was already drifting: the tools
returned metres and routing returned kilometres with no shared definition
saying so. Now `geo.py`, with `km()` and `metres()` over one formula.
`routing.haversine_km` remains as a thin alias because `itinerary` and the
tests import that name.

**The GTFS reading layer existed twice.** `rows` was byte-identical across
the two build tools; `to_seconds` was the same logic with different variable
names — and the copy in the bus builder had **lost the comment explaining why
hours past 24 must not be normalised.** That is the shape of the problem
rather than its size: the next fix has to be made twice, and one copy had
already lost the documentation of a subtlety somebody will otherwise
rediscover by shipping a bug. Now `gtfs.py`, and a test asserts neither tool
redefines any of it.

`stop_positions` and the archive URL were also duplicated, and `lines_at`
existed in both `routing.py` and the schedule builder. `lines_at` now lives
in `network/graph.py`, which is where a graph query belongs; `graph_lines()`
is the union of it over every node rather than a second walk over `adj` that
could disagree about what counts as a line.

**Dead code:** flake8 F401/F402/F811/F841 is clean across the project.

### Change Preventers — shotgun surgery

The duplication above *was* the change preventer, and it had already fired
once in this session: adding bus routes meant editing both build tools, and
the earlier fix to the path resolution had to be applied twice.

One remains and is documented: `haversineKm` in `static/js/app.js` duplicates
`geo.km`. Deliberate and narrow — shipping the routing engine to the browser
to draw a legend would be worse than eleven lines of trigonometry — and it is
eleven lines that will not change.

### Bloaters

`build_buses.build` was **D(27)**, doing five things: selecting routes,
thinning stops, wiring transfers, finding crossings, and stitching islands.
Split into `_one_route` and `_add_crossings`; nothing in the project is above
C now.

The nine remaining C-rated functions are the graph searches (`_search`,
`compute_times`), the two `build` entry points, and the GTFS matching passes.
Each is one loop over one data structure; the count comes from the number of
cases in the data, not from nesting.

### Magic Number

Named this pass: `EARTH_RADIUS_KM`, `SECONDS_PER_DAY`, `ROUTE_TYPE_SUBWAY`,
`ROUTE_TYPE_BUS`, `CLOCK`, `SENSOR_GRACE_MS`, `COARSE_METRES`,
`POOR_HEADING_DEGREES`, `MAX_WALK_ONLY_MIN`, `ALTERNATIVE_TOLERANCE`.

Previously named and still load-bearing: `MIN_GAPS_FOR_HEADWAY`,
`MAX_MATCH_METRES`, `TRANSFER_RADIUS_M`, `DRIVE_KMH`, `PARK_AND_WALK_MIN`.
Each has the reasoning above it, because in this project the number *is* the
modelling decision — 26 km/h rather than a speed limit, 900 m rather than
something tighter.

### Inconsistent Naming

**The stylesheet had two type scales and two palettes.** `.legendLabels` was
10px Inter — the only 10px in the file, and the only place a figure was set
in the body font while every other number is IBM Plex Mono. And the legend
gradient was three different colours from the map's own ramp
(`#4da3ff` against `rgb(57,182,255)`, and so on), so the bar under the slider
never quite matched the dots it explained. One ramp now, in CSS custom
properties that `app.js` reads, and every `font-size` lands on the
11 / 11.5 / 12.5 scale.

### Global Data

`network.nodes` and `network.adj` are module-level and mutable, built once at
import. That is the Global Data smell and it bit: `build_buses` imported
`network`, which loads the tool's own previous output, so every stop matched
*itself* from the last run — 388 self-loops and a second run reporting six
times the transfer edges of the first. The tool now filters to non-bus nodes
and a test asserts the graph has no self-loops.

`realtime` keeps a module-level cache and a refresher thread; `schedule`
caches the index. Both are lock-guarded singletons for a one-process app, and
both have `reset()` so tests are not fighting each other's state.

### Couplers

`itinerary` imports `haversine_km`, `path_km` and `walk_minutes` from
`routing`, which is a module reaching into a sibling for arithmetic rather
than for behaviour. The arithmetic half is now in `geo`; the rest is
`walk_minutes`, which is one line over `WALK_KMH` and stays where the walking
model is.

## Bug classes

| Class | Found this pass |
|---|---|
| Syntax | none — flake8 E9/F63/F7/F82 clean |
| Runtime | **fixed:** `TypeError` in `_search` — the heap compared `None` against a line name |
| Logical | **fixed:** the option filter compared transit against the *driving* baseline, so transit vanished from the comparison |
| Workflow | **fixed:** `laterDepartures` offered the train you were already catching |
| Integration | **fixed:** the bus builder's input contained its own previous output |
| Out of bounds | **fixed:** eleven bus stops in the graph reachable from nowhere |
| Environment | **fixed:** four tests passed only on a machine with a gitignored index |
| Security | reviewed below |

**Runtime.** `itinerary._search` pushed `(arrival, node, line)` onto the heap,
and `line` is `None` before boarding. Two entries with the same arrival at the
same stop fell through to comparing `None` with a string. Latent while exact
ties were rare; 388 more stops made them routine. There is a counter
tiebreaker now, so `heapq` never compares the payload.

**Environment.** Six consecutive CI runs were red while the suite was green
locally, and the difference was one gitignored file. `schedule_index.json` is
derived data that goes stale with the board period, so it is built rather than
committed and CI has never had one. Without it every boarding wait is modelled
at four minutes instead of read from the timetable, which is enough to reorder
the trip options — driving Union to Finch beats transit at 35.3 minutes
against 42.7.

Three tests read `plan["options"][0]` as "the transit trip". Options are
ordered by duration across every kind, so that was only ever true when transit
happened to win. They now ask for a transit option by kind. A fourth asserted
the alternative tolerance held *globally*, which the code deliberately gave up
when applying it across kinds turned out to hide transit whenever driving was
faster — it now checks per kind, which is what `_worth_choosing_between`
actually guarantees.

The tell was already in the file: `test_the_boarding_time_is_a_real_departure`
passes `compare=False` and says why — "the fastest option overall may be a
park-and-ride boarding somewhere else entirely". That hazard was understood in
one test and not applied to its neighbours.

Two new tests close it rather than just fixing it.
`test_the_fastest_option_is_not_always_transit` pins the ordering contract the
four broke, and `test_a_transit_option_survives_without_the_timetable`
monkeypatches the index away so the configuration CI actually runs is covered
on a developer machine too. The suite now passes both ways: **160 with the
index, 149 and 11 skipped without.**

**Security.** No authentication, no database, no user input reaching a shell
or a query. Coordinates are validated for type, finiteness and range — a
non-finite one used to reach the response as a bare `NaN` token, which
Python writes and `JSON.parse` rejects. The server binds loopback. Geolocation
checks `isSecureContext` first, because browsers refuse it off HTTPS with an
error saying "permission denied", which sends people to the wrong setting.

## Maintenance classification

**Corrective** — the heap `TypeError`, the self-loops, the eleven unreachable
stops, the dangling transfer edges, the duplicate transfers, the option
filter hiding transit, `laterDepartures` repeating a train.

**Adaptive** — most of this session. TTC publishes GTFS-realtime openly and
the docstrings said that feed had been retired; the static GTFS is a 36 MB
download and the docstrings said there was no network access. Both were
wrong, and both were the *stated reason* the app used a fixed schedule model.
Adapting to what the feeds actually offer also meant finding what they do
not: their `stop_id` spaces do not join (route 504 has 107 static stops and
103 realtime with 2 in common), and the subway has no realtime at all — zero
trip updates and zero vehicles for routes 1, 2 and 4.

**Perfective** — `geo.py` and `gtfs.py`, the `build` split, the legend type
and palette. None of it changes behaviour; all of it changes the cost of the
next change. The tests are what made it safe: every one passed before the
extraction and after it, and both build tools produce byte-identical output.

**Preventive** — the structural tests. `test_both_build_tools_use_the_shared_helpers`
fails if either tool redefines a shared helper;
`test_no_stop_pair_is_joined_twice_by_the_same_line` and the connectivity test
fail against the graph as it was mid-session; `test_hours_past_midnight_are_kept`
pins the GTFS subtlety whose documentation had already gone missing once.

## Accepted deviations

Thirteen `E501`s in `network/regional.py` and `network/streetcars.py`. All are
one-line station definitions — `{id, name, lat, lon}` per row — in data tables
where one row per line is more scannable than a wrapped block. All are under
the 127-character limit the CI enforces.

## 27 September 2026: 235 tests, 100%

1,055 statements, none missed (1,015 and one missed before: the
`dest is None` guard in `gtfs.fetch` had never run). Six bugs, each with a
test that was watched failing against the unfixed code:

- **An offset timestamp was a 500.** `departAt: "...T21:20:00+00:00"`
  parsed to an aware datetime and the timetable lookup raised `TypeError`
  comparing it with naive entries. `app._depart_at` and `itinerary.plan` now
  convert to Toronto wall-clock time.
- **"Leave now" used the machine's zone.** The timetable is Toronto time;
  a server in London planned 17:00 against the 17:00 timetable, five hours
  out. `schedule.local_now()` reads Toronto whatever the host, and `when.js`
  seeds "Leave at" from Toronto's clock rather than the browser's.
- **A 404 was saved as the GTFS archive.** curl without `--fail` writes the
  error page and exits 0, and `build_schedule.py` reuses an archive already
  on disk, so one bad download broke every later run. `IncompleteRead`
  escaped `fetch()` entirely and left an empty file. Failures now leave
  nothing at `dest`.
- **The realtime fetch ignored curl's exit status**, so a transfer cut off
  by `--max-time` was handed to the parser as a feed.
- **The debug reloader ran startup twice.** The watcher process fetched the
  feed and kept its own refresher polling TTC every 30 s. Startup is now
  `app.main()`, which warms the feed only in the serving process.
- **Stop names went into tooltips unescaped.** Leaflet sets a string
  tooltip as HTML; every other name already went through `esc()`.

Also: the Flask footer said "not a live feed"; both pages had no viewport
meta (`here.js` is written for phones); `gtfs.py` said the archive was 82 MB
(it is 36); the empty disruption table was written out five times in
`realtime.py`; two magic numbers got names. `tests/test_static_build.py`
fails if `docs/app/` is stale against its sources, and runs the ported
Dijkstra in Node against `compute_times` for four origins -- the build's own
check compares a Python transcription of the port, not the port.

Left alone: `realtime._feed` serves the last good parse indefinitely while
the feed is down and still reports `live: true` (by design, but nothing
ages it out); `_later_departures` offers later times for the first
*timetabled* boarding, which is not always the first vehicle its docstring
promises; `_search` and `_stitch_islands` stay over flake8's complexity 10.
