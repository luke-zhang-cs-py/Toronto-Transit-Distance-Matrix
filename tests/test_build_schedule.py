"""The departure-index builder (tools/build_schedule.py), on a GTFS feed small
enough to read.

The real input is a 207 MB archive that is downloaded, never committed, so
this tool went untested -- and it decides which stop every timetabled wait in
the app is read from. Here the feed is written into tmp_path: three stations,
four routes, a handful of trips, and a calendar with a holiday in it. The
graph is replaced by four nodes for the same reason: every match can then be
asserted by name rather than by count.

Nothing is downloaded. The one test of the download path replaces `fetch`.
"""

import json
import os
import zipfile

import pytest

from tools import build_schedule as bs

LINE_1 = "Line 1 (Yonge-University)"

# Union and King are 450 m apart, so each one's nearest Line 1 stop is its
# own. Spadina & King is the case the route constraint exists for. Far East
# is 15 km from any 504 stop, so it is matched to nothing and says so; its
# second line is one the feed does not carry at all.
NODES = {
    "union": {"name": "Union", "lat": 43.6453, "lon": -79.3806, "mode": "subway"},
    "king": {"name": "King", "lat": 43.6490, "lon": -79.3779, "mode": "subway"},
    "spadina_king": {"name": "Spadina & King", "lat": 43.6446, "lon": -79.3950,
                     "mode": "streetcar"},
    "far_east": {"name": "Far East", "lat": 43.7000, "lon": -79.2000,
                 "mode": "streetcar"},
}
LINES = {
    "union": {LINE_1},
    "king": {LINE_1},
    "spadina_king": {"504 King", "510 Spadina"},
    "far_east": {"504 King", "999 Nowhere"},
}

FEED = {
    # The feed spells the subway "Yonge - University", with spaces, which is
    # the near-miss the loose long-name match is for. 510 has no trips, and
    # route 7 is a bus the graph does not have.
    "routes.txt": (
        "route_id,route_short_name,route_long_name,route_type\n"
        "L1,1,Line 1 (Yonge - University),1\n"
        "R504,504,King,0\n"
        "R510,510,Spadina,0\n"
        "R7,7,Bathurst,3\n"),
    "trips.txt": (
        "route_id,service_id,trip_id\n"
        "L1,wk,t1\n"
        "L1,wk,t1b\n"
        "L1,sat,t2\n"
        "R504,wk,t3\n"
        "R7,wk,t7\n"),
    # t1b leaves Union at the same second as t1, so the index has a duplicate
    # to remove. t2 leaves at 25:30, past midnight, with only an arrival time;
    # its second row has no time at all and is skipped.
    "stop_times.txt": (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "t1,08:00:00,08:00:30,S_UNION,1\n"
        "t1,08:02:00,08:02:30,S_KING,2\n"
        "t1b,08:00:00,08:00:30,S_UNION,1\n"
        "t1b,08:10:00,08:10:30,S_KING,2\n"
        "t2,25:30:00,,S_UNION,1\n"
        "t2,,,S_KING,2\n"
        "t3,09:00:00,09:00:00,S_SPK,1\n"
        "t7,09:00:00,09:00:00,S_BATH,1\n"),
    "stops.txt": (
        "stop_id,stop_name,stop_lat,stop_lon\n"
        "S_UNION,Union Station,43.6453,-79.3806\n"
        "S_KING,King Station,43.6490,-79.3779\n"
        "S_SPK,Spadina Ave at King St West,43.6447,-79.3951\n"
        "S_BATH,Bathurst St at King St West,43.6440,-79.4030\n"),
    # Three weeks of weekday and weekend service; a row with a date nobody
    # can parse; and Thanksgiving (Monday 12 October 2026) moved onto the
    # holiday service the way TTC's own feed does it.
    "calendar.txt": (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
        "start_date,end_date\n"
        "wk,1,1,1,1,1,0,0,20261012,20261101\n"
        "sat,0,0,0,0,0,1,1,20261012,20261101\n"
        "bad,1,1,1,1,1,1,1,notadate,20261101\n"),
    "calendar_dates.txt": (
        "service_id,date,exception_type\n"
        "hol,20261012,1\n"
        "wk,20261012,2\n"
        "wk,20270101,2\n"
        "sat,20261101,2\n"),
}


def hms(hours, minutes=0, seconds=0):
    return hours * 3600 + minutes * 60 + seconds


def write_feed(tmp_path, tables=None, name="gtfs.zip"):
    """The feed as a zip, with the byte-order mark TTC ships."""
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        for table, body in (FEED if tables is None else tables).items():
            archive.writestr(table, "﻿" + body)
    return str(path)


@pytest.fixture
def small_graph(monkeypatch):
    monkeypatch.setattr(bs, "nodes", NODES)
    monkeypatch.setattr(bs, "lines_at", lambda node_id: LINES[node_id])


@pytest.fixture
def archive(tmp_path):
    return zipfile.ZipFile(write_feed(tmp_path))


# ------------------------------------------------------------ the pieces

def test_the_graphs_lines_are_every_line_at_every_node(small_graph):
    assert bs.graph_lines() == {LINE_1, "504 King", "510 Spadina", "999 Nowhere"}


def test_routes_match_on_the_number_or_the_loosely_spelled_name(archive):
    matched, missing = bs.match_routes(archive, {LINE_1, "504 King", "510 Spadina",
                                                 "999 Nowhere", ""})
    assert matched == {LINE_1: "L1", "504 King": "R504", "510 Spadina": "R510"}
    assert missing == ["", "999 Nowhere"]


def test_a_shared_track_name_matches_either_of_its_routes(tmp_path):
    """"509/510 Harbourfront" is two routes; the prefix is split first."""
    archive = zipfile.ZipFile(write_feed(tmp_path, {"routes.txt": (
        "route_id,route_short_name,route_long_name,route_type\n"
        "R510,510,Spadina,0\n")}))
    matched, missing = bs.match_routes(archive, {"509/510 Harbourfront"})
    assert matched == {"509/510 Harbourfront": "R510"} and missing == []


def test_only_the_trips_on_wanted_routes_are_kept(archive):
    assert bs.load_trips(archive, {"L1"}) == {
        "t1": ("L1", "wk"), "t1b": ("L1", "wk"), "t2": ("L1", "sat")}


def test_departures_are_grouped_by_route_stop_and_service(archive, monkeypatch, capsys):
    monkeypatch.setattr(bs, "PROGRESS_EVERY", 4)
    found = bs.collect_departures(archive, bs.load_trips(archive, {"L1", "R504"}))
    assert found == {
        ("L1", "S_UNION", "wk"): [hms(8, 0, 30), hms(8, 0, 30)],
        ("L1", "S_KING", "wk"): [hms(8, 2, 30), hms(8, 10, 30)],
        # 25:30 kept as 25:30, read from the arrival time.
        ("L1", "S_UNION", "sat"): [hms(25, 30)],
        ("R504", "S_SPK", "wk"): [hms(9)],
    }
    out = capsys.readouterr().out
    assert "    4 stop_times rows..." in out and "    8 rows read" in out


def test_each_node_is_matched_only_among_its_own_lines_stops(archive, small_graph):
    departures = bs.collect_departures(archive, bs.load_trips(archive, {"L1", "R504"}))
    positions = {"S_UNION": (43.6453, -79.3806, "Union Station"),
                 "S_KING": (43.6490, -79.3779, "King Station"),
                 "S_SPK": (43.6447, -79.3951, "Spadina Ave at King St West")}
    route_of_line = {LINE_1: "L1", "504 King": "R504", "510 Spadina": "R510"}
    matches, unmatched = bs.match_nodes(departures, positions, route_of_line)
    assert matches == {"union": {LINE_1: ("S_UNION", 0)},
                       "king": {LINE_1: ("S_KING", 0)},
                       "spadina_king": {"504 King": ("S_SPK", 14)}}
    # 510 has no departures and 999 no route: neither is a failed match.
    assert len(unmatched) == 1
    node, line, distance = unmatched[0]
    assert (node, line) == ("far_east", "504 King") and distance > bs.MAX_MATCH_METRES


def test_service_dates_apply_the_weekly_pattern_and_its_exceptions(archive):
    services = bs.load_services(archive)
    assert services["20261012"] == ["hol"], "Thanksgiving: holiday service only"
    assert services["20261013"] == ["wk"]
    assert services["20261017"] == ["sat"]
    assert "20261101" not in services, "a date left with no service is dropped"
    assert "20270101" not in services, "removing a date the feed lacks adds nothing"
    assert len(services) == 20


def test_a_feed_without_a_calendar_has_no_service_dates(tmp_path):
    archive = zipfile.ZipFile(write_feed(tmp_path, {"routes.txt": FEED["routes.txt"]}))
    assert bs.load_services(archive) == {}


# ------------------------------------------------------------ the build

def test_the_build_writes_an_index_the_router_can_read(tmp_path, small_graph,
                                                       monkeypatch, capsys):
    out = tmp_path / "schedule_index.json"
    monkeypatch.setattr(bs, "INDEX_PATH", str(out))
    payload = bs.build(write_feed(tmp_path))

    assert json.loads(out.read_text(encoding="utf-8")) == payload
    assert payload["departures"] == {
        "union": {LINE_1: {"wk": [hms(8, 0, 30)], "sat": [hms(25, 30)]}},
        "king": {LINE_1: {"wk": [hms(8, 2, 30), hms(8, 10, 30)]}},
        "spadina_king": {"504 King": {"wk": [hms(9)]}},
    }
    assert payload["stops"]["spadina_king"] == {
        "504 King": {"stopId": "S_SPK", "routeId": "R504"}}
    assert payload["matchMetres"] == {"union": {LINE_1: 0}, "king": {LINE_1: 0},
                                      "spadina_king": {"504 King": 14}}
    assert [u["node"] for u in payload["unmatched"]] == ["far_east"]
    assert payload["source"] == bs.GTFS_URL
    assert payload["maxMatchMetres"] == bs.MAX_MATCH_METRES

    # The projection runs from the last ordinary week, 19 October, and puts
    # Christmas on the service Thanksgiving ran.
    assert payload["projection"]["weekOf"] == "2026-10-19"
    assert payload["projection"]["holidayServices"] == ["hol"]
    assert payload["projected"]["20261225"] == ["hol"]
    assert not set(payload["projected"]) & set(payload["services"])

    log = capsys.readouterr().out
    assert "no GTFS route for: ['999 Nowhere']" in log
    assert "1 pairs had no stop within 900 m" in log
    assert "far_east / 504 King: nearest" in log
    assert "projected 2026-11-01 to 2030-10-31" in log
    assert "wrote %s" % out in log


def test_a_feed_with_nothing_to_project_still_builds(tmp_path, small_graph,
                                                     monkeypatch, capsys):
    """No calendar, so no published dates: the departures are still worth
    writing, and the log says why there is no projection."""
    tables = {name: body for name, body in FEED.items()
              if not name.startswith("calendar")}
    tables["routes.txt"] = ("route_id,route_short_name,route_long_name,route_type\n"
                            "L1,1,Line 1 (Yonge - University),1\n")
    monkeypatch.setattr(bs, "INDEX_PATH", str(tmp_path / "index.json"))
    monkeypatch.setattr(bs, "lines_at", lambda node_id: {LINE_1} & LINES[node_id])
    payload = bs.build(write_feed(tmp_path, tables))
    assert payload["services"] == {} and "projected" not in payload
    assert payload["unmatched"] == []
    log = capsys.readouterr().out
    assert "no projection: the index has no published service dates" in log
    assert "no GTFS route for" not in log and "had no stop within" not in log


# ------------------------------------------------------------ the command

def test_the_command_builds_from_a_local_archive(monkeypatch, tmp_path):
    built = []
    monkeypatch.setattr(bs, "build", built.append)
    monkeypatch.setattr("sys.argv", ["build_schedule.py", "--zip", "local.zip"])
    assert bs.main() == 0
    assert built == ["local.zip"]


def test_the_command_reuses_an_archive_already_downloaded(monkeypatch, tmp_path, capsys):
    (tmp_path / "_gtfs.zip").write_bytes(b"x" * 3_000_000)
    built = []
    monkeypatch.setattr(bs, "PROJ", str(tmp_path))
    monkeypatch.setattr(bs, "build", built.append)
    monkeypatch.setattr(bs, "fetch", lambda *a: pytest.fail("downloaded again"))
    monkeypatch.setattr("sys.argv", ["build_schedule.py"])
    assert bs.main() == 0
    assert built == [os.path.join(str(tmp_path), "_gtfs.zip")]
    assert "(3 MB)" in capsys.readouterr().out


def test_the_command_downloads_when_there_is_no_archive(monkeypatch, tmp_path, capsys):
    fetched, built = [], []

    def fetch(url, dest):
        fetched.append(url)
        with open(dest, "wb") as handle:
            handle.write(b"zip")
        return True

    monkeypatch.setattr(bs, "PROJ", str(tmp_path))
    monkeypatch.setattr(bs, "fetch", fetch)
    monkeypatch.setattr(bs, "build", built.append)
    monkeypatch.setattr("sys.argv", ["build_schedule.py"])
    assert bs.main() == 0
    assert fetched == [bs.GTFS_URL] and len(built) == 1
    assert "downloading %s" % bs.GTFS_URL in capsys.readouterr().out


def test_a_failed_download_exits_non_zero_without_building(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(bs, "PROJ", str(tmp_path))
    monkeypatch.setattr(bs, "fetch", lambda url, dest: False)
    monkeypatch.setattr(bs, "build", lambda path: pytest.fail("built anyway"))
    monkeypatch.setattr("sys.argv", ["build_schedule.py"])
    assert bs.main() == 1
    assert "could not download the GTFS archive" in capsys.readouterr().out
