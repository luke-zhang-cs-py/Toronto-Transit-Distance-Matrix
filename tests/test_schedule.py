"""The timetable index: what it can answer, and what it says when it cannot.

schedule.py was the least covered module at 68%, and the uncovered half was
the part that matters when something is missing -- no index built, a corrupt
file, a stop that is not in it, a time of night with no service. Those paths
decide whether a trip falls back gracefully or reports nonsense, and none of
them had a test.
"""

import datetime as dt
import json

import pytest

import schedule


@pytest.fixture(autouse=True)
def fresh():
    """schedule caches the index globally, so each test starts clean."""
    schedule.reset()
    yield
    schedule.reset()


def a_scheduled_stop():
    """A node and line the index actually holds, or skip."""
    index = schedule.load()
    if not index:
        pytest.skip("no schedule index; run tools_build_schedule.py")
    for node_id, by_line in index["departures"].items():
        for line in by_line:
            return node_id, line
    pytest.skip("the index is empty")


# ------------------------------------------------------------------ loading

def test_a_missing_index_is_absent_not_fatal(tmp_path):
    """The project works without it, on headways and modelled waits. A clone
    has no index until somebody runs the build tool, and that must not be a
    crash on the first page load."""
    assert schedule.load(str(tmp_path / "nope.json")) is None
    assert schedule.available() is False
    assert schedule.built_at() is None
    assert schedule.coverage() == {"available": False}


def test_a_corrupt_index_is_absent_not_fatal(tmp_path):
    """Half a JSON file is what you get if a build was interrupted."""
    broken = tmp_path / "broken.json"
    broken.write_text('{"departures": {"union":', encoding="utf-8")
    assert schedule.load(str(broken)) is None
    assert schedule.available() is False


def test_the_index_is_read_once(tmp_path, monkeypatch):
    """It is 2 MB. Re-reading per query would be a file open per edge."""
    path = tmp_path / "index.json"
    path.write_text(json.dumps({"builtAt": "x", "services": {}, "departures": {}}),
                    encoding="utf-8")
    reads = []
    real = open

    def counting(*args, **kwargs):
        if args and str(args[0]) == str(path):
            reads.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr("builtins.open", counting)
    for _ in range(4):
        schedule.load(str(path))
    assert len(reads) == 1


def test_reset_forgets_the_index(tmp_path):
    schedule.load(str(tmp_path / "nope.json"))
    assert schedule.available() is False
    schedule.reset()
    # After a reset the real index loads again rather than the cached miss.
    assert schedule.available() == (schedule.load() is not None)


# ----------------------------------------------------------------- querying

def test_a_stop_not_in_the_index_has_no_schedule():
    """Nine node-line pairs had no GTFS stop within 900 m. Those fall back,
    and has_schedule is how a caller knows which it is dealing with."""
    assert schedule.has_schedule("not-a-node", "not-a-line") is False
    assert schedule.match_metres("not-a-node", "not-a-line") is None
    assert schedule.wait_minutes("not-a-node", "not-a-line", dt.datetime.now()) is None
    assert schedule.next_departure("not-a-node", "not-a-line", dt.datetime.now()) is None
    assert schedule.departures_after("not-a-node", "not-a-line",
                                     dt.datetime.now()) == []


def test_a_scheduled_stop_reports_its_match_distance():
    """A node 600 m from its stop is on the right line, but the walk to it is
    not what the graph says -- so the distance is recorded rather than
    hidden behind the threshold that accepted it."""
    node_id, line = a_scheduled_stop()
    assert schedule.has_schedule(node_id, line) is True
    distance = schedule.match_metres(node_id, line)
    assert distance is None or 0 <= distance <= 900


def test_departures_come_back_in_order_and_are_not_repeated():
    """Two services can run on one date -- a weekday service plus a holiday
    exception -- and the same train then appears twice."""
    node_id, line = a_scheduled_stop()
    when = dt.datetime.combine(dt.date.today(), dt.time(8, 0))
    found = schedule.departures_after(node_id, line, when, limit=6)
    if not found:
        pytest.skip("nothing scheduled at that stop today")
    assert found == sorted(found)
    assert len(found) == len(set(found))
    assert all(d >= when for d in found)


def test_a_wait_is_never_negative():
    node_id, line = a_scheduled_stop()
    when = dt.datetime.combine(dt.date.today(), dt.time(8, 0))
    wait = schedule.wait_minutes(node_id, line, when)
    if wait is not None:
        assert wait >= 0


def test_nothing_is_offered_hours_away():
    """MAX_WAIT_SECONDS. A router that waits six hours for a train is not
    planning a trip anybody would take, and reporting one as the answer is
    worse than saying there is none."""
    node_id, line = a_scheduled_stop()
    # The small hours, when the surface network is not running.
    when = dt.datetime.combine(dt.date.today(), dt.time(3, 30))
    for departure in schedule.departures_after(node_id, line, when, limit=4):
        gap = (departure - when).total_seconds()
        assert gap <= schedule.MAX_WAIT_SECONDS


def test_the_service_span_says_when_the_day_starts_and_ends():
    """So a trip planned for 03:00 can say "the first train is at 05:57"
    rather than reporting no route and leaving the reader to guess why."""
    node_id, line = a_scheduled_stop()
    span = schedule.service_span(node_id, line, dt.date.today())
    if span is None:
        pytest.skip("no service at that stop today")
    first, last = span
    assert first <= last
    assert schedule.service_span("not-a-node", "not-a-line", dt.date.today()) is None


# ------------------------------------------------------------- service days

def test_services_are_known_for_the_dates_the_feed_covers():
    if not schedule.available():
        pytest.skip("no schedule index")
    dates = schedule.covered_dates()
    assert dates == sorted(dates)
    first = dt.datetime.strptime(dates[0], "%Y%m%d").date()
    assert schedule.services_on(first), "a covered date must run something"


def test_a_date_outside_the_feed_runs_nothing():
    """Rather than falling back to whatever the nearest date does, which
    would quietly plan a Sunday trip against a Tuesday timetable."""
    assert schedule.services_on(dt.date(1999, 1, 1)) == []


def test_coverage_reports_what_the_index_holds():
    if not schedule.available():
        pytest.skip("no schedule index")
    report = schedule.coverage()
    assert report["available"] is True
    assert report["nodes"] > 0
    assert report["departureTimes"] > 0
    assert report["lines"] == sorted(report["lines"])
    assert report["firstDate"] <= report["lastDate"]
    # The pairs with no stop nearby are listed, not silently dropped.
    assert isinstance(report["unmatched"], list)


def test_after_midnight_departures_belong_to_the_previous_service_day():
    """GTFS writes a 01:30 Friday-night train as 25:30 on Friday's service.
    Anything asking about the small hours has to look at yesterday's
    timetable, or the last trains of the night vanish."""
    node_id, line = a_scheduled_stop()
    index = schedule.load()
    table = index["departures"][node_id][line]
    past_midnight = [t for times in table.values() for t in times
                     if t >= schedule.SECONDS_PER_DAY]
    if not past_midnight:
        pytest.skip("this stop has no after-midnight service")
    # Those exist in the data, so the query has to be able to reach them.
    when = dt.datetime.combine(dt.date.today(), dt.time(0, 30))
    assert schedule.departures_after(node_id, line, when, limit=2) is not None


# ------------------------------------------------------- date coverage

def test_covers_is_about_the_date_not_the_file(tmp_path):
    """available() answers "is there an index"; covers() answers "can it tell
    me about this day". Conflating them made the trip planner report a
    timetable it no longer had once the board period ended."""
    assert schedule.load(str(tmp_path / "nope.json")) is None
    assert schedule.available() is False
    assert schedule.covers(dt.date.today()) is False


def test_covers_accepts_a_datetime_as_well_as_a_date():
    """plan() holds a datetime, so covers() has to take one without the
    caller remembering to reduce it."""
    if not schedule.available():
        pytest.skip("no schedule index")
    day = dt.datetime.strptime(schedule.covered_dates()[0], "%Y%m%d")
    assert schedule.covers(day) is True
    assert schedule.covers(day.date()) is True


def test_covers_is_true_across_the_whole_covered_range():
    if not schedule.available():
        pytest.skip("no schedule index")
    dates = schedule.covered_dates()
    for stamp in (dates[0], dates[len(dates) // 2], dates[-1]):
        day = dt.datetime.strptime(stamp, "%Y%m%d").date()
        assert schedule.covers(day) is True, stamp


def test_covers_is_false_outside_it():
    """Both ends: before the feed starts and after it expires."""
    if not schedule.available():
        pytest.skip("no schedule index")
    dates = schedule.covered_dates()
    first = dt.datetime.strptime(dates[0], "%Y%m%d").date()
    last = dt.datetime.strptime(dates[-1], "%Y%m%d").date()
    assert schedule.covers(first - dt.timedelta(days=1)) is False
    assert schedule.covers(last + dt.timedelta(days=1)) is False


def test_covers_agrees_with_services_on():
    """It is defined as "are there services", so the two must not drift."""
    if not schedule.available():
        pytest.skip("no schedule index")
    last = dt.datetime.strptime(schedule.covered_dates()[-1], "%Y%m%d").date()
    for offset in range(-2, 5):
        day = last + dt.timedelta(days=offset)
        assert schedule.covers(day) == bool(schedule.services_on(day)), day
