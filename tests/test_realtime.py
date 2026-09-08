"""Live TTC data, folded into the routing model.

Every test here runs against two recorded feeds in tests/fixtures, captured
from bustime.ttc.ca. Recorded rather than fetched: a test that needs the
network fails when the network is having a bad day, and a test that asserts
against live data cannot assert anything specific, because the thing it is
asserting about changes. The recording happens to contain a real Line 2
closure, which is the case worth pinning.
"""

import os

import pytest

import realtime
import routing
from network import WAIT_BY_MODE

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
UNION = (43.6453, -79.3806)
FINCH = (43.7805, -79.4151)


def load(name):
    from google.transit import gtfs_realtime_pb2
    message = gtfs_realtime_pb2.FeedMessage()
    with open(os.path.join(FIXTURES, name), "rb") as handle:
        message.ParseFromString(handle.read())
    return message


@pytest.fixture(scope="module")
def trips():
    return load("gtfsrt_trips.pb")


@pytest.fixture(scope="module")
def alerts():
    return load("gtfsrt_alerts.pb")


@pytest.fixture(scope="module")
def recorded(trips, alerts):
    """The conditions that recording describes."""
    return realtime.Conditions(headways=realtime.observed_headways(trips),
                               disrupted=realtime.disruptions(alerts),
                               live=True)


# ------------------------------------------------------------------- waits

def test_headways_come_out_of_the_trip_feed(trips):
    """The feed carries no `delay` field -- TTC leaves it unset -- so the
    wait has to be derived from the gaps between arrival times."""
    headways = realtime.observed_headways(trips)
    assert len(headways) > 100, "the feed covers most of the surface network"
    assert all(0 < v < 60 for v in headways.values()), "minutes, not seconds"


@pytest.mark.parametrize("route", ["501", "504", "505", "506", "510", "511"])
def test_every_streetcar_route_is_measured(recorded, route):
    """These are the six lines in the graph that TTC's feed can speak to."""
    assert route in recorded.headways


def test_a_measured_wait_replaces_the_modelled_one(recorded):
    """Half the observed headway, because somebody arriving at a random
    moment waits on average half the gap between vehicles."""
    wait, measured = recorded.wait_for("504 King", "tram")
    assert measured is True
    assert wait == pytest.approx(recorded.headways["504"] / 2, abs=0.01)
    assert wait != WAIT_BY_MODE["tram"], "otherwise nothing was gained"


def test_a_wait_is_bounded_either_way():
    """One vehicle seen twenty minutes apart is not a headway, and three in
    a minute is not a thirty-second one."""
    slow = realtime.Conditions(headways={"504": 300.0}, live=True)
    fast = realtime.Conditions(headways={"504": 0.2}, live=True)
    assert slow.wait_for("504 King", "tram")[0] == realtime.MAX_OBSERVED_WAIT_MIN
    assert fast.wait_for("504 King", "tram")[0] == realtime.MIN_OBSERVED_WAIT_MIN


def test_the_subway_stays_modelled(recorded):
    """TTC's realtime feed is surface routes only -- no subway route id
    appears in it. Line 1 and Line 2 keep their modelled wait however live
    the rest of the answer is, and the snapshot says so rather than leaving
    it to be inferred."""
    wait, measured = recorded.wait_for("Line 1 (Yonge-University)", "subway")
    assert measured is False
    assert wait == WAIT_BY_MODE["subway"]
    assert not {"1", "2", "3", "4"} & set(recorded.headways)


def test_the_regional_agencies_stay_modelled(recorded):
    """YRT, MiWay and GO are not in TTC's feed. Metrolinx's API would cover
    GO and needs a key this project does not use."""
    for line, mode in (("YRT Viva Purple (Hwy 7)", "yrt"),
                       ("MiWay Hurontario corridor", "miway")):
        wait, measured = recorded.wait_for(line, mode)
        assert measured is False
        assert wait == WAIT_BY_MODE[mode]


def test_a_line_name_yields_its_route_id():
    """The names in network/ start with the route number, which is the same
    id the feed uses -- so this is a parse, not a table that could fall out
    of step with the graph."""
    assert realtime.route_id_of("504 King") == "504"
    assert realtime.route_id_of("506 Carlton/College") == "506"
    assert realtime.route_id_of("Line 1 (Yonge-University)") is None
    assert realtime.route_id_of("Transfer") is None
    assert realtime.route_id_of(None) is None


# ------------------------------------------------------------- disruptions

@pytest.mark.parametrize("text,expected", [
    ("Line 2 Bloor-Danforth: No service", realtime.CLOSED),
    ("37 Islington: Buses are not stopping", realtime.CLOSED),
    ("68 Warden: Detour via Sixteenth", realtime.DETOUR),
    ("97 Yonge: Detour via Pleasant Blvd", realtime.DETOUR),
    ("St Andrew: Elevator out of service", realtime.COSMETIC),
    ("Have proof of payment ready", realtime.COSMETIC),
    ("Please look both ways", realtime.COSMETIC),
    ("", realtime.COSMETIC),
])
def test_an_alert_is_classified_from_its_text(text, expected):
    """TTC sets `effect` to UNKNOWN_EFFECT on every entity, so the meaning
    has to be read out of the header -- which TTC also truncates to about 32
    characters."""
    assert realtime.classify(text) == expected


def test_a_broken_lift_is_not_a_closure():
    """It is a real problem for a real person and changes nothing about how
    long a train takes. Treating it as a closure would route people the long
    way round for no reason."""
    assert realtime.classify("Kennedy: Elevator out of service") == realtime.COSMETIC


def test_a_subway_closure_closes_only_the_subway(recorded):
    """The bug this pins.

    TTC informs a subway closure via every route touching the affected area
    -- the recorded Line 2 alert lists thirty-five, including streetcars
    504, 505 and 512, which are the connections rather than the closure.
    Believing informed_entity would have closed a third of the network
    because one line was down, and sent people on detours around routes that
    were running normally.
    """
    assert recorded.disrupted["closed"] == {"line 2"}
    assert recorded.impact_on("Line 2 (Bloor-Danforth)") is None
    for connecting in ("504 King", "505 Dundas", "510 Spadina",
                       "Line 1 (Yonge-University)"):
        assert recorded.impact_on(connecting) == 0.0, connecting


def test_a_detour_costs_time_rather_than_closing(recorded):
    assert recorded.impact_on("97 Yonge") == realtime.DETOUR_PENALTY_MIN


def test_an_undisrupted_line_costs_nothing(recorded):
    assert recorded.impact_on("506 Carlton/College") == 0.0


def test_an_alert_naming_nothing_is_priced_as_a_detour():
    """Falling back to informed_entity means the subject was guessed, and a
    guess is not evidence that thirty-five routes stopped running."""
    from google.transit import gtfs_realtime_pb2 as pb
    feed = pb.FeedMessage()
    entity = feed.entity.add()
    entity.id = "x"
    entity.alert.header_text.translation.add().text = "Service suspended somewhere"
    for route in ("11", "22"):
        entity.alert.informed_entity.add().route_id = route

    found = realtime.disruptions(feed)
    assert found["closed"] == set(), "not closed on a guess"
    assert found["detour"] == {"11", "22"}
    assert found["notes"][0]["subjectFromText"] is False


# ---------------------------------------------------------------- routing

def test_a_closed_line_is_routed_around(recorded):
    """Kipling to Yonge & Bloor is a Line 2 trip. With Line 2 closed it has
    to be something else, or nothing."""
    kipling, yonge_bloor = (43.6371, -79.5357), (43.6709, -79.3857)
    route = routing.build_route(*kipling, *yonge_bloor, conditions=recorded)
    used = {s.get("line") for s in route["segments"] if s.get("line")}
    assert "Line 2 (Bloor-Danforth)" not in used


def test_the_static_model_still_uses_that_line():
    """The other half: the closure is the reason, not a coincidence."""
    kipling, yonge_bloor = (43.6371, -79.5357), (43.6709, -79.3857)
    route = routing.build_route(*kipling, *yonge_bloor,
                                conditions=realtime.Conditions.static())
    used = {s.get("line") for s in route["segments"] if s.get("line")}
    assert "Line 2 (Bloor-Danforth)" in used


def test_a_live_route_still_totals_its_own_segments(recorded):
    """The invariant has to hold whatever the weights are."""
    route = routing.build_route(*UNION, *FINCH, conditions=recorded)
    assert route["total"] == pytest.approx(sum(s["minutes"] for s in route["segments"]))


def test_a_boarding_wait_uses_the_soonest_line(recorded):
    """You board whatever arrives first, so the wait at an interchange is the
    smallest of its lines' waits, not the average."""
    wait, measured = recorded.boarding_wait({"504 King", "501 Queen"}, "tram")
    both = [recorded.wait_for(line, "tram")[0] for line in ("504 King", "501 Queen")]
    assert measured is True
    assert wait == pytest.approx(min(both))


def test_a_closed_line_cannot_be_boarded(recorded):
    """A stop served only by a closed line has no live wait to offer, so it
    falls back rather than reporting the wait for a train that is not
    running."""
    wait, measured = recorded.boarding_wait({"Line 2 (Bloor-Danforth)"}, "subway")
    assert measured is False
    assert wait == WAIT_BY_MODE["subway"]


# --------------------------------------------------------------- degrading

def test_everything_falls_back_when_the_feed_is_down(monkeypatch):
    """A router that stops working when the network hiccups is worse than one
    that was never live: it fails at the moment somebody is standing on a
    platform."""
    realtime.reset_cache()
    monkeypatch.setattr(realtime, "_fetch", lambda *a, **k: None)

    assert realtime.refresh() is False
    conditions = realtime.Conditions.live_now()
    assert conditions.live is False

    route = routing.build_route(*UNION, *FINCH, conditions=conditions)
    assert route["total"] > 0 and route["segments"]
    wait, measured = conditions.wait_for("504 King", "tram")
    assert measured is False and wait == WAIT_BY_MODE["tram"]
    realtime.reset_cache()


def test_a_corrupt_feed_body_does_not_raise(monkeypatch):
    realtime.reset_cache()
    monkeypatch.setattr(realtime, "_fetch", lambda *a, **k: b"not a protobuf at all")
    assert realtime.refresh() is False
    assert realtime.Conditions.live_now().live is False
    realtime.reset_cache()


def test_the_request_path_never_fetches(monkeypatch):
    """live_now() reads the derived cache. Fetching 730 KB took 5.2 seconds
    and re-deriving an unchanged answer took 98 ms -- neither belongs on a
    request."""
    realtime.reset_cache()

    def explode(*args, **kwargs):
        raise AssertionError("live_now() must not fetch")

    monkeypatch.setattr(realtime, "_fetch", explode)
    conditions = realtime.Conditions.live_now()
    assert conditions.live is False
    realtime.reset_cache()


def test_a_refresh_is_atomic(trips, alerts, monkeypatch):
    """Headways from one minute and closures from another would price a route
    against a network that never existed."""
    realtime.reset_cache()
    monkeypatch.setattr(realtime, "_feed",
                        lambda kind: trips if kind == "trips" else alerts)
    assert realtime.refresh() is True
    conditions = realtime.Conditions.live_now()
    assert conditions.live and conditions.headways
    assert conditions.disrupted["closed"] == {"line 2"}
    realtime.reset_cache()


# ------------------------------------------------------------------- HTTP

def test_the_snapshot_says_what_is_not_live(trips, alerts, monkeypatch):
    realtime.reset_cache()
    monkeypatch.setattr(realtime, "_feed",
                        lambda kind: trips if kind == "trips" else alerts)
    realtime.refresh()
    snap = realtime.snapshot()
    assert snap["live"] is True
    assert snap["routesWithObservedHeadway"] > 100
    assert snap["closed"] == ["line 2"]
    assert any("subway" in m for m in snap["modelledOnly"])
    assert "no key required" in snap["source"]
    realtime.reset_cache()


def test_the_live_endpoint_answers(client):
    body = client.get("/api/live").get_json()
    assert "live" in body and "modelledOnly" in body


def test_a_route_says_which_data_it_used(client):
    body = client.post("/api/route", json={
        "olat": UNION[0], "olon": UNION[1], "dlat": FINCH[0], "dlon": FINCH[1],
        "live": False}).get_json()
    assert body["live"] is False
    assert body["total"] > 0


def test_reach_reports_liveness_alongside_its_times(client):
    body = client.post("/api/reach", json={"lat": UNION[0], "lon": UNION[1],
                                           "live": False}).get_json()
    assert body["live"] is False
    assert len(body["times"]) > 100
