"""
tools_build_schedule.py
------------------------
Turn TTC's static GTFS into a departure index this graph can query.

Why a build step
----------------
stop_times.txt is 207 MB. Parsing it per request is out of the question and
parsing it at startup would put a minute on every boot, so it is streamed
once here and reduced to the only thing the router asks: for a given stop and
line, when does the next vehicle leave? That reduction is a few megabytes.

Why the matching is constrained by route
----------------------------------------
The graph's nodes are hand-placed, and matching each one to its nearest GTFS
stop gets the subway right -- stations matched to within 5 to 94 metres -- and
the streetcar intersections wrong. "Spadina & King" matched a stop on
Bathurst 61 metres away, because downtown has a stop on every corner and
nearest-in-metres does not know which street it is on.

So a node is matched only against stops that its own line actually serves.
That needs route -> trip -> stop, which is the streaming pass, which is why
the two steps are in one tool.

Output
------
    schedule_index.json

    {"builtAt": ..., "feedVersion": ...,
     "services": {"20260908": ["weekday-service-id", ...], ...},
     "departures": {node_id: {line: {service_id: [seconds after midnight, ...]}}}}

Departure seconds can exceed 86400: GTFS expresses a 01:30 train on a
service that began the previous morning as 25:30:00, and collapsing that to
01:30 would file the last train of the night under the start of the day.

Usage
-----
    python tools_build_schedule.py                    # fetch and build
    python tools_build_schedule.py --zip path/to.zip  # build from a local copy
"""

import argparse
import json
import os
import sys
import time
import zipfile

PROJ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJ)

from gtfs import (ARCHIVE_URL, fetch, rows, stop_positions,  # noqa: E402
                  to_seconds)
from geo import metres                            # noqa: E402

from network import lines_at, nodes                # noqa: E402

# The archive URL lives in gtfs, which is what both build tools read.
GTFS_URL = ARCHIVE_URL

INDEX_PATH = os.path.join(PROJ, "schedule_index.json")

# How far a node may sit from a stop on its own line and still be considered
# the same place.
#
# Generous, deliberately. The candidate set is already restricted to stops
# that this line serves, so the nearest one is almost certainly the right
# stop even at half a kilometre -- and the graph's streetcar nodes are
# synthetic, placed on a lat/lon grid of major intersections rather than
# surveyed, so they sit a few hundred metres off the real stop as a matter of
# course. Every match records its distance, so an approximate node is visible
# rather than hidden behind a threshold.
MAX_MATCH_METRES = 900.0


def log(message):
    print(message, flush=True)


# ---------------------------------------------------------------------------
# Which GTFS route is which line in the graph
# ---------------------------------------------------------------------------
def graph_lines():
    """Every line name in the graph, excluding transfers.

    The union of lines_at over every node -- the same question that function
    answers per stop, asked of the whole graph, rather than a second walk
    over adj that could disagree with it about what counts as a line.
    """
    return {line for node_id in nodes for line in lines_at(node_id)}


def match_routes(archive, lines):
    """{line name: route_id}.

    Surface lines carry the route number as their name's prefix, which is
    GTFS's route_short_name. The subway matches on the long name, which the
    feed spells almost identically to the graph -- "Line 2 (Bloor - Danforth)"
    against "Line 2 (Bloor-Danforth)" -- so the comparison ignores spacing
    and case rather than requiring the punctuation to agree.
    """
    def loose(text):
        return "".join(ch for ch in (text or "").lower() if ch.isalnum())

    by_short, by_long = {}, {}
    for route in rows(archive, "routes.txt"):
        by_short.setdefault(route.get("route_short_name", "").strip(), route["route_id"])
        by_long.setdefault(loose(route.get("route_long_name")), route["route_id"])

    matched, missing = {}, []
    for line in sorted(lines):
        # "509/510 Harbourfront" is two routes sharing track, so the prefix
        # has to be split before it will match either of them.
        prefix = line.split()[0] if line else ""
        candidates = [part for part in prefix.split("/") if part]
        hit = next((by_short[part] for part in candidates if part in by_short), None)
        if hit is not None:
            matched[line] = hit
            continue
        if loose(line) in by_long:
            matched[line] = by_long[loose(line)]
            continue
        missing.append(line)
    return matched, missing


# ---------------------------------------------------------------------------
# The streaming pass
# ---------------------------------------------------------------------------
def load_trips(archive, wanted_routes):
    """{trip_id: (route_id, service_id)} for the routes in the graph."""
    keep = {}
    for trip in rows(archive, "trips.txt"):
        if trip["route_id"] in wanted_routes:
            keep[trip["trip_id"]] = (trip["route_id"], trip["service_id"])
    return keep


def collect_departures(archive, trips):
    """{(route_id, stop_id, service_id): [departure seconds]}.

    One pass over 207 MB, keeping only the trips that belong to a line in the
    graph. Everything else is discarded as it goes by rather than held.
    """
    found = {}
    seen = 0
    for row in rows(archive, "stop_times.txt"):
        seen += 1
        if seen % 2_000_000 == 0:
            log(f"    {seen:,} stop_times rows...")
        trip = trips.get(row["trip_id"])
        if trip is None:
            continue
        seconds = to_seconds(row.get("departure_time") or row.get("arrival_time"))
        if seconds is None:
            continue
        route_id, service_id = trip
        found.setdefault((route_id, row["stop_id"], service_id), []).append(seconds)
    log(f"    {seen:,} rows read")
    return found


def match_nodes(departures, positions, route_of_line):
    """{node_id: {line: stop_id}}, matching within each line's own stops.

    Nearest-in-metres over all 9,402 stops puts "Spadina & King" on Bathurst.
    Nearest among the stops that line actually serves does not.
    """
    stops_by_route = {}
    for (route_id, stop_id, _service) in departures:
        stops_by_route.setdefault(route_id, set()).add(stop_id)

    matches, unmatched = {}, []
    for node_id, node in nodes.items():
        for line in lines_at(node_id):
            route_id = route_of_line.get(line)
            candidates = stops_by_route.get(route_id) if route_id else None
            if not candidates:
                continue
            best, best_distance = None, None
            for stop_id in candidates:
                lat, lon, _name = positions[stop_id]
                distance = metres(node["lat"], node["lon"], lat, lon)
                if best_distance is None or distance < best_distance:
                    best, best_distance = stop_id, distance
            if best_distance is not None and best_distance <= MAX_MATCH_METRES:
                matches.setdefault(node_id, {})[line] = (best, round(best_distance))
            else:
                unmatched.append((node_id, line, round(best_distance or -1)))
    return matches, unmatched


def load_services(archive):
    """{yyyymmdd: [service_id, ...]} for the dates the feed covers.

    calendar.txt gives the weekly pattern and calendar_dates.txt the
    exceptions. Both matter: a holiday runs a Sunday service on a Tuesday,
    and a router that ignores that is confidently wrong once a year.
    """
    weekly = []
    try:
        weekly = list(rows(archive, "calendar.txt"))
    except KeyError:
        pass

    added, removed = {}, {}
    try:
        for row in rows(archive, "calendar_dates.txt"):
            target = added if row["exception_type"] == "1" else removed
            target.setdefault(row["date"], set()).add(row["service_id"])
    except KeyError:
        pass

    import datetime as dt
    days = ("monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday")
    by_date = {}
    for service in weekly:
        try:
            start = dt.datetime.strptime(service["start_date"], "%Y%m%d").date()
            end = dt.datetime.strptime(service["end_date"], "%Y%m%d").date()
        except (KeyError, ValueError):
            continue
        day = start
        while day <= end:
            if service.get(days[day.weekday()]) == "1":
                by_date.setdefault(day.strftime("%Y%m%d"), set()).add(service["service_id"])
            day += dt.timedelta(days=1)

    for date, ids in added.items():
        by_date.setdefault(date, set()).update(ids)
    for date, ids in removed.items():
        if date in by_date:
            by_date[date] -= ids

    return {date: sorted(ids) for date, ids in by_date.items() if ids}


# ---------------------------------------------------------------------------
def build(zip_path):
    archive = zipfile.ZipFile(zip_path)

    lines = graph_lines()
    log(f"  graph has {len(lines)} lines")
    route_of_line, missing = match_routes(archive, lines)
    log(f"  matched {len(route_of_line)} to GTFS routes")
    if missing:
        log(f"  no GTFS route for: {missing}")

    log("  loading trips...")
    trips = load_trips(archive, set(route_of_line.values()))
    log(f"    {len(trips):,} trips on those routes")

    log("  streaming stop_times (207 MB)...")
    started = time.time()
    departures = collect_departures(archive, trips)
    log(f"    {len(departures):,} (route, stop, service) groups "
        f"in {time.time() - started:.0f}s")

    log("  matching graph nodes to stops on their own lines...")
    positions = stop_positions(archive)
    matches, unmatched = match_nodes(departures, positions, route_of_line)
    log(f"    matched {sum(len(v) for v in matches.values())} node-line pairs "
        f"across {len(matches)} nodes")
    if unmatched:
        log(f"    {len(unmatched)} pairs had no stop within {MAX_MATCH_METRES:.0f} m")
        for node_id, line, distance in unmatched[:5]:
            log(f"      {node_id} / {line}: nearest {distance} m")

    log("  assembling the index...")
    index, distances, stop_ids = {}, {}, {}
    for node_id, by_line in matches.items():
        for line, (stop_id, distance) in by_line.items():
            distances.setdefault(node_id, {})[line] = distance
            # The GTFS stop this node stands for, and the route id its times
            # came from. Stored because the realtime feed is keyed by exactly
            # this pair: without it, live arrival predictions cannot be
            # attached to a node, which is why the first pass at realtime
            # could only offer an average headway.
            stop_ids.setdefault(node_id, {})[line] = {
                "stopId": stop_id, "routeId": route_of_line[line]}
            route_id = route_of_line[line]
            for (r, s, service), times in departures.items():
                if r == route_id and s == stop_id:
                    slot = index.setdefault(node_id, {}).setdefault(line, {})
                    slot[service] = sorted(set(slot.get(service, []) + times))

    services = load_services(archive)
    total = sum(len(t) for byline in index.values()
                for byservice in byline.values() for t in byservice.values())
    log(f"    {total:,} departure times across {len(services)} service dates")

    payload = {
        "builtAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": GTFS_URL,
        "maxMatchMetres": MAX_MATCH_METRES,
        "services": services,
        "departures": index,
        # How far each node sits from the stop its times come from. A node
        # 600 m away is still on the right line; it is the graph's coordinate
        # that is approximate, and this says so.
        "matchMetres": distances,
        "stops": stop_ids,
        "unmatched": [{"node": n, "line": ln, "nearestMetres": d}
                      for n, ln, d in unmatched],
    }
    with open(INDEX_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"))
    log(f"  wrote {INDEX_PATH} "
        f"({os.path.getsize(INDEX_PATH) / 1e6:.1f} MB)")
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    parser.add_argument("--zip", default=None,
                        help="use a local GTFS archive instead of downloading")
    args = parser.parse_args()

    zip_path = args.zip
    if zip_path is None:
        zip_path = os.path.join(PROJ, "_gtfs.zip")
        if not os.path.exists(zip_path):
            log(f"downloading {GTFS_URL}")
            if not fetch(GTFS_URL, zip_path):
                log("could not download the GTFS archive")
                return 1
        log(f"using {zip_path} ({os.path.getsize(zip_path) / 1e6:.0f} MB)")

    build(zip_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
