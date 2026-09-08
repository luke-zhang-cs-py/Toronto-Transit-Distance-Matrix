"""
realtime.py
------------
Live TTC service data, folded into the routing model.

The rest of this project is a fixed schedule model: a subway wait is 4
minutes because that is roughly half the headway, a streetcar wait is 6.
Those numbers are averages of a timetable, and a timetable is not what is
happening. This module replaces them with what is happening, where the feed
can say.

No API key. TTC publishes GTFS-realtime openly at bustime.ttc.ca -- the
project docstrings used to say that feed had been retired, which was wrong;
all three endpoints answer, unauthenticated. Metrolinx's API does need a key
and is not used, so YRT, MiWay and GO stay on the static model and say so.

What the feed can and cannot tell us
------------------------------------
*Waits* come from the trip feed. It carries no `delay` field -- TTC leaves it
unset -- but it does carry ~30,000 absolute arrival times. Grouping those by
stop and taking the gaps gives the observed headway per route, and half a
headway is the expected wait for somebody arriving at a random moment. Route
506 measured a 6.6 minute headway on the first run, against the model's
assumed 6 minute *wait* -- so the static figure was nearly double the truth
at that moment.

*Disruptions* come from the alert feed. Its `effect` enum is UNKNOWN_EFFECT
on every entity, so the effect has to be read out of the header text, which
TTC also truncates to about 32 characters. That is enough to tell "No
service" from "Detour" from "Elevator out of service", and those three want
different treatment: route around it, add time, ignore it for routing.

Subway alerts are informed by the *shuttle bus* route ids rather than a
subway route id, so "Line 2 Bloor-Danforth: No service" has to be matched on
the text. Streetcar alerts carry the real route id (501, 504, 506...), which
is also the prefix of the line names in `network/`, so those map directly.

Degrading
---------
Every entry point returns the static answer when the feed is unavailable, and
the snapshot says which was used. A router that stops working when the
network hiccups is worse than one that was never live: it fails at the moment
somebody is standing on a platform. `Snapshot.live` is the honest flag, and
/api/route reports it so the page can show what it is looking at.
"""

import logging
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request

from network import WAIT_BY_MODE, DEFAULT_WAIT_MIN

log = logging.getLogger(__name__)

FEEDS = {
    "trips": "https://bustime.ttc.ca/gtfsrt/trips",
    "alerts": "https://bustime.ttc.ca/gtfsrt/alerts",
}

# How stale a feed may be before it is fetched again. Real-time does not mean
# re-downloading 730 KB on every keystroke: TTC's own predictions do not move
# faster than this, and a route request has to answer while somebody is
# looking at it.
TRIPS_TTL_SECONDS = 30.0
ALERTS_TTL_SECONDS = 60.0

# A request must not hang on a slow feed. Past this we serve the last good
# snapshot, or the static model.
FETCH_TIMEOUT_SECONDS = 8.0

# Bounds on a measured wait. One vehicle seen twenty minutes apart is not
# evidence of a twenty-minute headway, and a burst of three in a minute is not
# a thirty-second one.
MIN_OBSERVED_WAIT_MIN = 1.0
MAX_OBSERVED_WAIT_MIN = 25.0

# A headway needs this many observed gaps before it is worth believing.
MIN_GAPS_FOR_HEADWAY = 8

# Gaps outside this are not headways -- they are the end of service, or two
# predictions for the same vehicle.
MIN_GAP_SECONDS = 30
MAX_GAP_SECONDS = 45 * 60

# What a detour costs when the feed says there is one but not how long. Chosen
# to be enough to prefer an alternative if one exists, and not so much that it
# makes a usable route look impossible.
DETOUR_PENALTY_MIN = 5.0

# Alert text -> what it means for routing. Ordered: the first match wins, so
# "no service" beats "detour" when a message says both.
_NO_SERVICE = re.compile(r"no service|not stopping|closed|suspend", re.I)
_DETOUR = re.compile(r"detour|diver(t|sion)|delay|slow", re.I)
_NOT_ROUTING = re.compile(r"elevator|escalator|proof of payment|look both ways", re.I)

CLOSED = "closed"
DETOUR = "detour"
COSMETIC = "cosmetic"

_lock = threading.Lock()
_cache = {}          # kind -> {"at": float, "parsed": FeedMessage|None}
_last_good = {}      # kind -> parsed result, kept so a failed fetch is not a cliff

# The derived numbers the router actually reads: headways and disruptions,
# already computed. Kept separately from the parsed feed because deriving
# them is not free -- 2,400 trip updates and 30,000 arrival times -- and
# doing it per request was 98 ms of recomputing an unchanged answer.
_derived = {"headways": {}, "disrupted": {"closed": set(), "detour": set(), "notes": []},
            "live": False, "at": 0.0, "feedTimestamp": None}

_refresher = None
_stop = threading.Event()


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def _fetch(url, timeout=FETCH_TIMEOUT_SECONDS):
    """The feed bytes, or None.

    urllib first, curl second. Not a preference -- on this machine urllib
    cannot verify the certificate chain ("Basic Constraints of CA cert not
    marked critical"), because a local inspecting CA is not strict-OpenSSL
    clean, and certifi does not help since the interception is what fails.
    curl verifies differently and succeeds. On a machine without that proxy
    the first branch is the one that runs.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.debug("urllib could not fetch %s (%s); trying curl", url, exc)

    try:
        done = subprocess.run(["curl", "-s", "--max-time", str(int(timeout)), url],
                              capture_output=True, timeout=timeout + 5)
        return done.stdout or None
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("could not fetch %s: %s", url, exc)
        return None


def _feed(kind):
    """A parsed FeedMessage for `kind`, cached, or None if unavailable."""
    ttl = TRIPS_TTL_SECONDS if kind == "trips" else ALERTS_TTL_SECONDS
    now = time.monotonic()

    with _lock:
        cached = _cache.get(kind)
        if cached and now - cached["at"] < ttl:
            return cached.get("parsed")

    raw = _fetch(FEEDS[kind])
    parsed = None
    if raw:
        try:
            from google.transit import gtfs_realtime_pb2
            message = gtfs_realtime_pb2.FeedMessage()
            message.ParseFromString(raw)
            parsed = message
        except ImportError:
            log.warning("gtfs-realtime-bindings is not installed; "
                        "staying on the static model")
        except Exception as exc:                      # a corrupt or partial body
            log.warning("could not parse the %s feed: %s", kind, exc)

    with _lock:
        # Cache the attempt either way, so a feed that is down is not retried
        # on every single request -- but keep the last parse that worked.
        _cache[kind] = {"at": now, "parsed": parsed or _last_good.get(kind)}
        if parsed is not None:
            _last_good[kind] = parsed
    return _cache[kind]["parsed"]


# ---------------------------------------------------------------------------
# Waits, measured
# ---------------------------------------------------------------------------
def observed_headways(feed=None):
    """{route_id: median headway in minutes} from the trip feed.

    Gaps are taken per stop and pooled per route. Per stop because two
    consecutive arrivals at the *same* stop is what a headway is; pooled
    because one stop rarely has enough of them to be worth a median.
    """
    feed = feed if feed is not None else _feed("trips")
    if feed is None:
        return {}

    headways = {}
    for route, stops in _arrivals_by_route(feed).items():
        gaps = _gaps_between(stops)
        if len(gaps) < MIN_GAPS_FOR_HEADWAY:
            continue
        gaps.sort()
        headways[route] = gaps[len(gaps) // 2] / 60.0
    return headways


def _arrivals_by_route(feed):
    """{route_id: {stop_id: [arrival epoch, ...]}} out of the trip feed."""
    per_route = {}
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        update = entity.trip_update
        route = update.trip.route_id
        if not route:
            continue
        stops = per_route.setdefault(route, {})
        for stop_time in update.stop_time_update:
            if stop_time.HasField("arrival") and stop_time.arrival.time:
                stops.setdefault(stop_time.stop_id, []).append(stop_time.arrival.time)
    return per_route


def _gaps_between(stops):
    """Plausible headways in seconds, pooled across a route's stops.

    Gaps outside the bounds are not headways: too small is two predictions
    for one vehicle, too large is the end of service showing up as a wait
    nobody would actually have.
    """
    gaps = []
    for times in stops.values():
        ordered = sorted(times)
        gaps += [b - a for a, b in zip(ordered, ordered[1:])
                 if MIN_GAP_SECONDS < (b - a) < MAX_GAP_SECONDS]
    return gaps


def route_id_of(line):
    """The TTC route id a line name refers to, or None.

    The names in network/ start with the route number -- "504 King", "506
    Carlton/College" -- which is the same id the feed uses, so this is a
    parse rather than a table that could fall out of step with the graph.
    Subway lines and the regional agencies have no matching id.
    """
    match = re.match(r"^(\d{1,3})\b", line or "")
    return match.group(1) if match else None


def wait_for(line, mode, headways=None):
    """Expected wait in minutes, measured if the feed can say, else modelled.

    Half the headway: somebody arriving at a random moment waits, on average,
    half the gap between vehicles. The static WAIT_BY_MODE numbers were
    already half-headway estimates, so this is the same quantity with a
    current value instead of an average one.
    """
    fallback = WAIT_BY_MODE.get(mode, DEFAULT_WAIT_MIN)
    route = route_id_of(line)
    if route is None:
        return fallback, False

    table = headways if headways is not None else observed_headways()
    headway = table.get(route)
    if headway is None:
        return fallback, False

    measured = max(MIN_OBSERVED_WAIT_MIN, min(MAX_OBSERVED_WAIT_MIN, headway / 2.0))
    return measured, True


# ---------------------------------------------------------------------------
# Disruptions
# ---------------------------------------------------------------------------
def classify(text):
    """What an alert means for routing: CLOSED, DETOUR or COSMETIC.

    Read from the text because TTC sets `effect` to UNKNOWN_EFFECT on every
    entity. Cosmetic is checked first: a broken elevator is a real problem for
    a real person and changes nothing about how long a train takes, and
    treating it as a closure would route people the long way round for no
    reason.
    """
    text = text or ""
    if _NOT_ROUTING.search(text):
        return COSMETIC
    if _NO_SERVICE.search(text):
        return CLOSED
    if _DETOUR.search(text):
        return DETOUR
    return COSMETIC


def _alert_text(alert):
    parts = []
    for field in (alert.header_text, alert.description_text):
        for translation in field.translation:
            if translation.text:
                parts.append(translation.text)
    return " ".join(parts)


def disruptions(feed=None):
    """Route ids and subway line numbers currently disrupted.

    Returns {"closed": set, "detour": set, "notes": [...]}. Members are TTC
    route ids ("504") and subway line tokens ("line 1"), which is what
    `impact_on` matches a line name against.
    """
    feed = feed if feed is not None else _feed("alerts")
    out = {"closed": set(), "detour": set(), "notes": []}
    if feed is None:
        return out

    for entity in feed.entity:
        if not entity.HasField("alert"):
            continue
        alert = entity.alert
        text = _alert_text(alert)
        kind = classify(text)
        if kind == COSMETIC:
            continue

        subjects, precise = _subjects_of(alert, text)
        if not subjects:
            continue

        # An alert whose subject had to be guessed from informed_entity is not
        # evidence that all of those routes stopped running, so it is priced
        # as a detour rather than a closure. See _subjects_of.
        effect = kind if precise else DETOUR
        out[effect].update(subjects)
        out["notes"].append({"effect": effect, "text": text[:160],
                             "subjects": sorted(subjects),
                             "subjectFromText": precise})
    return out


def _subjects_of(alert, text):
    """What an alert is actually about: (subjects, came_from_the_text).

    `informed_entity` cannot be used as the subject. TTC lists every route
    touching the affected area, so "Line 2 Bloor-Danforth: No service"
    informs thirty-five routes -- including streetcars 504, 505 and 512,
    which are the connections, not the closure. Believing that list would
    have closed a third of the network because one subway line was down, and
    sent people on detours around routes that were running normally.

    TTC's headers follow "<subject>: <message>" -- "Line 2 Bloor-Danforth:
    No service", "68 Warden: Detour via Sixteenth" -- so the subject is the
    leading token, and that is what the effect belongs to.

    Only when the text names nothing does informed_entity get used, and the
    caller downgrades the effect accordingly.
    """
    leading_line = re.match(r"\s*line\s*([1-4])\b", text, re.I)
    if leading_line:
        return {f"line {leading_line.group(1)}"}, True

    leading_route = re.match(r"\s*(\d{1,3})\b", text)
    if leading_route:
        return {leading_route.group(1)}, True

    return {ie.route_id for ie in alert.informed_entity if ie.route_id}, False


def impact_on(line, disrupted=None):
    """Extra minutes for travelling this line, or None if it is not running.

    None means "do not route over this" -- the caller drops the edge rather
    than pricing it, because a closed line is not expensive, it is absent.
    """
    disrupted = disrupted if disrupted is not None else disruptions()
    route = route_id_of(line)
    tokens = {route} if route else set()

    subway = re.match(r"^line\s*([1-4])\b", (line or "").strip(), re.I)
    if subway:
        tokens.add(f"line {subway.group(1)}")

    if tokens & disrupted["closed"]:
        return None
    if tokens & disrupted["detour"]:
        return DETOUR_PENALTY_MIN
    return 0.0


# ---------------------------------------------------------------------------
# One reading of the network, for one request
# ---------------------------------------------------------------------------
class Conditions:
    """The live picture, fetched once and reused for a whole route.

    Dijkstra asks about waits and closures thousands of times per request.
    Calling the feed from inside that loop would be a network round trip per
    edge; worse, the answer could change halfway through, and a shortest-path
    search over a graph whose weights move while you search it is not
    shortest-path at all. So the feed is read once, frozen here, and the
    search runs against a consistent snapshot.
    """

    def __init__(self, headways=None, disrupted=None, live=False):
        self.headways = headways or {}
        self.disrupted = disrupted or {"closed": set(), "detour": set(), "notes": []}
        self.live = live

    @classmethod
    def live_now(cls):
        """The current reading, off the derived cache. Never does I/O.

        This is the request path, so it must not fetch and must not parse.
        Both were measured: fetching 730 KB took 5.2 seconds, and re-deriving
        the headways from an already-cached parse still took 98 ms -- per
        request, for numbers that had not changed. `refresh()` does that work
        on a background thread; this reads the result.

        If nothing has been refreshed yet, it returns the static model rather
        than blocking on a first fetch. A first page load answering in five
        milliseconds against the schedule is better than one answering in five
        seconds against the feed, and the next request will be live.
        """
        with _lock:
            return cls(headways=_derived["headways"],
                       disrupted=_derived["disrupted"],
                       live=_derived["live"])

    @classmethod
    def static(cls):
        """The fixed schedule model, with nothing live in it."""
        return cls(live=False)

    def wait_source(self, line, mode):
        """Whether this line's wait is measured or modelled, for the report."""
        _value, measured = self.wait_for(line, mode)
        return "measured" if measured else "modelled"

    def wait_for(self, line, mode):
        return wait_for(line, mode, self.headways)

    def impact_on(self, line):
        return impact_on(line, self.disrupted)

    def boarding_wait(self, node_lines, mode):
        """Wait at a stop, given the lines that serve it.

        You board whatever arrives first, so the wait at an interchange is the
        smallest of its lines' waits, not the average. With no live figure for
        any of them this is the modelled wait for the mode, unchanged.
        """
        fallback = WAIT_BY_MODE.get(mode, DEFAULT_WAIT_MIN)
        best, measured = fallback, False
        for line in node_lines:
            if self.impact_on(line) is None:
                continue                      # not running: cannot board it
            value, is_live = self.wait_for(line, mode)
            if is_live and value < best:
                best, measured = value, True
        return best, measured


# ---------------------------------------------------------------------------
# What the API reports
# ---------------------------------------------------------------------------
def snapshot():
    """Freshness and coverage, for the response and the page.

    Deliberately explicit about what is *not* live. A number that silently
    switches between measured and assumed is worse than either, because you
    cannot tell which one you are looking at.
    """
    with _lock:
        headways = dict(_derived["headways"])
        disrupted = _derived["disrupted"]
        live = _derived["live"]
        at = _derived["at"]
        feed_ts = _derived["feedTimestamp"]

    return {
        "live": live,
        "source": "TTC GTFS-realtime (bustime.ttc.ca, no key required)",
        "feedTimestamp": feed_ts,
        "ageSeconds": round(time.time() - at, 1) if at else None,
        "routesWithObservedHeadway": len(headways),
        "closed": sorted(disrupted["closed"]),
        "detour": sorted(disrupted["detour"]),
        "alerts": disrupted["notes"],
        # What the feed does not cover, said plainly rather than left to be
        # inferred from a number that happens to equal the modelled one.
        #
        # TTC's realtime feed is surface routes only: buses and streetcars.
        # No subway route id appears in it, so Line 1 and Line 2 keep their
        # modelled 4-minute wait however live the rest of the answer is --
        # and the subway is most of the travel time on most trips here.
        # Metrolinx's API, which would cover GO, needs a key this project
        # does not use.
        "modelledOnly": ["subway (Line 1-4)", "yrt", "miway", "go"],
        "measuredModes": ["tram (streetcar routes 501-511)", "bus"],
    }


def refresh():
    """Fetch, parse and derive. Safe to call from anywhere; not on a request.

    Returns True if the reading is live. Everything it touches is replaced
    atomically under the lock, so a request never sees half a refresh --
    headways from one minute and closures from another would price a route
    against a network that never existed.
    """
    trips = _feed("trips")
    alerts = _feed("alerts")
    live = trips is not None or alerts is not None

    headways = observed_headways(trips) if trips is not None else {}
    disrupted = disruptions(alerts) if alerts is not None else \
        {"closed": set(), "detour": set(), "notes": []}

    with _lock:
        _derived.update(headways=headways, disrupted=disrupted, live=live,
                        at=time.time(),
                        feedTimestamp=int(trips.header.timestamp) if trips is not None else None)
    return live


def start_refresh(interval=TRIPS_TTL_SECONDS):
    """Keep the reading current on a daemon thread. Idempotent.

    A background loop rather than refreshing when a request notices the data
    is stale: that puts a five-second fetch on whichever unlucky request
    arrives first after each expiry. The work is the same either way; the
    difference is who waits for it.
    """
    global _refresher
    with _lock:
        if _refresher is not None and _refresher.is_alive():
            return _refresher

        def loop():
            while not _stop.is_set():
                try:
                    refresh()
                except Exception:       # a dead refresher is a silent failure
                    log.exception("realtime refresh failed")
                _stop.wait(interval)

        _stop.clear()
        _refresher = threading.Thread(target=loop, name="ttc-realtime", daemon=True)
        _refresher.start()
        return _refresher


def stop_refresh():
    _stop.set()


def reset_cache():
    """Drop everything cached. For tests, and for a manual refresh."""
    with _lock:
        _cache.clear()
        _last_good.clear()
        _derived.update(headways={}, live=False, at=0.0, feedTimestamp=None,
                        disrupted={"closed": set(), "detour": set(), "notes": []})
