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
POST /api/reach       body {lat, lon} -> {node_id: minutes, ...}
                        (heat-map / "reachable within X minutes" mode)
POST /api/route       body {olat, olon, dlat, dlon} ->
                        {total, totalKm, segments:[...]}
                        (point-to-point trip planning)

This is a fixed schedule *model* (typical dwell/wait/transfer minutes),
not TTC's live feed — TTC's public real-time (GTFS-RT) feed was
retired, and this environment has no network access to pull a live
GTFS static feed either. See network/__init__.py for how to swap in
real GTFS data later.
"""

import math

from flask import Flask, request, jsonify, render_template

from network import nodes, adj
from routing import compute_times, build_route

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
    times = compute_times(lat, lon)
    return jsonify({nid: round(t, 1) for nid, t in times.items()})


@app.route('/api/route', methods=['POST'])
def api_route():
    body = request.get_json(force=True, silent=True)
    olat, olon = _point(body, 'olat', 'olon')
    dlat, dlon = _point(body, 'dlat', 'dlon')
    return jsonify(build_route(olat, olon, dlat, dlon))


if __name__ == '__main__':
    print(f"Loaded {len(nodes)} stops / {sum(len(v) for v in adj.values()) // 2} edges.")
    app.run(debug=True, port=5000)
