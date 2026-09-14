"""What the app does when the data it wants is not there.

This map is assembled from four sources that can each be missing or broken
independently: a 207 MB GTFS archive, a generated bus index, a live protobuf
feed, and a schedule index built from the first of those. None of them is
guaranteed to exist at import, and the design choice throughout is to carry
on with less rather than fail -- a route over the subway is still useful
when the bus file has not been generated.

That choice is only correct if the fallbacks work, and none of them had ever
been executed. These remove each source in turn and assert the app degrades
in the shape it claims to: fewer stops, a modelled wait instead of a
measured one, no answer rather than a wrong one.

Both networks are faked rather than downloaded. The real feeds are 730 KB of
protobuf and a fifth of a gigabyte of zip, and a test that needs either is a
test nobody runs.
"""

import io
import json
import subprocess
import urllib.error
import urllib.request

import pytest


# --------------------------------------------------------------- downloads


class FakeResponse:
    def __init__(self, payload=b"archive-bytes"):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.payload


def refusing_urlopen(*_a, **_kw):
    raise urllib.error.URLError("certificate verify failed")


def test_the_archive_downloads_over_urllib_when_it_can(tmp_path, monkeypatch):
    import gtfs

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=None: FakeResponse(b"zip-data"))
    dest = tmp_path / "gtfs.zip"
    assert gtfs.fetch(dest=str(dest)) is True
    assert dest.read_bytes() == b"zip-data"


def test_the_archive_falls_back_to_curl(tmp_path, monkeypatch):
    """urllib cannot verify the chain behind an inspecting proxy; curl
    verifies differently and gets through. That is why there are two, and
    the second had never run."""
    import gtfs

    monkeypatch.setattr(urllib.request, "urlopen", refusing_urlopen)
    dest = tmp_path / "gtfs.zip"

    def fake_curl(args, timeout=None):
        # curl writes the file itself, so the fake must too: the return
        # value is checked against the file's size.
        with io.open(args[args.index("-o") + 1], "wb") as handle:
            handle.write(b"curl-data")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_curl)
    assert gtfs.fetch(dest=str(dest)) is True
    assert dest.read_bytes() == b"curl-data"


def test_a_download_that_writes_nothing_is_not_a_success(tmp_path,
                                                         monkeypatch):
    """curl can exit 0 having written an empty file. Calling that a
    downloaded archive turns a network problem into a parse error later,
    somewhere much less obvious."""
    import gtfs

    monkeypatch.setattr(urllib.request, "urlopen", refusing_urlopen)
    dest = tmp_path / "gtfs.zip"
    dest.write_bytes(b"")

    monkeypatch.setattr(
        subprocess, "run",
        lambda args, timeout=None: subprocess.CompletedProcess(args, 0))
    assert gtfs.fetch(dest=str(dest)) is False


def test_both_ways_failing_is_reported_rather_than_raised(tmp_path,
                                                          monkeypatch):
    import gtfs

    def no_curl(args, timeout=None):
        raise OSError("curl is not installed")

    monkeypatch.setattr(urllib.request, "urlopen", refusing_urlopen)
    monkeypatch.setattr(subprocess, "run", no_curl)
    assert gtfs.fetch(dest=str(tmp_path / "x.zip")) is False


# ------------------------------------------------------------ the bus index


def test_no_bus_file_adds_no_stops():
    """The generated index is optional; the subway map stands on its own."""
    from network import buses

    assert buses.load(path="does-not-exist.json") == 0


def test_an_unreadable_bus_file_is_skipped(tmp_path):
    """Half a JSON file is a broken build, not a reason to have no map."""
    from network import buses

    broken = tmp_path / "bus_routes.json"
    broken.write_text('{"routes": [', encoding="utf-8")
    assert buses.load(path=str(broken)) == 0


def test_a_route_with_one_stop_is_not_a_route(tmp_path):
    """One stop has no edges, so it would add a node nothing can reach."""
    from network import buses

    one = tmp_path / "bus_routes.json"
    one.write_text(json.dumps({"routes": [
        {"name": "501 Queen",
         "stops": [{"id": "b1", "name": "Only stop",
                    "lat": 43.6, "lon": -79.4}],
         "hops": []},
    ]}), encoding="utf-8")
    assert buses.load(path=str(one)) == 0


# --------------------------------------------------------------- the graph


def test_an_edge_to_a_stop_that_is_not_on_the_map_is_dropped(caplog):
    """It used to be dropped in silence, so a mistyped id produced a map
    quietly missing a link -- and the only symptom is a route taking the long
    way round, which reads as a modelling choice rather than a typo."""
    from network import graph

    real = next(iter(graph.nodes))
    before = len(graph.adj.get(real, []))

    with caplog.at_level("WARNING"):
        graph.add_edge(real, "NOT-A-STATION", 3, "Line 1")

    assert len(graph.adj.get(real, [])) == before, "an edge was added anyway"
    assert any("NOT-A-STATION" in record.getMessage()
               for record in caplog.records), "the drop should not be silent"


# -------------------------------------------------------------- the routing


def test_the_search_keeps_the_cheapest_time_for_each_stop():
    """Dijkstra pushes a node again when it finds a cheaper way in rather
    than reaching into the heap to update it. The superseded entry stays in
    there and has to be recognised as out of date when it surfaces -- acting
    on it would overwrite a good time with a worse one."""
    import routing
    from network import graph

    node = graph.nodes[next(iter(graph.nodes))]
    times = routing.compute_times(node["lat"], node["lon"])

    assert times, "the search returned nothing at all"
    assert min(times.values()) >= 0
    # The origin's own stop is the cheapest thing in the result.
    assert times[next(iter(graph.nodes))] == min(times.values())


def test_a_zero_wait_is_not_charged_to_a_leg():
    """The boarding wait is charged by the search and then moved onto the
    first leg that is not a walk. Nothing to move is the ordinary case for a
    trip starting on a platform, and it must leave the legs alone rather
    than labelling one with a zero."""
    import routing

    segments = [{"type": "walk", "minutes": 4.0},
                {"type": "ride", "minutes": 10.0, "line": "Line 1"}]

    routing._charge_boarding_wait(segments, 0)
    assert segments[1]["minutes"] == 10.0
    assert "waitMinutes" not in segments[1]

    # With a real wait it lands on the ride, not the walk.
    routing._charge_boarding_wait(segments, 3)
    assert segments[0]["minutes"] == 4.0
    assert segments[1]["minutes"] == 13.0


# ------------------------------------------------------------- the schedule


@pytest.fixture
def no_schedule(monkeypatch):
    """Every schedule reader starts by asking load() for the index. With no
    index built, each has to answer "I do not know" in its own shape rather
    than raising or inventing a time."""
    import schedule
    monkeypatch.setattr(schedule, "load", lambda path=None: None)
    return schedule


def test_without_an_index_nothing_is_claimed(no_schedule):
    import datetime as dt

    schedule = no_schedule
    assert schedule.covered_dates() == []
    assert schedule.has_schedule("BLOOR-YONGE", "Line 1") is False
    assert schedule.match_metres("BLOOR-YONGE", "Line 1") is None
    assert schedule.service_span("BLOOR-YONGE", "Line 1",
                                 dt.date(2026, 9, 14)) is None


def test_a_line_with_no_times_on_a_date_has_no_span(monkeypatch):
    """The index exists and knows the stop, but that service does not run on
    the date asked about -- a Sunday-only branch asked about a Tuesday. No
    span is the honest answer; the first and last of an empty list is not."""
    import datetime as dt

    import schedule

    monkeypatch.setattr(schedule, "load", lambda path=None: {
        "departures": {"STOP": {"Line 9": {"SUNDAY": [3600]}}},
        "services": {},
    })
    monkeypatch.setattr(schedule, "services_on", lambda date: ["WEEKDAY"])
    assert schedule.service_span("STOP", "Line 9",
                                 dt.date(2026, 9, 15)) is None
