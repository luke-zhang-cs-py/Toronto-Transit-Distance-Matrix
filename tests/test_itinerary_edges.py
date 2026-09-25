"""Trips at the edges of what the planner can answer.

The itinerary builder spends most of its code on judgement rather than
arithmetic: which alternatives are worth showing, when a walk beats a ride,
what to do about a request from somewhere the network does not reach. Those
decisions are only visible at the edges, and the edges had not been reached.

Nothing here needs the live feed or the GTFS archive; the graph is built at
import and is enough.
"""

import datetime as dt

import pytest

from trips import itinerary
from network import nodes


def a_station(index=0):
    node_id = list(nodes)[index]
    return node_id, nodes[node_id]


# ------------------------------------------------------------- getting in


def test_a_request_from_far_outside_gets_the_nearest_stop_anyway():
    """Nothing within the access cap. Returning no stops would mean no
    answer at all; offering the single nearest one means a long access leg
    and a route, which is more use than a shrug."""
    # The middle of the Atlantic: every stop is far outside any cap.
    reachable = itinerary._access_nodes(0.0, -30.0)

    assert len(reachable) == 1, "exactly the nearest, not a list of far ones"
    node_id, minutes = reachable[0]
    assert node_id in nodes
    assert minutes > itinerary.MAX_ACCESS_WALK_MIN, (
        "this case is only interesting if it is past the cap")


def test_a_request_inside_the_network_gets_every_stop_within_the_cap():
    _node_id, node = a_station()
    reachable = itinerary._access_nodes(node["lat"], node["lon"])
    assert len(reachable) > 1
    assert all(minutes <= itinerary.MAX_ACCESS_WALK_MIN
               for _n, minutes in reachable)


def test_driving_gets_a_wider_cap_than_walking():
    """Park-and-ride only makes sense when walking never was an option, so
    the two caps are different numbers rather than one."""
    assert itinerary.MAX_ACCESS_DRIVE_MIN > itinerary.MAX_ACCESS_WALK_MIN

    _node_id, node = a_station()
    far_lat = node["lat"] + 0.25
    walking = itinerary._access_nodes(far_lat, node["lon"],
                                      mode=itinerary.ACCESS_WALK)
    driving = itinerary._access_nodes(far_lat, node["lon"],
                                      mode=itinerary.ACCESS_DRIVE)
    assert len(driving) >= len(walking)


# --------------------------------------------------- choosing between options


def test_two_options_with_the_same_shape_are_not_both_shown():
    """A list of alternatives whose entries differ only in a number nobody
    reads is a longer list, not a more useful one."""
    def option(lines, minutes, arrive):
        return {"kind": "walk+transit", "lines": lines,
                "totalMinutes": minutes, "arriveAt": arrive}

    same_a = option(["Line 1"], 20, "09:20")
    same_b = option(["Line 1"], 20, "09:20")   # rediscovered by a ban
    other = option(["Line 2"], 22, "09:22")

    kept = itinerary._worth_choosing_between([same_a, same_b, other])
    lines = [tuple(o["lines"]) for o in kept]

    assert lines.count(("Line 1",)) == 1, f"the duplicate survived: {lines}"
    assert ("Line 2",) in lines


def test_the_tolerance_is_applied_within_each_kind_not_across_them():
    """Applied globally it hid the thing being compared: from a suburb where
    driving takes 43 minutes and transit 68, the transit trip fell outside
    the tolerance of the best option overall and vanished -- leaving a
    comparison view showing only driving."""
    driving = {"kind": "drive", "lines": [], "totalMinutes": 43,
               "arriveAt": "09:43"}
    transit = {"kind": "walk+transit", "lines": ["Line 1"],
               "totalMinutes": 68, "arriveAt": "10:08"}

    kept = itinerary._worth_choosing_between([driving, transit])
    kinds = {o["kind"] for o in kept}
    assert kinds == {"drive", "walk+transit"}, (
        "the best of each kind must survive, however far apart they are")


def test_a_pure_walk_has_no_line_to_ban():
    """Alternatives are found by banning the line the last option used and
    searching again. A walking route used no line, so there is nothing left
    to exclude and the loop has to stop rather than search forever."""
    origin_id, origin = a_station(0)
    # Somewhere a few hundred metres away: the answer is to walk.
    nearby = (origin["lat"] + 0.001, origin["lon"] + 0.001)

    plan = itinerary.plan((origin["lat"], origin["lon"]), nearby,
                          depart_at=dt.datetime(2026, 9, 15, 9, 0))
    assert plan["options"], "a short hop should still produce an option"


def test_a_walk_only_option_is_offered_when_it_is_short_enough():
    """Below the cap a walk is a real alternative and is listed; above it,
    it is noise."""
    origin_id, origin = a_station(0)
    close = (origin["lat"] + 0.004, origin["lon"])

    plan = itinerary.plan((origin["lat"], origin["lon"]), close,
                          depart_at=dt.datetime(2026, 9, 15, 9, 0))
    walks = [o for o in plan["options"] if o.get("via") is None]
    assert walks, "no walking option was offered for a short trip"
    assert walks[0]["totalMinutes"] <= itinerary.MAX_WALK_ONLY_MIN


def test_one_mode_going_the_whole_way_stops_the_search():
    """If a single line covers the trip there is no second mode to try, and
    continuing would re-search the same graph for the same answer."""
    a_id, a = a_station(0)
    b_id, b = a_station(1)

    plan = itinerary.plan((a["lat"], a["lon"]), (b["lat"], b["lon"]),
                          depart_at=dt.datetime(2026, 9, 15, 9, 0))
    assert plan["options"]
    assert len(plan["options"]) <= 4, "the alternatives should be bounded"


# --------------------------------------------------------- later departures


def test_asking_for_no_later_departures_returns_none():
    """The caller decides how many to show, and zero is a legitimate answer
    to "show me alternatives"."""
    assert itinerary._later_departures(chain=[], count=0) == []
    assert itinerary._later_departures(chain=[], count=-1) == []


def test_a_chain_with_no_timetabled_leg_has_no_later_departures():
    """"The next one is at 17:26" is worth saying; "the next one is in about
    six minutes on average" is not, so a modelled leg offers nothing."""
    chain = [("A", None, None, 0, "model"),
             ("B", "504 King", None, 6, "model")]
    assert itinerary._later_departures(chain, count=3) == []


def test_a_timetabled_leg_whose_boarding_time_is_unknown(monkeypatch):
    """The boarding time is what the later list is measured from. Without it
    there is no boundary, and guessing one produced a list whose first entry
    was the train you were already on."""
    monkeypatch.setattr(itinerary, "_boarding_time", lambda chain, index: None)
    chain = [("A", None, None, 0, "timetable"),
             ("B", "Line 1", None, 3, "timetable")]
    assert itinerary._later_departures(chain, count=3) == []
