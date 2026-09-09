"""
tools_build_buses.py
---------------------
Generate bus routes for the graph from TTC's static GTFS.

The graph was hand-written: subway stations, a downtown streetcar grid, and a
few regional corridors. That leaves most of the city reachable only by
subway, so the reach map says north Etobicoke and east Scarborough are forty
minutes from everywhere when in practice they have a bus every eight.

Hand-writing bus routes would mean typing several hundred stop coordinates
and inventing the times between them. GTFS already has both, correctly, so
this generates them.

Three decisions worth knowing
-----------------------------
**Stops are thinned.** A TTC bus route has a stop every 200 metres, and all
of them in the graph would mean 9,000 nodes for a reach map that runs
Dijkstra on every click. Kept stops are at least MIN_SPACING_M apart along
the route, which preserves the shape and the endpoints while cutting the
count by roughly a factor of five.

**Ride times come from the timetable, not a guess.** For each pair of kept
stops the median scheduled travel time between them is used. The rest of the
graph's hop times are estimates; these are not, and a bus that GTFS says
takes eleven minutes between two points is not going to be improved by
rounding it to a nicer number.

**Routes are named "<number> <name>"** -- "63 Ossington" -- which is the same
convention the streetcars use. That is not cosmetic: realtime.route_id_of
parses the leading number to find the route in the live feed, and
tools_build_schedule matches it to a GTFS route_short_name. Naming them this
way means the new routes get live headways, alerts and timetabled departures
without another line of code.

Output
------
    network/bus_routes.json   consumed by network/buses.py

Usage
-----
    python tools_build_buses.py --zip path/to/gtfs.zip
    python tools_build_buses.py --routes 30 --spacing 900
"""

import argparse
import json
import os
import statistics
import sys
import zipfile
from collections import Counter, defaultdict

PROJ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJ)

from gtfs import rows, to_seconds                 # noqa: E402
from geo import metres                            # noqa: E402

OUTPUT = os.path.join(PROJ, "network", "bus_routes.json")

# How many of the busiest bus routes to include. Busiest by trip count, which
# is a decent proxy for "a route somebody would actually plan around".
DEFAULT_ROUTES = 28

# Minimum distance between kept stops, along the route.
DEFAULT_SPACING_M = 900.0

# A generated stop this close to another stop is the same place to change at,
# and gets a transfer edge rather than a duplicate node.
#
# 400 m rather than something tighter because the graph's hand-placed nodes
# are approximate -- the streetcar intersections sit a few hundred metres
# from the real stops -- so a tight radius rejects transfers that exist.
TRANSFER_RADIUS_M = 400.0

# Walking between a bus stop and a station platform. The graph's existing
# transfers use 3 minutes for a same-spot change; a bus stop outside a
# station is about the same.
TRANSFER_MINUTES = 3

# Guard rails on a derived hop time. GTFS occasionally has two stops with the
# same scheduled minute, and a zero-cost edge makes two places the same place.
MIN_HOP_MIN = 1
MAX_HOP_MIN = 40


def busiest_bus_routes(archive, limit):
    """The `limit` bus routes with the most trips."""
    routes = {r["route_id"]: r for r in rows(archive, "routes.txt")
              if r.get("route_type") == "3"}
    counts = Counter()
    for trip in rows(archive, "trips.txt"):
        if trip["route_id"] in routes:
            counts[trip["route_id"]] += 1
    chosen = []
    for route_id, _n in counts.most_common(limit):
        route = routes[route_id]
        short = (route.get("route_short_name") or "").strip()
        long_name = (route.get("route_long_name") or "").strip()
        if not short:
            continue
        chosen.append({"route_id": route_id, "short": short,
                       "line": f"{short} {long_name}".strip()})
    return chosen


def longest_trip_per_route(archive, wanted):
    """The trip with the most stops on each route, as its representative shape.

    A route has dozens of patterns -- short turns, branches, night variants.
    The longest one is the closest thing to "the whole route", and picking one
    pattern keeps the graph a line rather than a tangle of near-duplicates.
    """
    route_of_trip = {}
    for trip in rows(archive, "trips.txt"):
        if trip["route_id"] in wanted:
            route_of_trip[trip["trip_id"]] = trip["route_id"]

    # sequence of (stop_id, seconds) per trip, and the trip length per route
    per_trip = defaultdict(list)
    for row in rows(archive, "stop_times.txt"):
        route_id = route_of_trip.get(row["trip_id"])
        if route_id is None:
            continue
        seconds = to_seconds(row.get("departure_time") or row.get("arrival_time"))
        if seconds is None:
            continue
        per_trip[row["trip_id"]].append((int(row["stop_sequence"]), row["stop_id"],
                                         seconds))

    best = {}
    for trip_id, stops in per_trip.items():
        route_id = route_of_trip[trip_id]
        if route_id not in best or len(stops) > len(best[route_id][1]):
            best[route_id] = (trip_id, sorted(stops))
    return best, per_trip, route_of_trip


def median_hops(per_trip, route_of_trip):
    """{(route_id, stop_a, stop_b): median seconds} over every trip.

    Consecutive-stop times vary by time of day; the median across all trips
    is a fair single number for a graph that has one edge per pair.
    """
    gaps = defaultdict(list)
    for trip_id, stops in per_trip.items():
        route_id = route_of_trip[trip_id]
        ordered = sorted(stops)
        for (_s1, a, t1), (_s2, b, t2) in zip(ordered, ordered[1:]):
            if 0 < t2 - t1 < 3600:
                gaps[(route_id, a, b)].append(t2 - t1)
    return {key: statistics.median(values) for key, values in gaps.items()}


def thin(sequence, positions, spacing):
    """Keep stops at least `spacing` apart along the route, plus both ends."""
    kept = []
    for _seq, stop_id, seconds in sequence:
        if stop_id not in positions:
            continue
        if not kept:
            kept.append((stop_id, seconds))
            continue
        lat, lon = positions[stop_id][:2]
        plat, plon = positions[kept[-1][0]][:2]
        if metres(plat, plon, lat, lon) >= spacing:
            kept.append((stop_id, seconds))
    # Always keep the terminus, so a route does not stop short of its end.
    if sequence:
        last = sequence[-1]
        if last[1] in positions and (not kept or kept[-1][0] != last[1]):
            kept.append((last[1], last[2]))
    return kept


def hop_minutes(route_id, kept, hops, positions):
    """Minutes between each pair of kept stops.

    Summed from the timetable across the stops that were thinned out, so
    removing stops does not remove the time it takes to pass them. Falls back
    to distance at a bus's average speed where the timetable has a gap.
    """
    out = []
    for (a, ta), (b, tb) in zip(kept, kept[1:]):
        scheduled = tb - ta
        if not (0 < scheduled < 3600):
            # No usable timetable difference: 18 km/h is roughly a city bus
            # including stops.
            km = metres(*positions[a][:2], *positions[b][:2]) / 1000.0
            scheduled = km / 18.0 * 3600
        minutes = int(round(scheduled / 60.0))
        out.append(max(MIN_HOP_MIN, min(MAX_HOP_MIN, minutes)))
    return out


def _one_route(route, sequence, positions, hops, spacing, existing, seen_ids,
               transfers):
    """One generated route: its thinned stops, its hop times, its transfers.

    Returns None if too little of the route survived thinning to be worth
    adding -- a two-stop line is a pair of points, not a route.
    """
    kept = thin(sequence, positions, spacing)
    if len(kept) < 3:
        return None

    stops = []
    for stop_id, _seconds in kept:
        lat, lon, name = positions[stop_id]
        node_id = f"b{route['short']}_{stop_id}"
        if node_id in seen_ids:
            continue
        seen_ids.add(node_id)
        stops.append({"id": node_id, "name": name, "lat": lat, "lon": lon})

        # A generated stop near an existing node is a place to change. Every
        # one of them, not just the first: a stop outside a station that also
        # meets a streetcar is two changes, and taking only one leaves the
        # other unreachable.
        for other_id, other in existing.items():
            if metres(lat, lon, other["lat"], other["lon"]) <= TRANSFER_RADIUS_M:
                transfers.append([node_id, other_id, TRANSFER_MINUTES])

    if len(stops) < 3:
        return None
    return {
        "line": route["line"],
        "stops": stops,
        "hops": hop_minutes(route["route_id"], kept, hops,
                            positions)[:len(stops) - 1],
    }


def _add_crossings(out_routes, transfers):
    """Transfer edges where two generated routes meet. Returns how many.

    Without these each route is a line reachable only through its handful of
    station transfers, which is not a network -- crossing Scarborough would
    mean riding downtown and back. Routes meeting at an intersection is most
    of how buses are actually used.
    """
    placed = [(stop["id"], stop["lat"], stop["lon"], route["line"])
              for route in out_routes for stop in route["stops"]]
    crossings = 0
    for index, (id_a, lat_a, lon_a, line_a) in enumerate(placed):
        for id_b, lat_b, lon_b, line_b in placed[index + 1:]:
            if line_a == line_b:
                continue
            if metres(lat_a, lon_a, lat_b, lon_b) <= TRANSFER_RADIUS_M:
                transfers.append([id_a, id_b, TRANSFER_MINUTES])
                crossings += 1
    return crossings


def build(zip_path, route_limit, spacing):
    archive = zipfile.ZipFile(zip_path)
    positions = {s["stop_id"]: (float(s["stop_lat"]), float(s["stop_lon"]),
                                s["stop_name"])
                 for s in rows(archive, "stops.txt")}

    chosen = busiest_bus_routes(archive, route_limit)
    wanted = {route["route_id"] for route in chosen}
    print(f"  {len(chosen)} bus routes selected")

    print("  streaming stop_times...")
    best, per_trip, route_of_trip = longest_trip_per_route(archive, wanted)
    hops = median_hops(per_trip, route_of_trip)

    # The hand-built graph only.
    #
    # `network` runs buses.load() at import, so importing it here hands back
    # a graph that already contains this tool's own previous output. Matching
    # against that made every stop find *itself* from the last run and
    # transfer to it -- 388 self-loops, and a second run that reported six
    # times as many transfer edges as the first. A build tool whose input
    # includes its own output has to say which is which.
    from network import nodes as all_nodes
    existing = {node_id: node for node_id, node in all_nodes.items()
                if node["mode"] != "bus"}
    out_routes, transfers = [], []
    seen_ids = set()

    out_routes, transfers = [], []
    seen_ids = set()
    for route in chosen:
        entry = best.get(route["route_id"])
        if entry is None:
            continue
        built = _one_route(route, entry[1], positions, hops, spacing,
                           existing, seen_ids, transfers)
        if built is not None:
            out_routes.append(built)

    # Bus to bus, where two routes cross.
    #
    # Without these each route is a line reachable only through its handful
    # of subway transfers, which is not a network -- crossing Scarborough
    # would mean riding downtown and back. Routes crossing at an
    # intersection is most of how buses are actually used.
    crossings = _add_crossings(out_routes, transfers)
    print(f"  {crossings} bus-to-bus crossings")

    # Order matters. Prune first, so the island check is not fooled by an
    # edge to a stop that was never emitted; deduplicate next, so it is not
    # fooled into thinking a pair is joined twice either; stitch last, since
    # it is the only step that needs to know what is actually reachable; then
    # deduplicate once more, because a bridge can land on a pair that already
    # existed.
    dangling = _prune_dangling(out_routes, transfers)
    if dangling:
        print(f"  {dangling} transfer edge(s) to discarded stops pruned")
    dropped = _dedupe(transfers)

    from network import adj as all_adj
    # Same reasoning: only the edges between hand-built nodes.
    existing_adj = {node_id: [edge for edge in edges if edge["to"] in existing]
                    for node_id, edges in all_adj.items() if node_id in existing}
    stitched = _stitch_islands(out_routes, transfers, existing, existing_adj)
    if stitched:
        print(f"  {stitched} island(s) stitched in on foot")
    dropped += _dedupe(transfers)
    if dropped:
        print(f"  {dropped} duplicate transfer edge(s) dropped")

    payload = {
        "source": "TTC static GTFS",
        "routeCount": len(out_routes),
        "spacingMetres": spacing,
        "transferRadiusMetres": TRANSFER_RADIUS_M,
        "transferMinutes": TRANSFER_MINUTES,
        "routes": out_routes,
        "transfers": transfers,
    }
    with open(OUTPUT, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"))

    total_stops = sum(len(r["stops"]) for r in out_routes)
    print(f"  {len(out_routes)} routes, {total_stops} stops, "
          f"{len(transfers)} transfer edges")
    print(f"  wrote {OUTPUT} ({os.path.getsize(OUTPUT) / 1e6:.2f} MB)")
    return payload


def _dedupe(transfers):
    """One edge per pair of stops.

    A stop outside a station can pick up the same neighbour twice -- once as
    a station transfer, once as a bus crossing -- and add_edge appends
    without looking, so the graph ends up with parallel duplicates. Harmless
    to Dijkstra, and it means the map draws over itself and every scan does
    the work twice.
    """
    unique, seen = [], set()
    for edge in transfers:
        key = tuple(sorted(edge[:2]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(edge)
    dropped = len(transfers) - len(unique)
    transfers[:] = unique
    return dropped


def _prune_dangling(out_routes, transfers):
    """Drop transfer edges pointing at a stop that was never emitted.

    A route with fewer than three usable stops is discarded, and its station
    transfers had already been appended by then -- so the list kept edges to
    stops that do not exist. add_edge drops those at load time with a
    warning, which is the right behaviour and the wrong place to find out.

    Worse, they made the island check believe two components were joined,
    which is how eleven stops ended up in the graph reachable from nowhere.
    """
    emitted = {stop["id"] for route in out_routes for stop in route["stops"]}
    kept = [edge for edge in transfers
            if (edge[0] in emitted or not edge[0].startswith("b"))
            and (edge[1] in emitted or not edge[1].startswith("b"))]
    dropped = len(transfers) - len(kept)
    transfers[:] = kept
    return dropped


def _stitch_islands(out_routes, transfers, existing, existing_adj):
    """Connect any stop the transfers left unreachable, on foot.

    Crossings and station transfers get most stops connected and leave a few:
    the far end of a route that meets nothing, or a pair of routes that only
    cross each other. Those came out as islands -- in the graph, reachable
    from nowhere -- which is worse than not adding them, because the reach
    map would show a stop it can never route to.

    Dropping them would throw away real stops. Each island is joined to the
    nearest reachable node by a walking transfer, timed by how long the walk
    takes rather than by the flat platform-change penalty: 900 m between two
    stops is not a 3-minute change.

    Connectivity is judged from the edges that will actually be emitted, plus
    the real adjacency of the hand-built graph -- not from an assumption that
    the mainland is connected.
    """
    position = {stop["id"]: (stop["lat"], stop["lon"])
                for route in out_routes for stop in route["stops"]}
    for node_id, node in existing.items():
        position[node_id] = (node["lat"], node["lon"])

    neighbours = defaultdict(set)

    def link(a, b):
        neighbours[a].add(b)
        neighbours[b].add(a)

    for node_id, edges in existing_adj.items():
        for edge in edges:
            link(node_id, edge["to"])
    for route in out_routes:
        for before, after in zip(route["stops"], route["stops"][1:]):
            link(before["id"], after["id"])
    for edge in transfers:
        link(edge[0], edge[1])

    def component(seed):
        seen, queue = {seed}, [seed]
        while queue:
            for neighbour in neighbours[queue.pop()]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append(neighbour)
        return seen

    # The mainland is whichever component holds the hand-built graph.
    reachable = component(next(iter(existing)))
    islands = 0
    while True:
        stranded = [node_id for node_id in position if node_id not in reachable]
        if not stranded:
            break
        island = component(stranded[0])
        best = None
        for node_id in island:
            lat, lon = position[node_id]
            for other in reachable:
                if other not in position:
                    continue
                distance = metres(lat, lon, *position[other])
                if best is None or distance < best[2]:
                    best = (node_id, other, distance)
        if best is None:
            break
        node_id, other, distance = best
        walk = max(TRANSFER_MINUTES, int(round(distance / 1000.0 / 4.8 * 60)))
        transfers.append([node_id, other, walk])
        link(node_id, other)
        reachable |= island
        islands += 1
    return islands


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    parser.add_argument("--zip", required=True, help="TTC GTFS archive")
    parser.add_argument("--routes", type=int, default=DEFAULT_ROUTES)
    parser.add_argument("--spacing", type=float, default=DEFAULT_SPACING_M)
    args = parser.parse_args()
    build(args.zip, args.routes, args.spacing)
    return 0


if __name__ == "__main__":
    sys.exit(main())
