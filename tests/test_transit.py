"""Tests for the graph, the routing engine, and the HTTP surface.

The repository had none. The CI workflow lints and does not test, which is
honest but means nothing here has ever been checked by anything but hand.

Every test that names a bug describes one that was really in this code.
"""

import json
import math
import os
import sys
from collections import deque

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network import nodes, adj, WAIT_BY_MODE, DEFAULT_WAIT_MIN  # noqa: E402
from routing import build_route, compute_times, haversine_km, walk_minutes  # noqa: E402

# Somewhere central and somewhere north, far enough apart to need the subway.
UNION = (43.6453, -79.3806)
FINCH = (43.7805, -79.4151)


# ------------------------------------------------------------------- graph

def test_the_graph_is_one_connected_network():
    """Every stop reachable from every other. A typo in a station id used to
    drop an edge in silence, and an island of stops looks like a modelling
    choice rather than a mistake."""
    start = next(iter(nodes))
    seen, queue = {start}, deque([start])
    while queue:
        for edge in adj[queue.popleft()]:
            if edge["to"] not in seen:
                seen.add(edge["to"])
                queue.append(edge["to"])
    stranded = sorted(nodes[n]["name"] for n in set(nodes) - seen)
    assert not stranded, f"unreachable stops: {stranded}"


def test_every_edge_goes_both_ways():
    for a, edges in adj.items():
        for edge in edges:
            back = [e for e in adj[edge["to"]] if e["to"] == a and e["line"] == edge["line"]]
            assert back, f"{a} -> {edge['to']} on {edge['line']} has no return"
            assert back[0]["min"] == edge["min"], "and costs the same each way"


def test_every_mode_has_a_wait_time():
    """Anything missing falls back to DEFAULT_WAIT_MIN, which is a shrug, not
    a measurement. Reaching it means somebody added a mode and forgot."""
    assert {n["mode"] for n in nodes.values()} <= set(WAIT_BY_MODE)
    assert DEFAULT_WAIT_MIN > 0


def test_no_stop_pair_is_joined_twice_by_the_same_line():
    """add_edge appends without looking, so a station listed in two chains of
    the same line would quietly get a parallel duplicate. Harmless to
    Dijkstra, and it means the map draws over itself and every scan does the
    work twice."""
    for a, edges in adj.items():
        keys = [(e["to"], e["line"]) for e in edges]
        assert len(keys) == len(set(keys)), f"{a} has a duplicated edge"


def test_two_lines_may_still_share_a_pair_of_stops():
    """Spadina and St George really are one stop apart on both Line 1 and
    Line 2. The check above must not have outlawed that."""
    pairs = [e["line"] for e in adj["spadina"] if e["to"] == "stgeorge"]
    assert len(pairs) == 2 and len(set(pairs)) == 2


def test_every_stop_is_inside_greater_toronto():
    for nid, n in nodes.items():
        assert 43.0 < n["lat"] < 44.5, f"{nid} latitude {n['lat']}"
        assert -80.5 < n["lon"] < -78.5, f"{nid} longitude {n['lon']}"


def test_no_edge_is_free_or_negative():
    """A zero-cost edge makes two stops the same place; a negative one breaks
    the assumption Dijkstra rests on."""
    for a, edges in adj.items():
        for edge in edges:
            assert edge["min"] > 0, f"{a} -> {edge['to']} costs {edge['min']}"


# ----------------------------------------------------------------- distance

def test_haversine_against_a_known_distance():
    """Union to Finch is about 15 km as the crow flies."""
    km = haversine_km(*UNION, *FINCH)
    assert 14 < km < 17, km


def test_haversine_is_symmetric_and_zero_at_a_point():
    assert haversine_km(*UNION, *FINCH) == pytest.approx(haversine_km(*FINCH, *UNION))
    assert haversine_km(*UNION, *UNION) == pytest.approx(0.0)


def test_walking_is_slower_than_riding_the_length_of_the_line():
    ride = build_route(*UNION, *FINCH)["total"]
    assert ride < walk_minutes(haversine_km(*UNION, *FINCH))


# ------------------------------------------------------------ reachability

def test_every_stop_gets_a_finite_time():
    times = compute_times(*UNION)
    assert set(times) == set(nodes)
    assert all(math.isfinite(t) and t > 0 for t in times.values())


def test_nearby_stops_come_out_sooner_than_distant_ones():
    times = compute_times(*UNION)
    assert times["union"] < times["finch"]


def test_standing_on_a_stop_still_costs_the_wait():
    """You do not board the instant you arrive, and the heat map should not
    pretend otherwise."""
    times = compute_times(nodes["union"]["lat"], nodes["union"]["lon"])
    assert times["union"] == pytest.approx(WAIT_BY_MODE[nodes["union"]["mode"]], abs=0.1)


# ---------------------------------------------------------------- routing

def test_a_trip_totals_its_own_segments():
    """The bug: `total` came from Dijkstra and the segments were built
    separately, so they disagreed by exactly the boarding wait -- 45.1
    minutes at the top of a page whose legs added up to 41.1. The page
    prints both numbers."""
    route = build_route(*UNION, *FINCH)
    assert route["total"] == pytest.approx(sum(s["minutes"] for s in route["segments"]))
    assert route["totalKm"] == pytest.approx(sum(s["km"] for s in route["segments"]))


def test_the_boarding_wait_is_on_a_leg_and_labelled():
    """It is real time and it has to live somewhere. It belongs to boarding,
    so it goes on the first leg that is not a walk, and says so."""
    route = build_route(*UNION, *FINCH)
    waits = [s for s in route["segments"] if s.get("wait")]
    assert len(waits) == 1, "charged once, on boarding"
    leg = waits[0]
    assert leg["type"] != "walk", "you do not wait for a pavement"
    assert leg is route["segments"][1], "the first leg after the walk to the stop"
    assert leg["wait"] == WAIT_BY_MODE[leg["from"]["mode"]], "the wait for that mode"


def test_a_trip_starts_where_you_are_and_ends_where_you_asked():
    route = build_route(*UNION, *FINCH)
    first, last = route["segments"][0], route["segments"][-1]
    assert first["from"]["lat"] == pytest.approx(UNION[0])
    assert last["to"]["lat"] == pytest.approx(FINCH[0])
    assert first["type"] == "walk" and last["type"] == "walk"


def test_segments_join_up_end_to_end():
    """Each leg has to start where the last one finished, or the itinerary
    is describing a teleport."""
    segs = build_route(*UNION, *FINCH)["segments"]
    for before, after in zip(segs, segs[1:]):
        assert before["to"]["lat"] == pytest.approx(after["from"]["lat"])
        assert before["to"]["lon"] == pytest.approx(after["from"]["lon"])


def test_a_very_short_trip_is_just_a_walk():
    """Two minutes down the street should not route you through the subway."""
    route = build_route(43.6453, -79.3806, 43.6470, -79.3810)
    assert [s["type"] for s in route["segments"]] == ["walk"]


def test_a_trip_to_where_you_already_are_costs_nothing():
    route = build_route(*UNION, *UNION)
    assert route["total"] == pytest.approx(0.0)


# ------------------------------------------------------------------- HTTP

def test_the_page_loads(client):
    assert client.get("/").status_code == 200


def test_the_network_endpoint_describes_the_whole_graph(client):
    body = client.get("/api/network").get_json()
    assert set(body["nodes"]) == set(nodes)
    assert body["edges"], "edges are what the map draws"
    for a, b, minutes, line in body["edges"]:
        assert a in nodes and b in nodes and minutes > 0 and line


def test_each_edge_is_listed_once(client):
    """adj holds both directions; the map only needs one line drawn."""
    edges = client.get("/api/network").get_json()["edges"]
    keys = [tuple(sorted((a, b))) + (line,) for a, b, _m, line in edges]
    assert len(keys) == len(set(keys))


def test_reach_returns_a_time_for_every_stop(client):
    """`times` under its own key, with `live` beside it. Flat, there was
    nowhere to put the liveness flag that a node id could not also occupy."""
    body = client.post("/api/reach", json={"lat": UNION[0], "lon": UNION[1],
                                           "live": False}).get_json()
    assert set(body["times"]) == set(nodes)
    assert body["live"] is False


def test_route_returns_a_usable_itinerary(client):
    body = client.post("/api/route", json={
        "olat": UNION[0], "olon": UNION[1], "dlat": FINCH[0], "dlon": FINCH[1]}).get_json()
    assert body["total"] > 0 and body["segments"]


# ------------------------------------------------------------- bad requests

@pytest.mark.parametrize("body,why", [
    ({"lon": -79.4}, "missing lat"),
    ({"lat": 43.6}, "missing lon"),
    ({"lat": "banana", "lon": -79.4}, "not a number"),
    ({"lat": None, "lon": -79.4}, "null"),
    ({"lat": 999, "lon": -79.4}, "off the globe"),
    ({"lat": 43.6, "lon": 999}, "longitude off the globe"),
    ([1, 2], "not an object"),
    ("hello", "not an object"),
])
def test_a_bad_reach_request_is_400_not_500(client, body, why):
    """Every one of these used to be a 500 with a stack trace: the handler
    was `float(body['lat'])` with nothing around it."""
    res = client.post("/api/reach", json=body)
    assert res.status_code == 400, why
    assert res.get_json()["error"]


@pytest.mark.parametrize("value", ["nan", "NaN", "inf", "-inf", "Infinity"])
def test_a_non_finite_coordinate_is_refused(client, value):
    """float() accepts these. NaN then travels into the response, where
    jsonify writes a bare NaN token -- which is not valid JSON, so the
    browser's JSON.parse throws and the page fails with an error about the
    response instead of about the input."""
    res = client.post("/api/reach", json={"lat": value, "lon": -79.4})
    assert res.status_code == 400


def test_no_response_can_contain_nan(client):
    for path, body in [("/api/reach", {"lat": UNION[0], "lon": UNION[1]}),
                       ("/api/route", {"olat": UNION[0], "olon": UNION[1],
                                       "dlat": FINCH[0], "dlon": FINCH[1]}),
                       ("/api/network", None)]:
        res = client.post(path, json=body) if body else client.get(path)
        raw = res.get_data(as_text=True)
        assert "NaN" not in raw and "Infinity" not in raw
        json.loads(raw)


def test_a_bad_route_request_is_400_not_500(client):
    for body in [{}, {"olat": 43.6, "olon": -79.4}, {"olat": "x", "olon": -79.4,
                                                     "dlat": 43.7, "dlon": -79.4}]:
        assert client.post("/api/route", json=body).status_code == 400


def test_malformed_json_is_not_a_500(client):
    res = client.post("/api/reach", data="{not json", content_type="application/json")
    assert res.status_code == 400
