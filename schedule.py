"""
schedule.py
------------
When the next vehicle actually leaves, from TTC's published timetable.

`realtime.py` answers "how long will I wait on average" from observed
headways. This answers "what time does the next one go", which is a
different question and the one you need if you are planning to leave at
17:20 rather than right now.

The data is TTC's static GTFS, reduced by tools_build_schedule.py into
schedule_index.json: for each graph node and line, the departure times on
each service day. Built rather than parsed live because stop_times.txt is
207 MB and the reduction is 0.6.

Service days, not calendar days
-------------------------------
GTFS writes a 01:30 train on Friday night as "25:30:00" on Friday's service,
not "01:30:00" on Saturday's, because that train belongs to Friday's
timetable. Times here are seconds after the service day's midnight and can
exceed 86400. Anything asking about the small hours has to look at yesterday's
service as well as today's, which `departures_after` does.

What is still modelled
----------------------
Only the time *at* a stop comes from the timetable. Hop times between stops
are still the graph's fixed minutes -- GTFS has those too, but the graph's
nodes are a hand-built simplification and its edges skip stops, so a
scheduled hop would not describe the same journey. And the graph's synthetic
streetcar nodes sit a few hundred metres from the real stop, which the index
records per match so it is visible rather than assumed away.

Nine node-line pairs have no stop within 900 m and are not in the index at
all. Those fall back to the modelled wait, and `has_schedule` says which is
which.
"""

import datetime as dt
import json
import logging
import os
import threading

log = logging.getLogger(__name__)

INDEX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "schedule_index.json")

SECONDS_PER_DAY = 86400

# How far ahead to keep looking for a departure before giving up. Past this
# the answer is "not until tomorrow", and a router that waits six hours for a
# train is not planning a trip anybody would take.
MAX_WAIT_SECONDS = 3 * 3600

_lock = threading.Lock()
_index = None
_loaded = False


def load(path=INDEX_PATH):
    """The departure index, read once. Returns None if it has not been built.

    Absent rather than fatal: the project works without it, on headways and
    modelled waits, and `python tools_build_schedule.py` is what turns the
    timetable on.
    """
    global _index, _loaded
    with _lock:
        if _loaded:
            return _index
        _loaded = True
        if not os.path.exists(path):
            log.info("no schedule index at %s; run tools_build_schedule.py "
                     "for timetabled departures", path)
            _index = None
            return None
        try:
            with open(path, encoding="utf-8") as handle:
                _index = json.load(handle)
        except (OSError, ValueError) as exc:
            log.warning("could not read the schedule index: %s", exc)
            _index = None
        return _index


def reset():
    """Forget the loaded index. For tests."""
    global _index, _loaded
    with _lock:
        _index = None
        _loaded = False


def available():
    return load() is not None


def built_at():
    index = load()
    return index.get("builtAt") if index else None


# ---------------------------------------------------------------------------
# Service days
# ---------------------------------------------------------------------------
def services_on(date):
    """The service ids running on a calendar date."""
    index = load()
    if not index:
        return []
    return index.get("services", {}).get(date.strftime("%Y%m%d"), [])


def covered_dates():
    index = load()
    if not index:
        return []
    return sorted(index.get("services", {}))


def has_schedule(node_id, line):
    index = load()
    if not index:
        return False
    return line in index.get("departures", {}).get(node_id, {})


def match_metres(node_id, line):
    """How far this node sits from the stop its times come from.

    Worth surfacing: a node 600 m from its stop is on the right line, but the
    walk to it is not what the graph says, and a schedule quoted to the
    minute against an approximate position is precise about the wrong thing.
    """
    index = load()
    if not index:
        return None
    return index.get("matchMetres", {}).get(node_id, {}).get(line)


# ---------------------------------------------------------------------------
# Departures
# ---------------------------------------------------------------------------
def departures_after(node_id, line, moment, limit=4):
    """The next `limit` scheduled departures at or after `moment`.

    `moment` is a datetime. Returns datetimes, in order.

    Today's service is checked first, then tomorrow's -- and yesterday's,
    because a departure written as 25:30 on yesterday's service is half past
    one this morning and is the train somebody catching the last one wants.
    """
    index = load()
    if not index:
        return []
    table = index.get("departures", {}).get(node_id, {}).get(line)
    if not table:
        return []

    found = []
    # Yesterday first: its after-midnight departures land today.
    for offset in (-1, 0, 1):
        day = (moment + dt.timedelta(days=offset)).date()
        midnight = dt.datetime.combine(day, dt.time.min)
        for service in services_on(day):
            for seconds in table.get(service, []):
                when = midnight + dt.timedelta(seconds=seconds)
                if when >= moment and (when - moment).total_seconds() <= MAX_WAIT_SECONDS:
                    found.append(when)
        if len(found) >= limit * 4:
            break

    found.sort()
    # De-duplicate: two services can both run on a date (a weekday service
    # plus a holiday exception), and the same train then appears twice.
    unique = []
    for when in found:
        if not unique or when != unique[-1]:
            unique.append(when)
    return unique[:limit]


def next_departure(node_id, line, moment):
    """The next scheduled departure, or None if there is not one soon."""
    found = departures_after(node_id, line, moment, limit=1)
    return found[0] if found else None


def wait_minutes(node_id, line, moment):
    """Minutes until the next scheduled departure, or None if unscheduled.

    None is the signal to fall back -- to the live headway, then to the
    modelled wait. It means "the timetable cannot answer this", which is a
    different thing from "there is no wait".
    """
    when = next_departure(node_id, line, moment)
    if when is None:
        return None
    return max(0.0, (when - moment).total_seconds() / 60.0)


def service_span(node_id, line, date):
    """(first, last) scheduled departure on a date, as datetimes, or None.

    So a trip planned for 03:00 can say "the first train is at 05:57" rather
    than reporting no route and leaving the reader to guess why.
    """
    index = load()
    if not index:
        return None
    table = index.get("departures", {}).get(node_id, {}).get(line)
    if not table:
        return None

    midnight = dt.datetime.combine(date, dt.time.min)
    times = []
    for service in services_on(date):
        times += table.get(service, [])
    if not times:
        return None
    return (midnight + dt.timedelta(seconds=min(times)),
            midnight + dt.timedelta(seconds=max(times)))


def coverage():
    """What the index holds, for /api/live and the report."""
    index = load()
    if not index:
        return {"available": False}

    departures = index.get("departures", {})
    lines = sorted({line for byline in departures.values() for line in byline})
    total = sum(len(times) for byline in departures.values()
                for byservice in byline.values() for times in byservice.values())
    dates = covered_dates()
    return {
        "available": True,
        "builtAt": index.get("builtAt"),
        "nodes": len(departures),
        "lines": lines,
        "departureTimes": total,
        "firstDate": dates[0] if dates else None,
        "lastDate": dates[-1] if dates else None,
        "unmatched": index.get("unmatched", []),
    }
