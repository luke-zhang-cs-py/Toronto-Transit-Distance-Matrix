"""The bus-route generator (tools/build_buses.py), on a feed of a few rows.

It reads the same 207 MB archive as the schedule builder and writes
network/bus_routes.json, which is most of the graph -- 388 of its 516 stops.
Here the feed is written into tmp_path and the hand-built graph is two
stations, so every stop it keeps, every hop time and every transfer can be
named in an assertion.

The output goes to tmp_path too. A test that wrote network/bus_routes.json
would replace the real graph for every test after it.

Distances, for reading the fixtures: 0.001 degrees of latitude is 111 m and
0.001 of longitude 80 m at this latitude. The tests build with a 500 m
spacing so a route of five stops is enough to see some of them thinned.
"""

import json
import zipfile

import pytest

import network
from tools import build_buses as bb
from trips.geo import metres

# The hand-built graph: two stations 1.6 km apart, joined by a subway edge.
# Broadview is the name that matters -- it starts with "b", like every
# generated stop id, and the pruning step used to take it for one. The old
# bus stop is what `network` holds from the tool's own previous run, sitting
# exactly on a stop of route 10: a transfer to it would mean the build had
# matched against its own output.
NODES = {
    "broadview": {"name": "Broadview", "lat": 43.7000, "lon": -79.4000, "mode": "subway"},
    "chester": {"name": "Chester", "lat": 43.7000, "lon": -79.3800, "mode": "subway"},
    "b_old": {"name": "Last run's stop", "lat": 43.7100, "lon": -79.4000, "mode": "bus"},
}
ADJ = {
    "broadview": [{"to": "chester", "min": 2, "line": "Line 2"},
                  {"to": "b_old", "min": 3, "line": "Transfer"}],
    "chester": [{"to": "broadview", "min": 2, "line": "Line 2"}],
    "b_old": [{"to": "broadview", "min": 3, "line": "Transfer"}],
}

STOPS = {
    # Route 10 runs north from Broadview. A1 is 333 m from A0 and is thinned;
    # A4 is 55 m past A3, kept anyway because it is the terminus.
    "A0": (43.7000, -79.4000), "A1": (43.7030, -79.4000), "A2": (43.7100, -79.4000),
    "A3": (43.7200, -79.4000), "A4": (43.7205, -79.4000),
    # Route 20 crosses route 10 at A3/A4.
    "C0": (43.7200, -79.4100), "C1": (43.7202, -79.4001), "C2": (43.7200, -79.3900),
    # Route 30 is 9 km north, meeting nothing: an island.
    "I0": (43.8000, -79.4000), "I1": (43.8060, -79.4000), "I2": (43.8120, -79.4000),
    # Route 40 has two stops; route 50 is a loop from Chester and back.
    "D0": (43.7500, -79.4500), "D1": (43.7600, -79.4500),
    "X0": (43.7000, -79.3800), "X1": (43.7100, -79.3800),
}

# (trip, route, [(stop, "hh:mm:ss"), ...]) in stop_sequence order.
TRIPS = [
    # The shorter pattern first, so the longer one has to replace it. Its
    # two-hour gap is not a hop time anybody should be given.
    ("t10b", "R10", [("A0", "08:00:00"), ("A1", "10:00:00"), ("A2", "10:02:00")]),
    # A stop missing from stops.txt is passed over; A3 and A4 share a minute.
    ("t10a", "R10", [("A0", "08:00:00"), ("GHOST", "08:00:30"), ("A1", "08:01:00"),
                     ("A2", "08:03:00"), ("A3", "08:06:00"), ("A4", "08:06:00")]),
    # Fifty minutes between C0 and C1 is past the cap on one hop.
    ("t20a", "R20", [("C0", "09:00:00"), ("C1", "09:50:00"), ("C2", "10:00:00")]),
    ("t20b", "R20", [("C0", "11:00:00"), ("C1", "11:50:00"), ("C2", "12:00:00")]),
    # The last stop is one stops.txt does not have.
    ("t30", "R30", [("I0", "07:00:00"), ("I1", "07:02:00"), ("I2", "07:04:00"),
                    ("NOWHERE", "07:06:00")]),
    ("t40", "R40", [("D0", "07:00:00"), ("D1", "07:05:00")]),
    ("t50", "R50", [("X0", "07:00:00"), ("X1", "07:04:00"), ("X0", "07:08:00")]),
    # No usable time on any row, so the route is chosen and has no shape.
    ("t60", "R60", [("A0", ""), ("A2", "")]),
    ("t70", "R70", [("A0", "07:00:00"), ("A2", "07:05:00")]),
    ("t1", "L1", [("A0", "07:00:00"), ("A2", "07:05:00")]),
]

ROUTES = (
    "route_id,route_short_name,route_long_name,route_type\n"
    "R10,10,North,3\n"
    "R20,20,Cross,3\n"
    "R30,30,Island,3\n"
    "R40,40,Two Stops,3\n"
    "R50,50,Loop,3\n"
    "R60,60,Ghost,3\n"
    "R70,,Unnamed,3\n"
    "L1,1,Line 1,1\n")


def feed_tables(trips=TRIPS, routes=ROUTES):
    stop_times = ["trip_id,arrival_time,departure_time,stop_id,stop_sequence"]
    for trip_id, _route, calls in trips:
        for sequence, (stop, when) in enumerate(calls, 1):
            stop_times.append("%s,%s,%s,%s,%d" % (trip_id, when, when, stop, sequence))
    return {
        "routes.txt": routes,
        "trips.txt": "route_id,service_id,trip_id\n" + "".join(
            "%s,wk,%s\n" % (route, trip_id) for trip_id, route, _ in trips),
        "stop_times.txt": "\n".join(stop_times) + "\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\n" + "".join(
            "%s,Stop %s,%s,%s\n" % (stop, stop, lat, lon)
            for stop, (lat, lon) in STOPS.items()),
    }


def write_feed(tmp_path, tables=None):
    path = tmp_path / "gtfs.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, body in (tables or feed_tables()).items():
            archive.writestr(name, "﻿" + body)
    return str(path)


def positions():
    return {stop: (lat, lon, "Stop " + stop) for stop, (lat, lon) in STOPS.items()}


@pytest.fixture
def hand_built(monkeypatch, tmp_path):
    """The two-station graph in place of the real one, and the output in
    tmp_path."""
    monkeypatch.setattr(network, "nodes", NODES)
    monkeypatch.setattr(network, "adj", ADJ)
    out = tmp_path / "bus_routes.json"
    monkeypatch.setattr(bb, "OUTPUT", str(out))
    return out


# ------------------------------------------------------------ choosing routes

def test_the_busiest_bus_routes_are_chosen_by_trip_count(tmp_path):
    archive = zipfile.ZipFile(write_feed(tmp_path))
    chosen = bb.busiest_bus_routes(archive, 10)
    # The subway is not a bus, and a route with no number cannot be named
    # the way realtime and the schedule builder look it up.
    assert [route["line"] for route in chosen] == [
        "10 North", "20 Cross", "30 Island", "40 Two Stops", "50 Loop", "60 Ghost"]
    assert chosen[0] == {"route_id": "R10", "short": "10", "line": "10 North"}
    assert [route["route_id"] for route in bb.busiest_bus_routes(archive, 1)] == ["R10"]


def test_each_route_is_represented_by_its_longest_trip(tmp_path):
    archive = zipfile.ZipFile(write_feed(tmp_path))
    best, per_trip, route_of_trip = bb.longest_trip_per_route(archive, {"R10", "R20", "R60"})
    assert best["R10"][0] == "t10a"
    assert [stop for _seq, stop, _t in best["R10"][1]] == [
        "A0", "GHOST", "A1", "A2", "A3", "A4"]
    assert best["R20"][0] == "t20a", "a tie keeps the first trip seen"
    assert "R60" not in best, "a trip with no usable times has no shape"
    assert set(per_trip) == {"t10a", "t10b", "t20a", "t20b"}
    assert route_of_trip["t60"] == "R60"


def test_hop_times_are_the_median_over_trips_ignoring_impossible_gaps(tmp_path):
    archive = zipfile.ZipFile(write_feed(tmp_path))
    _best, per_trip, route_of_trip = bb.longest_trip_per_route(archive, {"R10", "R20"})
    hops = bb.median_hops(per_trip, route_of_trip)
    assert hops[("R10", "A1", "A2")] == 120
    assert ("R10", "A0", "A1") not in hops, "t10b's two-hour gap is left out"
    assert hops[("R10", "A0", "GHOST")] == 30, "a hop is between stops as listed"
    assert ("R10", "A3", "A4") not in hops, "no time between them is not a hop"
    assert hops[("R20", "C0", "C1")] == 3000


# ------------------------------------------------------------ one route

def test_thinning_keeps_both_ends_and_drops_stops_too_close_together():
    sequence = [(1, "A0", 0), (2, "GHOST", 30), (3, "A1", 60), (4, "A2", 180),
                (5, "A3", 360), (6, "A4", 360)]
    assert bb.thin(sequence, positions(), 500) == [
        ("A0", 0), ("A2", 180), ("A3", 360), ("A4", 360)]
    # Already at the terminus: it is not added twice.
    assert bb.thin(sequence[:5], positions(), 500) == [("A0", 0), ("A2", 180), ("A3", 360)]
    # A terminus nobody has a position for is left off.
    assert bb.thin([(1, "A0", 0), (2, "NOWHERE", 60)], positions(), 500) == [("A0", 0)]
    assert bb.thin([], positions(), 500) == []


def test_hop_minutes_come_from_the_timetable_within_the_guard_rails():
    kept = [("A0", 0), ("A2", 180), ("A3", 3180), ("A4", 3180), ("C2", 9999)]
    assert bb.hop_minutes("R10", kept, {}, positions()) == [
        3,          # three scheduled minutes
        40,         # fifty, capped
        1,          # the same minute: 55 m at 18 km/h, then the 1-minute floor
        3,          # a gap past an hour: 0.8 km at 18 km/h
    ]


def test_a_route_with_too_few_stops_left_is_not_built():
    transfers = []
    sequence = [(1, "D0", 0), (2, "D1", 300)]
    assert bb._one_route({"route_id": "R40", "short": "40", "line": "40 Two Stops"},
                         sequence, positions(), {}, 500, NODES, set(), transfers) is None
    assert transfers == []


# ------------------------------------------------------------ the graph's edges

def test_crossings_join_different_routes_only():
    routes = [{"line": "10 North", "stops": [
                  {"id": "b10_A3", "lat": 43.7200, "lon": -79.4000},
                  {"id": "b10_A4", "lat": 43.7205, "lon": -79.4000}]},
              {"line": "20 Cross", "stops": [
                  {"id": "b20_C0", "lat": 43.7200, "lon": -79.4100},
                  {"id": "b20_C1", "lat": 43.7202, "lon": -79.4001}]}]
    transfers = []
    assert bb._add_crossings(routes, transfers) == 2
    assert transfers == [["b10_A3", "b20_C1", 3], ["b10_A4", "b20_C1", 3]]


def test_a_pair_of_stops_gets_one_edge_however_it_was_found():
    transfers = [["a", "b", 3], ["b", "a", 3], ["a", "c", 3]]
    assert bb._dedupe(transfers) == 1
    assert transfers == [["a", "b", 3], ["a", "c", 3]]


def test_pruning_keeps_hand_built_stations_whose_names_start_with_b():
    """The bug this pins: an end was called dangling if it began with "b"
    and was not an emitted stop -- which Bathurst, Bay, Bloor-Yonge and
    Broadview all are. Every station transfer to them was thrown away."""
    routes = [{"line": "10 North", "stops": [{"id": "b10_A0"}]}]
    transfers = [["b10_A0", "broadview", 3], ["b50_X0", "chester", 3],
                 ["chester", "b99_gone", 3]]
    assert bb._prune_dangling(routes, transfers, {"broadview": {}, "chester": {}}) == 2
    assert transfers == [["b10_A0", "broadview", 3]]


def test_an_island_is_walked_to_from_its_nearest_reachable_stop():
    island = {"line": "30 Island", "stops": [
        {"id": "b30_I0", "lat": 43.8000, "lon": -79.4000},
        {"id": "b30_I1", "lat": 43.8060, "lon": -79.4000}]}
    # chester's neighbour "elsewhere" has no position, so it cannot be the
    # far end of a walk.
    existing = {"broadview": NODES["broadview"], "chester": NODES["chester"]}
    existing_adj = {"broadview": [{"to": "chester"}], "chester": [{"to": "elsewhere"}]}
    transfers = []
    assert bb._stitch_islands([island], transfers, existing, existing_adj) == 1
    walk = round(metres(43.8, -79.4, 43.7, -79.4) / 1000.0 / 4.8 * 60)
    assert transfers == [["b30_I0", "broadview", walk]]
    assert walk > 100, "timed as a walk, not as a 3-minute platform change"


# ------------------------------------------------------------ the build

def test_the_build_writes_routes_and_transfers_from_the_feed(tmp_path, hand_built, capsys):
    payload = bb.build(write_feed(tmp_path), 10, 500.0)
    assert json.loads(hand_built.read_text(encoding="utf-8")) == payload

    routes = {route["line"]: route for route in payload["routes"]}
    # 40 is two stops, 50 loops back onto its own first stop, 60 has no
    # times and 70 no number: four of the seven bus routes are not built.
    assert sorted(routes) == ["10 North", "20 Cross", "30 Island"]
    assert payload["routeCount"] == 3 and payload["spacingMetres"] == 500.0
    assert [s["id"] for s in routes["10 North"]["stops"]] == [
        "b10_A0", "b10_A2", "b10_A3", "b10_A4"]
    assert routes["10 North"]["stops"][0] == {
        "id": "b10_A0", "name": "Stop A0", "lat": 43.7, "lon": -79.4}
    assert routes["10 North"]["hops"] == [3, 3, 1]
    assert routes["20 Cross"]["hops"] == [40, 10]

    transfers = payload["transfers"]
    assert ["b10_A0", "broadview", 3] in transfers, "pruned as if it were a bus stop"
    assert ["b10_A3", "b20_C1", 3] in transfers and ["b10_A4", "b20_C1", 3] in transfers
    assert not any("b_old" in edge for edge in transfers), "matched its own last run"
    assert not any("b50_X0" in edge for edge in transfers), "a stop never emitted"
    walk = round(metres(43.8, -79.4, 43.7205, -79.4) / 1000.0 / 4.8 * 60)
    assert ["b30_I0", "b10_A4", walk] in transfers
    assert len(transfers) == 4

    log = capsys.readouterr().out
    assert "6 bus routes selected" in log
    assert "2 bus-to-bus crossings" in log
    assert "1 transfer edge(s) to discarded stops pruned" in log
    assert "1 island(s) stitched in on foot" in log
    assert "duplicate transfer" not in log
    assert "3 routes, 10 stops, 4 transfer edges" in log


def test_a_transfer_found_twice_is_written_once(tmp_path, hand_built, monkeypatch, capsys):
    real = bb._add_crossings

    def twice(out_routes, transfers):
        found = real(out_routes, transfers)
        transfers.append(list(reversed(transfers[-1][:2])) + [3])
        return found

    monkeypatch.setattr(bb, "_add_crossings", twice)
    payload = bb.build(write_feed(tmp_path), 10, 500.0)
    pairs = [tuple(sorted(edge[:2])) for edge in payload["transfers"]]
    assert len(pairs) == len(set(pairs)) == 4
    assert "1 duplicate transfer edge(s) dropped" in capsys.readouterr().out


def test_a_feed_with_no_bus_routes_writes_an_empty_network(tmp_path, hand_built, capsys):
    tables = feed_tables(trips=[t for t in TRIPS if t[1] == "L1"],
                         routes="route_id,route_short_name,route_long_name,route_type\n"
                                "L1,1,Line 1,1\n")
    payload = bb.build(write_feed(tmp_path, tables), 10, 500.0)
    assert payload["routes"] == [] and payload["transfers"] == []
    log = capsys.readouterr().out
    assert "0 bus routes selected" in log
    assert "pruned" not in log and "stitched" not in log and "duplicate" not in log


def test_the_command_passes_its_options_to_the_build(monkeypatch):
    calls = []
    monkeypatch.setattr(bb, "build", lambda *args: calls.append(args))
    monkeypatch.setattr("sys.argv", ["build_buses.py", "--zip", "feed.zip",
                                     "--routes", "5", "--spacing", "700"])
    assert bb.main() == 0
    assert calls == [("feed.zip", 5, 700.0)]
    monkeypatch.setattr("sys.argv", ["build_buses.py", "--zip", "feed.zip"])
    bb.main()
    assert calls[-1] == ("feed.zip", bb.DEFAULT_ROUTES, bb.DEFAULT_SPACING_M)
