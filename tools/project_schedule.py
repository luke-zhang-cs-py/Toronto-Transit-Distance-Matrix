"""
tools/project_schedule.py
-------------------------
Extend the timetable past TTC's published dates, labelled as a projection.

Why
---
TTC publishes one board period at a time, six to eight weeks ahead. Past the
last published date every wait used to fall back to the modelled figure,
which is the right answer for a trip in 2029 only if nothing better can be
said -- and something can: the timetable is the same week, Monday to Sunday,
for most of the year, and on a statutory holiday TTC runs its holiday
service. So the latest published week is repeated forward and the holidays
are put on the holiday service, the way the published feed itself does for
Labour Day and Thanksgiving.

What it is not
--------------
A projection. Board periods change frequencies, add and drop trips, and run
reduced summer service; none of that is known in advance. So projected dates
go in their own key, `projected`, never in `services`, and
`feeds/schedule.is_projected` lets the router say "projected" where it would
say "timetabled". Real dates always win: a date the feed publishes is read
from `services` even if a projection also lists it, and every rebuild from a
newer feed replaces projected dates with published ones.

Output (added to schedule_index.json)
------
    "projected": {"20261101": ["3"], "20261102": ["1", "2901", ...], ...},
    "projection": {"through": "2030-10-31", "weekOf": "2026-10-19",
                   "holidayServices": ["4"], "holidays": 89}

Usage
-----
    python tools/project_schedule.py                   # 4 years past the feed
    python tools/project_schedule.py --years 2
"""

import argparse
import datetime as dt
import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_PATH = os.path.join(PROJ, "schedule_index.json")

YEARS = 4
DAY = dt.timedelta(days=1)
STAMP = "%Y%m%d"


def easter(year):
    """Easter Sunday, Gregorian (the anonymous algorithm, Meeus/Jones/Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7    # noqa: E741 -- the algorithm's own name
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return dt.date(year, month, day)


def _nth_monday(year, month, n):
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(7 - first.weekday()) % 7 + 7 * (n - 1))


def _observed(day, taken):
    """The weekday a weekend holiday is observed on: the next free Monday-Friday."""
    while day.weekday() >= 5 or day in taken:
        day += DAY
    return day


def ontario_holidays(year):
    """The days TTC runs holiday service in `year`, each with a name.

    Ontario's statutory holidays plus Civic Holiday, which TTC also runs on
    holiday service. A fixed-date holiday that falls on a weekend runs holiday
    service on the day itself and on the weekday it is observed, which is the
    next weekday no other holiday has: Christmas on a Saturday is observed on
    the Monday and Boxing Day on the Tuesday; Christmas on a Sunday, with
    Boxing Day on the Monday, is observed on the Tuesday.

    Every actual date is placed before any observance, so an observance can
    see a holiday that comes after it in the year. Doing both in one pass let
    Sunday's Christmas take Monday 26 December, which Boxing Day then wrote
    over, and the Tuesday was never a holiday.
    """
    found = {}
    fixed = [(dt.date(year, 1, 1), "New Year's Day"), (dt.date(year, 7, 1), "Canada Day"),
             (dt.date(year, 12, 25), "Christmas Day"), (dt.date(year, 12, 26), "Boxing Day")]
    for day, name in fixed:
        found[day] = name
    found[_nth_monday(year, 2, 3)] = "Family Day"
    found[easter(year) - 2 * DAY] = "Good Friday"
    may25 = dt.date(year, 5, 25)
    found[may25 - dt.timedelta(days=(may25.weekday() or 7))] = "Victoria Day"
    found[_nth_monday(year, 8, 1)] = "Civic Holiday"
    found[_nth_monday(year, 9, 1)] = "Labour Day"
    found[_nth_monday(year, 10, 2)] = "Thanksgiving"
    for day, name in fixed:
        if day.weekday() >= 5:
            found[_observed(day, set(found))] = name + " (observed)"
    return found


def _dates(services):
    return sorted(dt.datetime.strptime(k, STAMP).date() for k in services)


def holiday_services(services):
    """The service ids the published feed runs on the holidays it covers.

    Read from the feed rather than assumed: Labour Day and Thanksgiving in the
    current feed say which id is the holiday service. Falls back to the Sunday
    ids if the feed covers no weekday holiday at all.

    Weekday holidays only. A holiday on a Saturday can run the ordinary
    Saturday service, and learning that id as "the holiday service" put every
    projected holiday on Saturday and holiday service at once -- twice the
    trains.
    """
    days = _dates(services)
    ids = set()
    for year in {d.year for d in days}:
        for holiday in ontario_holidays(year):
            if holiday.weekday() < 5:
                ids.update(services.get(holiday.strftime(STAMP), []))
    if ids:
        return sorted(ids)
    sundays = [d for d in days if d.weekday() == 6]
    return sorted(services[sundays[-1].strftime(STAMP)]) if sundays else []


def representative_week(services):
    """The latest published Monday-to-Sunday week with no holiday in it.

    Returns (monday, {weekday: [service ids]}). The latest because a board
    period's ids and frequencies are what the next one is most like; holiday
    free because a Thanksgiving Monday is not what an ordinary Monday runs.
    """
    days = _dates(services)
    present = set(days)
    holidays = set()
    for year in {d.year for d in days}:
        holidays.update(ontario_holidays(year))
    mondays = [d for d in days if d.weekday() == 0]
    for monday in reversed(mondays):
        week = [monday + i * DAY for i in range(7)]
        if all(d in present for d in week) and not holidays.intersection(week):
            return monday, {d.weekday(): list(services[d.strftime(STAMP)]) for d in week}
    raise ValueError("the feed has no complete week without a holiday to project from")


def project(index, years=YEARS):
    """Add `projected` and `projection` to a schedule index, in place.

    From the day after the last published date to `years` years after it.
    Returns the projection summary.
    """
    services = index.get("services") or {}
    if not services:
        raise ValueError("the index has no published service dates to project from")
    days = _dates(services)
    start, last = days[-1] + DAY, days[-1]
    try:
        through = last.replace(year=last.year + years)
    except ValueError:                       # 29 February
        through = last.replace(year=last.year + years, day=28)

    monday, week = representative_week(services)
    holiday_ids = holiday_services(services)
    holidays = {}
    for year in range(start.year, through.year + 1):
        holidays.update(ontario_holidays(year))

    projected, on_holiday = {}, 0
    day = start
    while day <= through:
        if day in holidays:
            projected[day.strftime(STAMP)] = list(holiday_ids)
            on_holiday += 1
        else:
            projected[day.strftime(STAMP)] = list(week[day.weekday()])
        day += DAY

    summary = {"from": start.isoformat(), "through": through.isoformat(),
               "weekOf": monday.isoformat(), "holidayServices": holiday_ids,
               "holidays": on_holiday}
    index["projected"] = projected
    index["projection"] = summary
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[3])
    parser.add_argument("--years", type=int, default=YEARS)
    parser.add_argument("--index", default=INDEX_PATH)
    args = parser.parse_args()
    if args.years < 1:
        parser.error("--years must be at least 1")
    with open(args.index, encoding="utf-8") as handle:
        index = json.load(handle)
    summary = project(index, args.years)
    with open(args.index, "w", encoding="utf-8") as handle:
        json.dump(index, handle, separators=(",", ":"))
    print("projected %s to %s from the week of %s; %d holiday dates on service %s"
          % (summary["from"], summary["through"], summary["weekOf"],
             summary["holidays"], ",".join(summary["holidayServices"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
