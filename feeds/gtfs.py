"""
gtfs.py
--------
Reading TTC's static GTFS archive, in one place.

Two build tools consume that archive -- tools/build_schedule.py for the
timetable index, tools/build_buses.py for the bus routes -- and both had
their own copy of the same three helpers. `rows` and the distance function
were byte-identical; `to_seconds` was the same logic with different variable
names, and the copy in the bus builder had lost the comment explaining why
hours past 24 must not be normalised.

That is the shape of the problem rather than its size: the next fix to the
time parser has to be made twice, and one of the two copies had already
drifted in the way that matters, which is the documentation of a subtlety
somebody will otherwise rediscover.

Nothing here knows about the graph. It reads an archive and hands back rows.
"""

import csv
import http.client
import io
import os
import subprocess
import urllib.error
import urllib.request
import zipfile

# Toronto's open data portal. Republished when the board period changes, so
# it is fetched rather than committed.
ARCHIVE_URL = ("https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/"
               "7795b45e-e65a-4465-81fc-c36b9dfff169/resource/"
               "cfb6b2b8-6191-41e3-bda1-b175c51148cb/download/"
               "opendata_ttc_schedules.zip")

# GTFS route_type values, the two this project uses.
ROUTE_TYPE_SUBWAY = "1"
ROUTE_TYPE_BUS = "3"

SECONDS_PER_DAY = 86400


def fetch(url=ARCHIVE_URL, dest=None, timeout=400):
    """Download the archive to `dest`. Returns True on success.

    urllib first, curl second. Not a preference: on this machine urllib
    cannot verify the certificate chain, because a local inspecting CA is
    not strict-OpenSSL clean, and certifi does not help since the
    interception is what fails. curl verifies differently and succeeds. On a
    machine without that proxy the first branch is the one that runs. Same
    reasoning as realtime._fetch.

    `dest` has no real default -- there is nowhere sensible to write an
    36 MB archive without being told -- so it stays keyword-optional only to
    let `url` be positional, and is checked here rather than left to fail as
    a bare `open(None, "wb")` TypeError two lines down, which says nothing
    about what was actually missing.

    A failure leaves nothing at `dest`. build_schedule.py reuses an archive
    that is already on disk rather than download 36 MB again, so a partial
    or wrong file left behind is not one failed run, it is every run after
    it failing with BadZipFile until somebody finds the file and deletes it.
    Two ways that used to happen: curl without `--fail` saves an HTTP error
    page to `dest` and exits 0, which read as a successful download -- and
    the portal's resource URL does change when the dataset is republished --
    and a connection dropped mid-read left the empty file `open()` had made.
    """
    if dest is None:
        raise ValueError("fetch() requires dest: a path to write the archive to")
    if _fetch_once(url, dest, timeout):
        return True
    _discard(dest)
    return False


def _fetch_once(url, dest, timeout):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response, \
                open(dest, "wb") as handle:
            handle.write(response.read())
        return True
    except (urllib.error.URLError, http.client.HTTPException, OSError,
            ValueError):
        pass
    try:
        done = subprocess.run(["curl", "-sSLf", "--max-time", str(timeout),
                               "-o", dest, url], timeout=timeout + 20)
        return (done.returncode == 0 and os.path.exists(dest)
                and os.path.getsize(dest) > 0)
    except (OSError, subprocess.SubprocessError):
        return False


def _discard(path):
    try:
        os.remove(path)
    except OSError:
        pass


def open_archive(path):
    return zipfile.ZipFile(path)


def rows(archive, name):
    """Every row of a GTFS table, as dicts.

    Streamed rather than listed: stop_times.txt is 207 MB, and the tools that
    read it discard most of what they see as it goes past.

    utf-8-sig because TTC ships a byte-order mark, which turns the first
    column's name into "\\ufeffroute_id" under plain utf-8 -- so every lookup
    of that column silently returns nothing.
    """
    with archive.open(name) as raw:
        for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig")):
            yield row


def to_seconds(value):
    """A GTFS time as seconds after midnight, keeping hours past 24.

    "25:30:00" is half past one in the morning on a service day that began
    the previous morning. Normalising it to 01:30 would file the last train
    of the night before the first train of the day, and any sort or
    comparison after that is wrong in a way that looks plausible.

    None for anything unparseable, which GTFS does contain -- a blank
    departure_time on a timing-point-only row is legal.
    """
    try:
        hours, minutes, seconds = (int(part) for part in value.split(":"))
    except (ValueError, AttributeError):
        return None
    return hours * 3600 + minutes * 60 + seconds


def stop_positions(archive):
    """{stop_id: (lat, lon, name)} for every stop in the feed."""
    return {stop["stop_id"]: (float(stop["stop_lat"]), float(stop["stop_lon"]),
                              stop["stop_name"])
            for stop in rows(archive, "stops.txt")}


def routes_by_id(archive, route_type=None):
    """{route_id: row}, optionally only one route_type."""
    return {route["route_id"]: route for route in rows(archive, "routes.txt")
            if route_type is None or route.get("route_type") == route_type}
