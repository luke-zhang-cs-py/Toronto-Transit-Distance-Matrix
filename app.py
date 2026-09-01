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

from flask import Flask, request, jsonify, render_template

from network import nodes, adj
from routing import compute_times, build_route

app = Flask(__name__)


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
    body = request.get_json(force=True)
    lat, lon = float(body['lat']), float(body['lon'])
    times = compute_times(lat, lon)
    return jsonify({nid: round(t, 1) for nid, t in times.items()})


@app.route('/api/route', methods=['POST'])
def api_route():
    body = request.get_json(force=True)
    route = build_route(float(body['olat']), float(body['olon']),
                         float(body['dlat']), float(body['dlon']))
    return jsonify(route)


if __name__ == '__main__':
    print(f"Loaded {len(nodes)} stops / {sum(len(v) for v in adj.values()) // 2} edges.")
    app.run(debug=True, port=5000)
