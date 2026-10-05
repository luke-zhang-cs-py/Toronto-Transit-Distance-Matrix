"""The projection past TTC's published dates (tools/project_schedule.py).

No real index needed: each case builds the few dates it is about, so CI --
which never has schedule_index.json -- runs all of them. The holiday dates
are checked against the published calendar for each year, not against the
same arithmetic.
"""

import datetime as dt

import pytest

from tools import project_schedule as ps

D = dt.date


def test_easter_on_known_years():
    # Published Easter Sundays.
    assert [ps.easter(y) for y in (2026, 2027, 2028, 2029, 2030)] == [
        D(2026, 4, 5), D(2027, 3, 28), D(2028, 4, 16), D(2029, 4, 1), D(2030, 4, 21)]


def test_the_holidays_ttc_runs_holiday_service_on():
    got = ps.ontario_holidays(2027)
    assert {d: n for d, n in got.items() if "observed" not in n} == {
        D(2027, 1, 1): "New Year's Day", D(2027, 2, 15): "Family Day",
        D(2027, 3, 26): "Good Friday", D(2027, 5, 24): "Victoria Day",
        D(2027, 7, 1): "Canada Day", D(2027, 8, 2): "Civic Holiday",
        D(2027, 9, 6): "Labour Day", D(2027, 10, 11): "Thanksgiving",
        D(2027, 12, 25): "Christmas Day", D(2027, 12, 26): "Boxing Day"}


def test_a_weekend_holiday_is_observed_on_the_next_free_weekday():
    # Christmas 2027 is a Saturday and Boxing Day a Sunday: observed Monday
    # and Tuesday, in that order, not both on the Monday.
    got = ps.ontario_holidays(2027)
    assert got[D(2027, 12, 27)] == "Christmas Day (observed)"
    assert got[D(2027, 12, 28)] == "Boxing Day (observed)"
    # Canada Day 2029 is a Sunday.
    assert ps.ontario_holidays(2029)[D(2029, 7, 2)] == "Canada Day (observed)"
    # A weekday holiday has no second day.
    assert not any("observed" in n for d, n in ps.ontario_holidays(2026).items()
                   if d.month == 7)


def test_victoria_day_is_the_monday_before_the_25th_even_when_the_25th_is_a_monday():
    assert D(2026, 5, 18) in ps.ontario_holidays(2026)      # the 25th is a Monday
    assert D(2030, 5, 20) in ps.ontario_holidays(2030)


def _feed(first, last, holiday_on=()):
    """A published feed: weekdays run 'wk-<day>', Saturday 'sat', Sunday 'sun',
    and the given dates the holiday service 'hol'."""
    services, day = {}, first
    while day <= last:
        if day in holiday_on:
            ids = ["hol"]
        elif day.weekday() == 5:
            ids = ["sat"]
        elif day.weekday() == 6:
            ids = ["sun"]
        else:
            ids = ["wk", "wk-%d" % day.weekday()]
        services[day.strftime(ps.STAMP)] = ids
        day += ps.DAY
    return {"services": services, "departures": {}}


def test_the_projection_repeats_the_latest_ordinary_week_and_runs_holidays_on_holiday_service():
    index = _feed(D(2026, 9, 6), D(2026, 10, 31), holiday_on={D(2026, 9, 7), D(2026, 10, 12)})
    summary = ps.project(index, years=4)
    projected = index["projected"]
    assert summary["from"] == "2026-11-01" and summary["through"] == "2030-10-31"
    assert summary["weekOf"] == "2026-10-19", "the last whole week with no holiday in it"
    assert summary["holidayServices"] == ["hol"], "read off Labour Day and Thanksgiving"
    assert len(projected) == (D(2030, 10, 31) - D(2026, 11, 1)).days + 1
    assert projected["20261102"] == ["wk", "wk-0"]                 # a Monday
    assert projected["20261107"] == ["sat"]


def test_projected_holidays_and_ordinary_days(tmp_path):
    index = _feed(D(2026, 9, 6), D(2026, 10, 31), holiday_on={D(2026, 9, 7), D(2026, 10, 12)})
    ps.project(index, years=4)
    p = index["projected"]
    assert p["20291008"] == ["hol"], "Thanksgiving 2029"
    assert p["20291011"] == ["wk", "wk-3"], "an ordinary Thursday"
    assert p["20271227"] == ["hol"] and p["20271228"] == ["hol"], "observed Christmas, Boxing Day"
    assert p["20280414"] == ["hol"], "Good Friday 2028"
    assert p["20301031"] == ["wk", "wk-3"]
    assert "20301101" not in p, "four years, not a day more"
    assert not set(p) & set(index["services"]), "never a published date"


def test_a_feed_with_no_holiday_projects_holidays_on_the_sunday_service():
    index = _feed(D(2026, 10, 13), D(2026, 10, 31))
    summary = ps.project(index, years=1)
    assert summary["holidayServices"] == ["sun"]
    assert index["projected"]["20261225"] == ["sun"]


def test_a_feed_without_a_whole_ordinary_week_is_refused_not_guessed():
    with pytest.raises(ValueError, match="no complete week"):
        ps.project(_feed(D(2026, 10, 7), D(2026, 10, 12), holiday_on={D(2026, 10, 12)}))
    with pytest.raises(ValueError, match="no published service dates"):
        ps.project({"services": {}})


def test_a_feed_ending_on_29_february_projects_to_28_february():
    index = _feed(D(2028, 2, 1), D(2028, 2, 29))
    assert ps.project(index, years=1)["through"] == "2029-02-28"


def test_the_command_writes_the_projection_into_the_index(tmp_path, monkeypatch, capsys):
    import json
    path = tmp_path / "schedule_index.json"
    path.write_text(json.dumps(_feed(D(2026, 9, 6), D(2026, 10, 31),
                                     holiday_on={D(2026, 9, 7), D(2026, 10, 12)})))
    monkeypatch.setattr("sys.argv", ["project_schedule.py", "--index", str(path), "--years", "2"])
    assert ps.main() == 0
    written = json.loads(path.read_text())
    assert written["projection"]["through"] == "2028-10-31"
    assert "projected 2026-11-01 to 2028-10-31" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["project_schedule.py", "--index", str(path), "--years", "0"])
    with pytest.raises(SystemExit):
        ps.main()
