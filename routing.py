"""
The routing engine: everything that turns the graph in `network` into
actual travel times and trips. Two public entry points:

    compute_times(lat, lon)         -> {node_id: minutes, ...}
        Dijkstra from a virtual origin point to every node in the
        network. This is what powers the "reachable within X minutes"
        heat-map mode.

    build_route(olat, olon, dlat, dlon) -> {total, totalKm, segments}
        Full point-to-point trip: walk to the best entry point, ride
        the shortest sequence of legs, walk to the destination. Each
        segment carries both time and real (haversine) distance.
"""

import heapq

import geo
import realtime
from network import nodes, adj, WALK_KMH, lines_at


def haversine_km(lat1, lon1, lat2, lon2):
    """Kept as a name because itinerary and the tests import it from here.
    The formula lives in geo, which is also what the build tools use."""
    return geo.km(lat1, lon1, lat2, lon2)


def walk_minutes(km):
    return km / WALK_KMH * 60


def compute_times(olat, olon, with_paths=False, conditions=None):
    """Dijkstra from a virtual origin point to every node. If with_paths is
    True, also returns predecessor node/line maps for path reconstruction.

    `conditions` is a realtime.Conditions -- one frozen reading of the live
    feed, or the static model. Frozen because the weights must not move while
    the search runs: a shortest path over a graph that changes underneath you
    is not a shortest path.
    """
    if conditions is None:
        conditions = realtime.Conditions.static()

    time = {}
    prev_node = {}
    prev_line = {}
    for nid, n in nodes.items():
        wait, _measured = conditions.boarding_wait(lines_at(nid), n['mode'])
        time[nid] = walk_minutes(haversine_km(olat, olon, n['lat'], n['lon'])) + wait
        prev_node[nid] = None
        prev_line[nid] = None

    visited = set()
    pq = [(t, nid) for nid, t in time.items()]
    heapq.heapify(pq)
    while pq:
        t, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        if t > time[u]:
            continue
        for edge in adj[u]:
            # A closed line is absent, not expensive: skipping the edge lets
            # the search route around it, which is what somebody standing on
            # the platform has to do.
            extra = conditions.impact_on(edge['line'])
            if extra is None:
                continue
            v, w = edge['to'], edge['min'] + extra
            nt = t + w
            if nt < time[v]:
                time[v] = nt
                prev_node[v] = u
                prev_line[v] = edge['line']
                heapq.heappush(pq, (nt, v))

    if with_paths:
        return time, prev_node, prev_line
    return time


def path_km(points):
    km = 0.0
    for i in range(1, len(points)):
        km += haversine_km(points[i - 1]['lat'], points[i - 1]['lon'],
                           points[i]['lat'], points[i]['lon'])
    return km


def build_route(olat, olon, dlat, dlon, conditions=None):
    if conditions is None:
        conditions = realtime.Conditions.static()
    time, prev_node, prev_line = compute_times(olat, olon, with_paths=True,
                                               conditions=conditions)
    direct_walk = walk_minutes(haversine_km(olat, olon, dlat, dlon))
    direct_km = haversine_km(olat, olon, dlat, dlon)

    best_id, best_total = None, direct_walk
    for nid, n in nodes.items():
        total = time[nid] + walk_minutes(haversine_km(n['lat'], n['lon'], dlat, dlon))
        if total < best_total:
            best_total, best_id = total, nid

    if best_id is None:
        return {
            'total': direct_walk, 'totalKm': direct_km,
            'segments': [{'type': 'walk', 'from': {'lat': olat, 'lon': olon, 'name': 'Start'},
                          'to': {'lat': dlat, 'lon': dlon, 'name': 'Destination'},
                          'minutes': direct_walk, 'km': direct_km}]
        }

    chain_ids, line_at_step = _walk_back(best_id, prev_node, prev_line)

    segments = []
    first = nodes[chain_ids[0]]
    d0 = haversine_km(olat, olon, first['lat'], first['lon'])
    segments.append({'type': 'walk', 'from': {'lat': olat, 'lon': olon, 'name': 'Start'},
                     'to': first, 'minutes': walk_minutes(d0), 'km': d0})
    segments += _ride_legs(chain_ids, line_at_step, time)

    last = nodes[best_id]
    dlast = haversine_km(last['lat'], last['lon'], dlat, dlon)
    segments.append({'type': 'walk', 'from': last,
                     'to': {'lat': dlat, 'lon': dlon, 'name': 'Destination'},
                     'minutes': walk_minutes(dlast), 'km': dlast})

    _charge_boarding_wait(segments, time[chain_ids[0]] - walk_minutes(d0))

    # Summed from the parts rather than taken from Dijkstra's figure. The two
    # used to be worked out separately and disagreed by exactly the boarding
    # wait: best_total included it, no segment did, and the page prints both.
    # A trip whose legs do not add up to its own total is the kind of wrong
    # that makes a reader distrust every other number on the screen.
    return {
        'total': sum(seg['minutes'] for seg in segments),
        'totalKm': sum(seg['km'] for seg in segments),
        'segments': segments,
    }


def _walk_back(end_id, prev_node, prev_line):
    """The chain of stops from the entry point to `end_id`, and the line used
    at each step.

    Dijkstra leaves a predecessor per node; this reads it backwards into
    forward order. Returned as two lists of lengths n and n-1: the line at
    step i is how you got from chain[i] to chain[i + 1].
    """
    chain_ids = [end_id]
    line_at_step = []
    cur = end_id
    while prev_node[cur] is not None:
        line_at_step.insert(0, prev_line[cur])
        cur = prev_node[cur]
        chain_ids.insert(0, cur)
    return chain_ids, line_at_step


def _ride_legs(chain_ids, line_at_step, time):
    """Consecutive stops on the same line collapsed into one leg.

    An itinerary that lists every stop between Union and Finch is a list of
    stations, not directions. What a reader wants is "ride Line 1 from Union
    to Finch", so runs of the same line become a single segment.
    """
    legs = []
    i = 0
    while i < len(line_at_step):
        line = line_at_step[i]
        j = i
        while j < len(line_at_step) and line_at_step[j] == line:
            j += 1
        start_node, end_node = chain_ids[i], chain_ids[j]
        legs.append({
            'type': 'transfer' if line == 'Transfer' else 'transit', 'line': line,
            'from': nodes[start_node], 'to': nodes[end_node],
            # The difference of two settled Dijkstra distances is exactly the
            # sum of the edge weights along this run.
            'minutes': time[end_node] - time[start_node],
            'km': path_km([nodes[nid] for nid in chain_ids[i:j + 1]]),
        })
        i = j
    return legs


def _charge_boarding_wait(segments, wait):
    """Put the wait for the first vehicle on the leg it belongs to.

    Dijkstra charges it when entering the network -- it is the difference
    between the walk to the first stop and that stop's cost -- but it is not
    walking time and it is not riding time, so it had nowhere to go and was
    quietly dropped from the itinerary. It belongs to boarding, so it goes on
    the first leg that is not a walk, labelled, so the leg can say how much
    of itself is standing on a platform.
    """
    if wait <= 0:
        return
    for seg in segments:
        if seg['type'] != 'walk':
            seg['minutes'] += wait
            seg['wait'] = wait
            return
