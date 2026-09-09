"""The two extracted modules: distance, and reading GTFS.

Both were duplicated before -- haversine three times, the GTFS helpers twice
-- and neither copy had a test. That is the combination worth fixing
together: shared code with no tests is shared risk, and the copy that had
already drifted was the one whose documentation went missing.
"""

import math
import zipfile

import pytest

import geo
import gtfs

UNION = (43.6453, -79.3806)
FINCH = (43.7805, -79.4151)


# ------------------------------------------------------------------ distance

def test_a_known_distance():
    """Union to Finch is about 15 km as the crow flies."""
    assert 14 < geo.km(*UNION, *FINCH) < 17


def test_the_two_units_agree():
    """One formula, two wrappers. If these ever disagree, the split has been
    undone by somebody editing one of them."""
    assert geo.metres(*UNION, *FINCH) == pytest.approx(geo.km(*UNION, *FINCH) * 1000)


def test_distance_is_symmetric():
    assert geo.km(*UNION, *FINCH) == pytest.approx(geo.km(*FINCH, *UNION))


def test_a_point_is_no_distance_from_itself():
    assert geo.km(*UNION, *UNION) == pytest.approx(0.0)
    assert geo.metres(*UNION, *UNION) == pytest.approx(0.0)


def test_it_matches_what_routing_publishes():
    """routing.haversine_km is now a thin alias. The alias exists because
    itinerary and the tests import that name; this checks it still means the
    same thing."""
    import routing
    assert routing.haversine_km(*UNION, *FINCH) == pytest.approx(geo.km(*UNION, *FINCH))


def test_antipodes_do_not_blow_up():
    """asin of anything above 1 is a domain error, and floating point can
    push the haversine term just past it for opposite points."""
    assert geo.km(0, 0, 0, 180) == pytest.approx(math.pi * geo.EARTH_RADIUS_KM, rel=1e-6)
    assert geo.km(90, 0, -90, 0) == pytest.approx(math.pi * geo.EARTH_RADIUS_KM, rel=1e-6)


# ------------------------------------------------------------- GTFS times

@pytest.mark.parametrize("value,expected", [
    ("00:00:00", 0),
    ("09:30:00", 9 * 3600 + 30 * 60),
    ("23:59:59", 86399),
])
def test_ordinary_times(value, expected):
    assert gtfs.to_seconds(value) == expected


def test_hours_past_midnight_are_kept():
    """The subtlety this module exists to keep documented in one place.

    "25:30:00" is half past one in the morning on a service day that began
    the previous morning. Normalising it to 01:30 would file the last train
    of the night before the first train of the day, and every sort or
    comparison after that is wrong in a way that looks plausible.
    """
    assert gtfs.to_seconds("25:30:00") == 25 * 3600 + 30 * 60
    assert gtfs.to_seconds("25:30:00") > gtfs.SECONDS_PER_DAY
    assert gtfs.to_seconds("25:30:00") > gtfs.to_seconds("05:00:00")


@pytest.mark.parametrize("value", ["", None, "nonsense", "9:30", "09:30",
                                   "09:30:00.5", 930])
def test_an_unparseable_time_is_none(value):
    """GTFS legally contains blank departure_times on timing-point rows, so
    this is data rather than corruption -- None lets the caller skip the row
    instead of crashing the build."""
    assert gtfs.to_seconds(value) is None


# -------------------------------------------------------------- GTFS tables

def a_tiny_archive(tmp_path, name="stops.txt", body=None):
    """A one-table GTFS zip, with TTC's byte-order mark."""
    path = tmp_path / "tiny.zip"
    text = body if body is not None else (
        "stop_id,stop_code,stop_name,stop_lat,stop_lon\n"
        "1,1,Union,43.6453,-79.3806\n"
        "2,2,Finch,43.7805,-79.4151\n")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, "﻿" + text)
    return path


def test_rows_reads_a_table(tmp_path):
    archive = gtfs.open_archive(a_tiny_archive(tmp_path))
    found = list(gtfs.rows(archive, "stops.txt"))
    assert len(found) == 2
    assert found[0]["stop_name"] == "Union"


def test_the_byte_order_mark_does_not_corrupt_the_first_column(tmp_path):
    """TTC ships a BOM. Under plain utf-8 the first column's name becomes
    "\\ufeffstop_id", so every lookup of it silently returns nothing -- which
    is the worst kind of encoding bug, because nothing raises."""
    archive = gtfs.open_archive(a_tiny_archive(tmp_path))
    first = next(iter(gtfs.rows(archive, "stops.txt")))
    assert "stop_id" in first
    assert not any(key.startswith("﻿") for key in first)


def test_rows_streams_rather_than_listing(tmp_path):
    """stop_times.txt is 207 MB and the callers discard most of it as it goes
    past. A generator is the difference between that and 207 MB resident."""
    archive = gtfs.open_archive(a_tiny_archive(tmp_path))
    assert not isinstance(gtfs.rows(archive, "stops.txt"), list)
    assert hasattr(gtfs.rows(archive, "stops.txt"), "__next__")


def test_stop_positions_parses_coordinates(tmp_path):
    archive = gtfs.open_archive(a_tiny_archive(tmp_path))
    positions = gtfs.stop_positions(archive)
    assert positions["1"][0] == pytest.approx(43.6453)
    assert positions["1"][2] == "Union"
    assert geo.km(*positions["1"][:2], *positions["2"][:2]) > 14


def test_routes_can_be_filtered_by_type(tmp_path):
    body = ("route_id,route_short_name,route_long_name,route_type\n"
            "1,1,Line 1 (Yonge-University),1\n"
            "504,504,King,3\n")
    archive = gtfs.open_archive(a_tiny_archive(tmp_path, "routes.txt", body))
    assert set(gtfs.routes_by_id(archive)) == {"1", "504"}
    assert set(gtfs.routes_by_id(archive, gtfs.ROUTE_TYPE_SUBWAY)) == {"1"}
    assert set(gtfs.routes_by_id(archive, gtfs.ROUTE_TYPE_BUS)) == {"504"}


def test_a_failed_download_reports_rather_than_raising(tmp_path, monkeypatch):
    """A build tool that dies on a network blip has to be re-run from the
    start; one that returns False can say so and exit cleanly."""
    def refuse(*args, **kwargs):
        raise OSError("no network")

    monkeypatch.setattr(gtfs.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(gtfs.subprocess, "run", refuse)
    assert gtfs.fetch("https://example.invalid/x.zip",
                      str(tmp_path / "out.zip")) is False


def test_the_archive_url_is_defined_once():
    """It was written out in the schedule tool as well; both read it here."""
    import tools_build_schedule
    assert tools_build_schedule.GTFS_URL == gtfs.ARCHIVE_URL


def test_both_build_tools_use_the_shared_helpers():
    """The structural half of the deduplication.

    `metres` and `rows` were byte-identical in the two tools and
    `to_seconds` had lost its documentation in one of them. Redefining any
    of them locally is that drift starting again.
    """
    import inspect
    import tools_build_buses
    import tools_build_schedule

    for module in (tools_build_buses, tools_build_schedule):
        source = inspect.getsource(module)
        for name in ("def rows(", "def to_seconds(", "def metres("):
            assert name not in source, f"{module.__name__} redefines {name}"
        assert module.rows is gtfs.rows
        assert module.to_seconds is gtfs.to_seconds
        assert module.metres is geo.metres
