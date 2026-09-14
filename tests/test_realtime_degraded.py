"""The live feed when it is slow, absent, corrupt, or missing its library.

realtime.py is the one module in this project that depends on something
outside it: two TTC protobuf feeds, 730 KB of trip updates, fetched over a
network that is allowed to be down. Every decision in it is about what to do
when that goes wrong, and almost none of those decisions had been executed --
the suite has always tested the static model.

The feed is faked rather than fetched. A real fetch would make the suite
depend on the TTC being up and on a 730 KB download, and the protobuf
objects are only read through `HasField` and attribute access, so a small
stand-in exercises the same branches. gtfs-realtime-bindings may not even be
installed, which is itself one of the paths tested here.

Nothing here leaves module state behind: the caches are module-level dicts
and the refresher is a real thread, so both are reset around every test.
"""

import subprocess
import threading
import time
import urllib.error
import urllib.request

import pytest

import realtime


# --------------------------------------------------------- a stand-in feed


class FakeField:
    """Something with HasField, which is all the reader asks of a message."""

    def __init__(self, **fields):
        self._present = set(fields)
        for name, value in fields.items():
            setattr(self, name, value)

    def HasField(self, name):
        return name in self._present


def arrival(at):
    return FakeField(time=at)


def stop_time(stop_id, at=None):
    if at is None:
        return FakeField(stop_id=stop_id)          # no arrival field at all
    return FakeField(stop_id=stop_id, arrival=arrival(at))


def trip_update(route_id, stops):
    """stops: {stop_id: [epoch, ...]}"""
    updates = []
    for stop_id, times in stops.items():
        for at in times:
            updates.append(stop_time(stop_id, at))
    trip = FakeField(route_id=route_id)
    return FakeField(trip=trip, stop_time_update=updates)


def a_trip_entity(route_id="504", stops=None):
    # MIN_GAPS_FOR_HEADWAY is 8, so a headway needs nine gaps to have a
    # median worth reporting. Ten arrivals, ten minutes apart.
    stops = stops or {"s1": [600 * n for n in range(10)]}
    return FakeField(trip_update=trip_update(route_id, stops))


class FakeFeed:
    def __init__(self, entities):
        self.entity = entities


@pytest.fixture(autouse=True)
def clean_module_state():
    """The caches and the refresher are module-level, so a test that leaves
    either set changes the next one. Both are put back."""
    realtime.reset() if hasattr(realtime, "reset") else None
    realtime._cache.clear()
    realtime._last_good.clear()
    yield
    realtime.stop_refresh()
    if realtime._refresher is not None:
        realtime._refresher.join(timeout=5)
    realtime._refresher = None
    realtime._stop.clear()
    realtime._cache.clear()
    realtime._last_good.clear()


# ------------------------------------------------------------- fetching


def test_the_feed_is_fetched_over_urllib_when_it_can_be(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"feed-bytes"

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=None: Response())
    assert realtime._fetch("http://example.invalid/feed") == b"feed-bytes"


def test_the_feed_falls_back_to_curl(monkeypatch):
    """Same reason as the archive download: urllib cannot verify the chain
    behind an inspecting proxy, and curl can."""
    def refuse(url, timeout=None):
        raise urllib.error.URLError("certificate verify failed")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(
        subprocess, "run",
        lambda args, capture_output=None, timeout=None:
        subprocess.CompletedProcess(args, 0, stdout=b"curl-bytes"))

    assert realtime._fetch("http://example.invalid/feed") == b"curl-bytes"


def test_curl_returning_nothing_is_none_not_empty_bytes(monkeypatch):
    """An empty body must not be handed on as if it were a feed; the parser
    would report a corrupt message for what is really a failed fetch."""
    def refuse(url, timeout=None):
        raise urllib.error.URLError("no")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(
        subprocess, "run",
        lambda args, capture_output=None, timeout=None:
        subprocess.CompletedProcess(args, 0, stdout=b""))

    assert realtime._fetch("http://example.invalid/feed") is None


def test_both_ways_failing_gives_up_quietly(monkeypatch):
    def refuse(url, timeout=None):
        raise urllib.error.URLError("no")

    def no_curl(args, capture_output=None, timeout=None):
        raise OSError("curl is not installed")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(subprocess, "run", no_curl)
    assert realtime._fetch("http://example.invalid/feed") is None


# --------------------------------------------------------------- caching


def test_a_fresh_cache_entry_is_not_fetched_again(monkeypatch):
    """The whole point of the TTL. Re-fetching per request was 5.2 seconds
    on the first one and a repeated 730 KB after that."""
    calls = []

    def counting_fetch(url, timeout=None):
        calls.append(url)
        return None

    monkeypatch.setattr(realtime, "_fetch", counting_fetch)

    realtime._cache["trips"] = {"at": time.monotonic(), "parsed": "cached"}
    assert realtime._feed("trips") == "cached"
    assert calls == [], "a fresh entry should not reach the network"


def test_a_failed_fetch_keeps_the_last_good_reading(monkeypatch):
    """A feed that goes down should degrade, not fall off a cliff: the last
    parse that worked is still the best available answer."""
    monkeypatch.setattr(realtime, "_fetch", lambda url, timeout=None: None)
    realtime._last_good["trips"] = "yesterday's feed"

    assert realtime._feed("trips") == "yesterday's feed"


def fake_bindings(monkeypatch, message_class):
    """Put a stand-in google.transit.gtfs_realtime_pb2 in sys.modules.

    _feed imports it inside the function, so replacing the module entry is
    enough -- and the real bindings may not be installed at all, which is
    one of the cases below.
    """
    import sys
    import types

    module = types.ModuleType("google.transit.gtfs_realtime_pb2")
    module.FeedMessage = message_class
    transit = types.ModuleType("google.transit")
    transit.gtfs_realtime_pb2 = module
    google = types.ModuleType("google")
    google.transit = transit

    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.transit", transit)
    monkeypatch.setitem(sys.modules,
                        "google.transit.gtfs_realtime_pb2", module)


def test_a_successful_parse_becomes_the_last_good_reading(monkeypatch):
    """The parse that worked is remembered, so the next failed fetch has
    something to fall back on rather than nothing."""
    entities = [a_trip_entity()]

    class Message:
        def __init__(self):
            self.entity = entities

        def ParseFromString(self, raw):
            pass

    monkeypatch.setattr(realtime, "_fetch", lambda url, timeout=None: b"raw")
    fake_bindings(monkeypatch, Message)

    got = realtime._feed("trips")
    assert got is not None, "a good body should have parsed"
    assert realtime._last_good.get("trips") is got


def test_a_missing_protobuf_library_stays_on_the_static_model(monkeypatch):
    """The bindings are an optional install. Without them the app must keep
    serving the fixed schedule rather than failing to start."""
    import builtins

    monkeypatch.setattr(realtime, "_fetch", lambda url, timeout=None: b"raw")
    real_import = builtins.__import__

    def no_bindings(name, *args, **kwargs):
        if "gtfs_realtime_pb2" in name or name == "google.transit":
            raise ImportError("no gtfs-realtime-bindings")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_bindings)
    assert realtime._feed("trips") is None


def test_a_corrupt_body_is_not_a_crash(monkeypatch):
    """A partial download parses as a corrupt message. That is a feed
    problem, not a reason to stop answering."""
    monkeypatch.setattr(realtime, "_fetch", lambda url, timeout=None: b"junk")

    class Message:
        def ParseFromString(self, raw):
            raise ValueError("truncated message")

    fake_bindings(monkeypatch, Message)
    assert realtime._feed("trips") is None


# ------------------------------------------------------- reading the feed


def test_no_feed_means_no_headways_rather_than_zero():
    """Zero headways would read as "every line runs constantly"."""
    assert realtime.observed_headways(feed=None) == {}


def test_no_feed_means_no_disruptions_claimed():
    out = realtime.disruptions(feed=None)
    assert out == {"closed": set(), "detour": set(), "notes": []}


def test_entities_that_are_not_trip_updates_are_skipped():
    """One feed carries several entity types; a vehicle position has no
    trip_update to read."""
    feed = FakeFeed([FakeField(vehicle=FakeField(id="v1")), a_trip_entity()])
    assert realtime.observed_headways(feed=feed), "the real entity was lost"


def test_a_trip_update_with_no_route_is_skipped():
    """Pooling gaps under an empty route id would put every unidentified
    trip in one bucket and call the median a headway."""
    feed = FakeFeed([a_trip_entity(route_id=""),
                     a_trip_entity(route_id="504")])
    got = realtime.observed_headways(feed=feed)
    assert "" not in got
    assert "504" in got


def test_entities_that_are_not_alerts_are_skipped():
    feed = FakeFeed([a_trip_entity()])
    assert realtime.disruptions(feed=feed) == {
        "closed": set(), "detour": set(), "notes": []}


def test_an_alert_about_nothing_identifiable_is_skipped():
    """If no route or line can be named, there is nothing to price: applying
    it to everything would close the network on one vague sentence."""
    alert = FakeField(
        header_text=FakeField(translation=[FakeField(text="Elevator update")]),
        description_text=FakeField(translation=[]),
        informed_entity=[])
    feed = FakeFeed([FakeField(alert=alert)])

    out = realtime.disruptions(feed=feed)
    assert out["closed"] == set() and out["detour"] == set()


# --------------------------------------------------------- the reading API


def test_a_reading_says_whether_each_wait_was_measured():
    """The report distinguishes a measured headway from a modelled one, and
    that distinction is the reason the live feed is worth fetching."""
    reading = realtime.Conditions(headways={"504": 4.0}, disrupted=None,
                                  live=True)
    assert reading.wait_source("504 King", "streetcar") == "measured"
    assert reading.wait_source("999 Nowhere", "bus") == "modelled"


# ------------------------------------------------------------ the refresher


def test_the_refresher_starts_once_and_stops(monkeypatch):
    """A background loop rather than making one unlucky request pay for the
    fetch. Starting twice would double the traffic for nothing."""
    ticks = []
    monkeypatch.setattr(realtime, "refresh",
                        lambda: ticks.append(1) or True)

    first = realtime.start_refresh(interval=0.01)
    assert isinstance(first, threading.Thread)
    again = realtime.start_refresh(interval=0.01)
    assert again is first, "a second thread was started over a live one"

    deadline = time.monotonic() + 5
    while not ticks and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ticks, "the loop never refreshed"

    realtime.stop_refresh()
    first.join(timeout=5)
    assert not first.is_alive(), "it did not stop when asked"


def test_a_refresh_that_raises_does_not_kill_the_loop(monkeypatch):
    """A dead refresher is a silent failure: nothing errors, and the data
    just quietly stops being current."""
    calls = []

    def sometimes():
        calls.append(1)
        raise RuntimeError("the feed went away")

    monkeypatch.setattr(realtime, "refresh", sometimes)

    thread = realtime.start_refresh(interval=0.01)
    deadline = time.monotonic() + 5
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)

    assert len(calls) >= 2, "the loop stopped at the first exception"
    assert thread.is_alive()


def test_an_alert_that_reads_as_a_closure_but_names_nothing_is_skipped():
    """Classified as a real disruption, but with no route or line anywhere
    in it. Applying it to everything would shut the network on one vague
    sentence; applying it to nothing is the only safe reading."""
    alert = FakeField(
        header_text=FakeField(
            translation=[FakeField(text="No service until further notice")]),
        description_text=FakeField(translation=[]),
        informed_entity=[])

    assert realtime.classify("No service until further notice") == \
        realtime.CLOSED, "this case only matters if it is not cosmetic"

    out = realtime.disruptions(feed=FakeFeed([FakeField(alert=alert)]))
    assert out["closed"] == set()
    assert out["detour"] == set()
