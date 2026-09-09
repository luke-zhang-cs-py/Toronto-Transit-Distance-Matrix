"""Trips for a departure time: clock times, real waits, several options.

The interesting assertions are about *when*, not how long. A duration cannot
be wrong about the time of day; an itinerary can, and the ways it goes wrong
are specific: a wait that was never charged, a walk long enough to mean the
search gave up, an alternative that is not an alternative.
"""

import datetime as dt

import pytest

import itinerary
import realtime
import schedule

UNION = (43.6453, -79.3806)
FINCH = (43.7805, -79.4151)
KIPLING = (43.6371, -79.5357)


def at(hour, minute=0):
    return dt.datetime.combine(dt.date.today(), dt.time(hour, minute))


@pytest.fixture
def static():
    return realtime.Conditions.static()


def legs_of(option, kind):
    return [leg for leg in option["legs"] if leg["type"] == kind]


# ------------------------------------------------------------- clock times

def test_a_trip_reports_when_it_starts_and_ends(static):
    plan = itinerary.plan(UNION, FINCH, depart_at=at(17, 20), conditions=static)
    assert plan["departAt"] == "17:20"
    best = plan["options"][0]
    assert best["departAt"] == "17:20"
    assert best["arriveAt"] > "17:20"


def test_every_leg_carries_a_clock_time(static):
    plan = itinerary.plan(UNION, FINCH, depart_at=at(17, 20), conditions=static)
    for leg in plan["options"][0]["legs"]:
        dt.datetime.strptime(leg["startTime"], "%H:%M")
        dt.datetime.strptime(leg["endTime"], "%H:%M")
        assert leg["endTime"] >= leg["startTime"]


def test_the_legs_run_end_to_end_without_a_gap(static):
    """A gap between one leg ending and the next starting is time the
    itinerary has not accounted for."""
    plan = itinerary.plan(KIPLING, FINCH, depart_at=at(8, 15), conditions=static)
    legs = plan["options"][0]["legs"]
    for before, after in zip(legs, legs[1:]):
        assert after["startTime"] == before["endTime"]


def test_the_legs_add_up_to_the_total(static):
    plan = itinerary.plan(UNION, FINCH, depart_at=at(17, 20), conditions=static)
    best = plan["options"][0]
    assert sum(leg["minutes"] for leg in best["legs"]) == pytest.approx(
        best["totalMinutes"], abs=0.2)


def test_leaving_later_arrives_later(static):
    """Transit is FIFO, which is what lets Dijkstra work on a clock. If this
    ever fails, the search is exploring in the wrong order."""
    early = itinerary.plan(UNION, FINCH, depart_at=at(17, 20), conditions=static)
    late = itinerary.plan(UNION, FINCH, depart_at=at(17, 50), conditions=static)
    assert late["options"][0]["arriveAt"] > early["options"][0]["arriveAt"]


# ------------------------------------------------------------------- waits

@pytest.mark.skipif(not schedule.available(),
                    reason="no schedule index; run tools_build_schedule.py")
def test_a_wait_comes_from_the_timetable(static):
    plan = itinerary.plan(UNION, FINCH, depart_at=at(17, 20), conditions=static)
    waits = legs_of(plan["options"][0], "wait")
    assert waits, "boarding a train means waiting for it"
    assert waits[0]["source"] == "timetable"
    dt.datetime.strptime(waits[0]["boardAt"], "%H:%M")


@pytest.mark.skipif(not schedule.available(), reason="no schedule index")
def test_the_boarding_time_is_a_real_departure(static):
    """Not "about two minutes" -- the actual next train.

    compare=False because the fastest option overall may be a park-and-ride
    boarding somewhere else entirely, and this is about the transit trip.
    """
    plan = itinerary.plan(UNION, FINCH, depart_at=at(17, 20), conditions=static,
                          compare=False)
    option = plan["options"][0]
    wait = legs_of(option, "wait")[0]
    ride = legs_of(option, "transit")[0]
    # The node is found from the leg rather than assumed, so the test does not
    # break the moment the best trip starts somewhere else.
    from network import nodes as graph_nodes
    node_id = next(nid for nid, node in graph_nodes.items()
                   if node["name"] == ride["from"]["name"])
    scheduled = schedule.departures_after(node_id, ride["line"], at(17, 20), limit=8)
    assert wait["boardAt"] in [when.strftime("%H:%M") for when in scheduled]


def test_a_wait_is_charged_for_every_boarding(static):
    """routing.py charged one wait, at the origin, and none at a transfer --
    so a trip with two changes undercounted by two waits. Every ride has to
    be preceded by a wait for the thing being ridden."""
    plan = itinerary.plan(KIPLING, FINCH, depart_at=at(8, 15), conditions=static)
    for option in plan["options"]:
        rides = legs_of(option, "transit")
        waits = legs_of(option, "wait")
        assert len(waits) == len(rides), option["lines"]
        for ride, wait in zip(rides, waits):
            assert wait["line"] == ride["line"]


def test_staying_on_a_train_through_a_station_is_free(static):
    """The reason the search state has to include the line: riding through
    an interchange must not be charged as a change."""
    plan = itinerary.plan(UNION, FINCH, depart_at=at(17, 20), conditions=static)
    best = plan["options"][0]
    assert len(legs_of(best, "transit")) == 1, "one line, one ride"
    assert best["transfers"] == 0


def test_a_wait_falls_back_when_the_timetable_cannot_answer(static):
    """YRT, MiWay and GO are not in TTC's GTFS, so their waits are modelled
    and the leg says so rather than implying a timetable."""
    plan = itinerary.plan((43.8, -79.5), (43.6, -79.6), depart_at=at(9, 0),
                          conditions=static)
    sources = {leg["source"] for option in plan["options"]
               for leg in legs_of(option, "wait")}
    assert sources <= {"timetable", "headway", "modelled"}


# -------------------------------------------------------------- transfers

def test_transfers_count_line_changes_not_platform_walks(static):
    """A trip that boarded three lines reported "0 transfers", because two of
    the changes happened at a shared stop with no walk between them. What a
    rider counts is how many times they have to get on something."""
    plan = itinerary.plan(KIPLING, FINCH, depart_at=at(8, 15), conditions=static)
    for option in plan["options"]:
        assert option["transfers"] == max(0, len(legs_of(option, "transit")) - 1)
        assert option["platformWalks"] <= option["transfers"] + 1


# ------------------------------------------------------------- alternatives

def test_several_options_come_back_for_a_trip_with_choices(static):
    plan = itinerary.plan(KIPLING, FINCH, depart_at=at(8, 15), conditions=static,
                          alternatives=3)
    assert len(plan["options"]) >= 2
    assert len({tuple(o["lines"]) for o in plan["options"]}) == len(plan["options"]), \
        "options that use the same lines are not different options"


def test_options_are_ordered_by_how_long_they_take(static):
    plan = itinerary.plan(KIPLING, FINCH, depart_at=at(8, 15), conditions=static,
                          alternatives=3)
    totals = [o["totalMinutes"] for o in plan["options"]]
    assert totals == sorted(totals)


def test_an_absurd_alternative_is_not_offered(static):
    """Banning the useful line leaves a search that "succeeds" by riding
    partway and walking for two and a half hours. That is the search
    admitting it failed, not a second option."""
    plan = itinerary.plan(UNION, FINCH, depart_at=at(17, 20), conditions=static,
                          alternatives=4)
    best = plan["options"][0]["totalMinutes"]
    for option in plan["options"]:
        assert option["totalMinutes"] <= max(
            best * itinerary.ALTERNATIVE_TOLERANCE,
            best + itinerary.ALTERNATIVE_SLACK_MIN)


def test_no_option_ends_in_an_unreasonable_walk(static):
    plan = itinerary.plan(KIPLING, FINCH, depart_at=at(8, 15), conditions=static,
                          alternatives=4)
    for option in plan["options"]:
        for leg in legs_of(option, "walk"):
            assert leg["minutes"] <= itinerary.MAX_EGRESS_WALK_MIN + 1


def test_asking_for_no_alternatives_gives_one_trip(static):
    plan = itinerary.plan(UNION, FINCH, depart_at=at(17, 20), conditions=static,
                          alternatives=0, compare=False)
    assert len(plan["options"]) == 1


# ------------------------------------------------------- comparing the modes

def test_comparing_offers_driving_as_well_as_transit(static):
    """A transit time means nothing on its own. "41 minutes against 35
    driving" is a decision; "41 minutes" is a number."""
    plan = itinerary.plan(UNION, FINCH, depart_at=at(17, 20), conditions=static,
                          compare=True)
    kinds = {option["kind"] for option in plan["options"]}
    assert "walk+transit" in kinds or "drive+transit" in kinds
    assert "drive" in kinds, "no yardstick to compare against"


def test_a_yardstick_is_labelled_as_one(static):
    """Driving the whole way is not a route this app planned -- it is a
    straight line at an assumed speed, and saying so is the difference
    between a comparison and a claim."""
    plan = itinerary.plan(UNION, FINCH, depart_at=at(17, 20), conditions=static,
                          compare=True)
    for option in plan["options"]:
        if option.get("isBaseline"):
            assert option["note"], "a yardstick has to say what it assumes"
            assert option["lines"] == []


def test_park_and_ride_charges_for_parking(static):
    """Finding a spot at a commuter station and walking in is not free, and
    leaving it out is what makes park-and-ride look strictly better."""
    plan = itinerary.plan((43.81, -79.42), UNION, depart_at=at(8, 0),
                          conditions=static, compare=True)
    drives = [leg for option in plan["options"]
              for leg in option["legs"] if leg["type"] == "drive"
              and leg["to"]["name"] != "Destination"]
    assert drives, "no park-and-ride option was offered"
    for leg in drives:
        assert leg["parkMinutes"] == itinerary.PARK_AND_WALK_MIN


def test_driving_the_whole_way_does_not_charge_for_parking(static):
    """It ends at the door."""
    plan = itinerary.plan(UNION, FINCH, depart_at=at(17, 20), conditions=static,
                          compare=True)
    baseline = next(o for o in plan["options"] if o["kind"] == "drive")
    expected = itinerary.drive_minutes(baseline["totalKm"]) - itinerary.PARK_AND_WALK_MIN
    assert baseline["totalMinutes"] == pytest.approx(expected, abs=0.2)


def test_a_three_hour_walk_is_not_offered_as_a_comparison(static):
    """It is noise, not a choice somebody is weighing."""
    plan = itinerary.plan((43.81, -79.42), (43.60, -79.55), depart_at=at(8, 0),
                          conditions=static, compare=True)
    walks = [o for o in plan["options"] if o["kind"] == "walk"]
    for option in walks:
        assert option["totalMinutes"] <= itinerary.MAX_WALK_ONLY_MIN


def test_every_option_says_what_kind_it_is(static):
    plan = itinerary.plan(UNION, FINCH, depart_at=at(17, 20), conditions=static,
                          compare=True)
    for option in plan["options"]:
        assert option["kind"] in ("walk+transit", "drive+transit", "drive", "walk")
        assert option["label"]


def test_driving_is_slower_than_the_speed_limit_on_purpose():
    """26 km/h is roughly what a car averages across a city with lights and
    turns. Quoting 50 would make driving look better than it is."""
    assert itinerary.DRIVE_KMH < 40
    assert itinerary.drive_minutes(10) > 10 / 50 * 60


@pytest.mark.skipif(not schedule.available(), reason="no schedule index")
def test_later_departures_are_offered_for_the_same_routing(static):
    """What somebody actually wants when deciding whether to hurry."""
    plan = itinerary.plan(UNION, FINCH, depart_at=at(17, 20), conditions=static)
    later = plan["options"][0]["laterDepartures"]
    assert later, "the timetable knows when the next ones are"
    assert later == sorted(later)
    boarded = legs_of(plan["options"][0], "wait")[0]["boardAt"]
    assert all(when > boarded for when in later)


# ------------------------------------------------------------- disruptions

def test_a_closed_line_is_not_used(static):
    closed = realtime.Conditions(
        disrupted={"closed": {"line 1"}, "detour": set(), "notes": []}, live=True)
    plan = itinerary.plan(UNION, FINCH, depart_at=at(17, 20), conditions=closed)
    for option in plan["options"]:
        assert "Line 1 (Yonge-University)" not in option["lines"]


def test_a_trip_says_whether_it_was_planned_live(static):
    plan = itinerary.plan(UNION, FINCH, depart_at=at(17, 20), conditions=static)
    assert plan["live"] is False
    assert plan["scheduleAvailable"] == schedule.available()


# -------------------------------------------------------------------- HTTP

def test_the_trips_endpoint_answers(client):
    body = client.post("/api/trips", json={
        "olat": UNION[0], "olon": UNION[1], "dlat": FINCH[0], "dlon": FINCH[1],
        "departAt": "17:20", "live": False}).get_json()
    assert body["departAt"] == "17:20"
    assert body["options"] and body["options"][0]["arriveAt"]


@pytest.mark.parametrize("value", ["17:20", "17:20:00", "now", None])
def test_an_acceptable_departure_time_is_accepted(client, value):
    payload = {"olat": UNION[0], "olon": UNION[1],
               "dlat": FINCH[0], "dlon": FINCH[1], "live": False}
    if value is not None:
        payload["departAt"] = value
    assert client.post("/api/trips", json=payload).status_code == 200


@pytest.mark.parametrize("value", ["half five", "25:99", 1720, [], "2026-13-45T99:99"])
def test_a_bad_departure_time_is_400_not_a_guess(client, value):
    """Silently planning for "now" when somebody asked for 17:20 gives them a
    plausible itinerary for the wrong journey."""
    res = client.post("/api/trips", json={
        "olat": UNION[0], "olon": UNION[1], "dlat": FINCH[0], "dlon": FINCH[1],
        "departAt": value, "live": False})
    assert res.status_code == 400
    assert "departAt" in res.get_json()["error"]


def test_an_iso_timestamp_plans_for_another_day(client):
    body = client.post("/api/trips", json={
        "olat": UNION[0], "olon": UNION[1], "dlat": FINCH[0], "dlon": FINCH[1],
        "departAt": "2026-09-09T06:30", "live": False}).get_json()
    assert body["departDate"] == "2026-09-09"
    assert body["departAt"] == "06:30"


@pytest.mark.parametrize("key,value", [("alternatives", 99), ("later", -1),
                                       ("alternatives", "lots")])
def test_out_of_range_counts_are_refused(client, key, value):
    res = client.post("/api/trips", json={
        "olat": UNION[0], "olon": UNION[1], "dlat": FINCH[0], "dlon": FINCH[1],
        key: value, "live": False})
    assert res.status_code == 400


def test_the_live_endpoint_reports_schedule_coverage(client):
    body = client.get("/api/live").get_json()
    assert "schedule" in body
    assert body["schedule"]["available"] == schedule.available()
