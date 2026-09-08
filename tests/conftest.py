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
def no_live_feed_in_tests():
    """Tests never touch the network.

    realtime caches globally, so a test that fetched would leave a live
    reading behind for whatever ran next -- and its assertions would depend
    on what TTC happened to be doing. Tests that want live behaviour build a
    Conditions from the recorded fixtures explicitly.
    """
    import realtime
    realtime.reset_cache()
    yield
    realtime.reset_cache()
