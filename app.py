"""
Toronto Transit Reach — Flask entry point.

This file is deliberately thin: it wires up three HTTP endpoints and
hands off everything else to the rest of the package.

    network/        the transit graph — subway, streetcars, YRT/MiWay,
                     highway hubs (see network/__init__.py for the map)
    routing.py       Dijkstra reachability + point-to-point trip building
    templates/       the page shell (Jinja)
    static/css, js   styling and all browser-side interaction

Run it:
    pip install -r requirements.txt
    python app.py
Then open:  http://127.0.0.1:5000

Endpoints
---------
GET  /              the page itself
GET  /api/network    -> {nodes: {...}, edges: [[a,b,minutes,line], ...]}
                        (fetched once on load, used to draw the line
                        outlines and to sample the heat-radar layer)
POST /api/reach       body {lat, lon} -> {times: {node_id: minutes}, live}
POST /api/route       body {olat, olon, dlat, dlon} ->
                        {total, totalKm, segments:[...], live}
                        (point-to-point trip planning)
GET  /api/live        -> feed freshness, closures, coverage

Both POST bodies accept "live": false to force the fixed schedule model.

Live data
---------
Waits and closures come from TTC's GTFS-realtime feed, which is open and
needs no API key (bustime.ttc.ca). An earlier version of this note said
that feed had been retired; it has not. See realtime.py for what the feed
can and cannot answer, and for how a route degrades to the fixed schedule
model when it is unreachable.

The hop times between stops are still a model -- those need TTC's static
GTFS to improve, and the feed's stop ids do not map onto this hand-built
graph without it. YRT, MiWay and GO have no open real-time feed, so they
stay modelled, and /api/live says so.
"""

import datetime as dt
import math

from flask import Flask, request, jsonify, render_template

import itinerary
import realtime
import schedule
from network import nodes, adj
from routing import build_route, compute_times

app = Flask(__name__)

# Anything outside these is not a place on Earth, and the maths downstream
# will happily return a number for it rather than saying so.
LAT_RANGE = (-90.0, 90.0)
LON_RANGE = (-180.0, 180.0)


class BadRequest(Exception):
    """Something wrong with the request body that the caller can fix."""


def _coord(body, key, low, high):
    """One latitude or longitude out of the request body.

    Every one of these used to be `float(body['lat'])` with nothing around
    it, so a missing key, a null, a string, or a body that was not an object
    all came back as a 500 with a stack trace. Two of them were worse than
    that: float() accepts "nan" and "inf", and NaN then travels all the way
    into the response, where jsonify writes a bare NaN token. That is not
    valid JSON -- Python's parser tolerates it, and the browser's
    JSON.parse throws, so the page breaks with an error about the response
    rather than about the input.
    """
    if not isinstance(body, dict):
        raise BadRequest("Body must be a JSON object.")
    if key not in body:
        raise BadRequest(f"'{key}' is required.")
    try:
        value = float(body[key])
    except (TypeError, ValueError):
        raise BadRequest(f"'{key}' must be a number.")
    if not math.isfinite(value):
        raise BadRequest(f"'{key}' must be a finite number.")
    if not (low <= value <= high):
        raise BadRequest(f"'{key}' must be between {low:g} and {high:g}.")
    return value


def _point(body, lat_key, lon_key):
    return (_coord(body, lat_key, *LAT_RANGE),
            _coord(body, lon_key, *LON_RANGE))


def _depart_at(body):
    """The requested departure, or now.

    Accepts "17:20" for today and a full ISO timestamp for another day.
    Rejected rather than guessed if it is neither: silently planning for
    "now" when somebody asked for 17:20 gives them a plausible itinerary for
    the wrong journey, which is worse than an error.
    """
    raw = (body or {}).get("departAt") if isinstance(body, dict) else None
    if raw in (None, "", "now"):
        return dt.datetime.now().replace(second=0, microsecond=0)
    if not isinstance(raw, str):
        raise BadRequest("'departAt' must be \"HH:MM\", an ISO timestamp, or \"now\".")

    text = raw.strip()
    for pattern in ("%H:%M", "%H:%M:%S"):
        try:
            clock = dt.datetime.strptime(text, pattern).time()
            return dt.datetime.combine(dt.date.today(), clock)
        except ValueError:
            pass
    try:
        return dt.datetime.fromisoformat(text).replace(second=0, microsecond=0)
    except ValueError:
        raise BadRequest("'departAt' must be \"HH:MM\", an ISO timestamp, or \"now\".")


def _count(body, key, default, low, high):
    value = (body or {}).get(key, default) if isinstance(body, dict) else default
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise BadRequest(f"'{key}' must be a whole number.")
    if not (low <= value <= high):
        raise BadRequest(f"'{key}' must be between {low} and {high}.")
    return value


def _conditions(body):
    """The live network reading for this request, unless asked not to.

    Live by default, because a router that has to be asked for current data
    is a timetable. `{"live": false}` gets the fixed schedule model, which is
    what the tests use and what you want when comparing two routes without
    the ground moving between them.
    """
    if isinstance(body, dict) and body.get("live") is False:
        return realtime.Conditions.static()
    return realtime.Conditions.live_now()


@app.errorhandler(BadRequest)
def _bad_request(exc):
    return jsonify({'error': str(exc)}), 400


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/network')
def api_network():
    out_nodes = {nid: {'name': n['name'], 'lat': n['lat'], 'lon': n['lon'], 'mode': n['mode']}
                 for nid, n in nodes.items()}
    seen = set()
    out_edges = []
    for a, edges in adj.items():
        for e in edges:
            b = e['to']
            key = tuple(sorted((a, b))) + (e['line'],)
            if key in seen:
                continue
            seen.add(key)
            out_edges.append([a, b, e['min'], e['line']])
    return jsonify({'nodes': out_nodes, 'edges': out_edges})


@app.route('/api/reach', methods=['POST'])
def api_reach():
    body = request.get_json(force=True, silent=True)
    lat, lon = _point(body, 'lat', 'lon')
    conditions = _conditions(body)
    times = compute_times(lat, lon, conditions=conditions)
    # `times` under its own key rather than the node ids at the top level.
    # Flat, there was nowhere to put `live` that a node id could not also
    # occupy, and a response whose keys are partly data and partly metadata
    # cannot be read without knowing every node id in advance.
    return jsonify({
        'times': {nid: round(t, 1) for nid, t in times.items()},
        'live': conditions.live,
    })


@app.route('/api/route', methods=['POST'])
def api_route():
    body = request.get_json(force=True, silent=True)
    olat, olon = _point(body, 'olat', 'olon')
    dlat, dlon = _point(body, 'dlat', 'dlon')
    conditions = _conditions(body)
    route = build_route(olat, olon, dlat, dlon, conditions=conditions)
    # Every trip says whether it was planned against live data or the fixed
    # schedule. A number that silently switches between measured and assumed
    # is worse than either, because you cannot tell which you are reading.
    route['live'] = conditions.live
    return jsonify(route)


@app.route('/api/trips', methods=['POST'])
def api_trips():
    """Several ways to make one trip, for a departure time, with clock times.

    body {olat, olon, dlat, dlon, departAt?, alternatives?, later?,
          compare?, live?}

    With compare (the default) the answer also includes driving to the
    network and driving or walking the whole way, so the transit time sits
    next to what somebody would otherwise do.

    Separate from /api/route rather than replacing it: /api/route answers a
    duration for the map, this answers "what time do I arrive", and the two
    want different shapes.
    """
    body = request.get_json(force=True, silent=True)
    olat, olon = _point(body, 'olat', 'olon')
    dlat, dlon = _point(body, 'dlat', 'dlon')
    depart_at = _depart_at(body)
    alternatives = _count(body, 'alternatives', itinerary.DEFAULT_ALTERNATIVES, 0, 5)
    later = _count(body, 'later', itinerary.DEFAULT_LATER, 0, 8)
    # Comparison on by default: a transit time is only useful next to the
    # alternative somebody would otherwise choose.
    compare = (body or {}).get('compare', True) is not False

    return jsonify(itinerary.plan((olat, olon), (dlat, dlon),
                                  depart_at=depart_at,
                                  conditions=_conditions(body),
                                  alternatives=alternatives,
                                  later=later,
                                  compare=compare))


@app.route('/api/live')
def api_live():
    """What the live feed currently says: freshness, closures, coverage.

    Its own endpoint because the page wants it once, on load and on a timer,
    rather than bundled into every route response.
    """
    snap = realtime.snapshot()
    snap['schedule'] = schedule.coverage()
    return jsonify(snap)


if __name__ == '__main__':
    print(f"Loaded {len(nodes)} stops / {sum(len(v) for v in adj.values()) // 2} edges.")
    # Warm the live reading before serving, and keep it warm on a background
    # thread. Without this the first route request pays the fetch -- measured
    # at 5.2 seconds for 730 KB -- and one request every TTL pays it again.
    realtime.start_refresh()
    if realtime.refresh():
        snap = realtime.snapshot()
        print(f"Live TTC feed: {snap['routesWithObservedHeadway']} routes measured, "
              f"{len(snap['closed'])} closed, {len(snap['detour'])} on detour.")
    else:
        print("Live TTC feed unavailable -- serving the fixed schedule model.")
    app.run(debug=True, port=5000)
