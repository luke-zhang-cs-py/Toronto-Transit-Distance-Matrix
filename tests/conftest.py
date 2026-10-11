"""Shared fixtures.

The project root goes on sys.path here rather than in each test file, and the
Flask test client is defined once now that two files want it.
"""

import datetime
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture(autouse=True)
def no_live_feed_in_tests(monkeypatch):
    """Tests never touch the network -- now actually enforced.

    realtime caches globally, so a test that fetched would leave a live
    reading behind for whatever ran next, and its assertions would depend on
    what TTC happened to be doing. Tests that want live behaviour build a
    Conditions from the recorded fixtures explicitly.

    This used to reset the cache and nothing else, while its docstring
    claimed the stronger property. It was not true: `observed_headways()`
    and `disruptions()` default to `feed=None`, which means *fetch the live
    feed*, so any test calling them without one made a real HTTP request to
    the TTC. Two did.

    That passed on a machine where the request fails -- this one, where the
    certificate chain is intercepted -- and failed in CI, where it succeeds
    and real data comes back. A guard that reads as protection and provides
    none is worse than no guard: the two tests looked like they were pinning
    "no feed means no headways" and were really pinning "the network is
    down".

    The enforcement is the *URL*, not a stub. Replacing `_fetch` was the
    first attempt and it was too broad: `_fetch` is itself under test --
    urllib-then-curl, one test per branch -- and an autouse stub replaced
    the function those tests exercise, so four of them started asserting
    against the stub. Patching `subprocess.run` instead is worse still,
    because test_published_figures runs `pytest --collect-only` through it.

    `.invalid` is reserved by RFC 2606 for exactly this and can never
    resolve, so the real `_fetch` runs, both of its branches fail the way
    they do on a machine with no route to the feed, and `_feed` returns
    None. Nothing under test is replaced, and a test that wants a specific
    fetch result still patches `_fetch` itself.
    """
    from feeds import realtime
    realtime.reset_cache()
    monkeypatch.setattr(realtime, "FEEDS",
                        {kind: "http://feed.invalid/%s" % kind
                         for kind in realtime.FEEDS})
    yield
    realtime.reset_cache()


# ---------------------------------------------------------------------------
# A small timetable
# ---------------------------------------------------------------------------
# schedule_index.json is derived from a 207 MB archive and gitignored, so a
# clone and CI have none -- and every test that wants a timetable used to
# skip, leaving feeds/schedule.py and the timetabled half of the router
# untested wherever the suite actually ran. This builds one: every boardable
# (node, line) pair in the real graph, a train every six minutes from 05:00:16
# to 26:00:16 (the last ones written past midnight, as GTFS does), on two
# services that both run every covered day -- so the de-duplication has real
# duplicates to remove. Dates are relative to today, because the tests plan
# trips "today". The published range is 30 days back to 60 ahead and the
# projection continues it for 800 more, as tools/project_schedule.py would.
def _synthetic_index(today):
    from network import adj

    times = list(range(5 * 3600 + 16, 26 * 3600 + 17, 360))
    departures, matches = {}, {}
    for node_id, edges in adj.items():
        for line in {e["line"] for e in edges if e["line"] != "Transfer"}:
            departures.setdefault(node_id, {})[line] = {"wk": times, "dup": times}
            matches.setdefault(node_id, {})[line] = 120

    def key(day):
        return day.strftime("%Y%m%d")

    first = today - datetime.timedelta(days=30)
    last = today + datetime.timedelta(days=60)
    services = {key(first + datetime.timedelta(days=i)): ["wk", "dup"]
                for i in range((last - first).days + 1)}
    projected = {key(last + datetime.timedelta(days=i)): ["wk"]
                 for i in range(1, 801)}
    return {"builtAt": "2026-01-01T00:00:00",
            "services": services,
            "projected": projected,
            "projection": {"through": (last + datetime.timedelta(days=800)).isoformat()},
            "departures": departures,
            "matchMetres": matches,
            "unmatched": [{"node": "nowhere", "line": "Line 9", "nearestMetres": 1500}]}


@pytest.fixture
def timetable(tmp_path):
    """Load the small timetable above as the schedule index, and put the
    real one (or its absence) back afterwards."""
    from feeds import schedule
    path = tmp_path / "schedule_index.json"
    path.write_text(json.dumps(_synthetic_index(datetime.date.today())),
                    encoding="utf-8")
    schedule.reset()
    assert schedule.load(str(path)) is not None
    yield schedule
    schedule.reset()
