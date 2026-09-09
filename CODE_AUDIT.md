# Code audit

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

`tools_build_buses.build` was **D(27)**, doing five things: selecting routes,
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
import. That is the Global Data smell and it bit: `tools_build_buses` imported
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
