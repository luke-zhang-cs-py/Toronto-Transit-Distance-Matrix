"""Shared fixtures.

The project root goes on sys.path here rather than in each test file, and the
Flask test client is defined once now that two files want it.
"""

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
    import realtime
    realtime.reset_cache()
    monkeypatch.setattr(realtime, "FEEDS",
                        {kind: "http://feed.invalid/%s" % kind
                         for kind in realtime.FEEDS})
    yield
    realtime.reset_cache()
