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

import math
import heapq

from network import nodes, adj, WALK_KMH, WAIT_BY_MODE


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def walk_minutes(km):
    return km / WALK_KMH * 60


def compute_times(olat, olon, with_paths=False):
    """Dijkstra from a virtual origin point to every node. If with_paths is
    True, also returns predecessor node/line maps for path reconstruction."""
    time = {}
    prev_node = {}
    prev_line = {}
    for nid, n in nodes.items():
        wait = WAIT_BY_MODE.get(n['mode'], 6)
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
            v, w = edge['to'], edge['min']
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


def build_route(olat, olon, dlat, dlon):
    time, prev_node, prev_line = compute_times(olat, olon, with_paths=True)
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

    # reconstruct node chain from origin-entry to best_id
    chain_ids = [best_id]
    line_at_step = []
    cur = best_id
    while prev_node[cur] is not None:
        line_at_step.insert(0, prev_line[cur])
        cur = prev_node[cur]
        chain_ids.insert(0, cur)

    segments = []
    first = nodes[chain_ids[0]]
    d0 = haversine_km(olat, olon, first['lat'], first['lon'])
    segments.append({'type': 'walk', 'from': {'lat': olat, 'lon': olon, 'name': 'Start'},
                     'to': first, 'minutes': walk_minutes(d0), 'km': d0})

    i = 0
    while i < len(line_at_step):
        line = line_at_step[i]
        start_node = chain_ids[i]
        j = i
        while j < len(line_at_step) and line_at_step[j] == line:
            j += 1
        end_node = chain_ids[j]
        leg_minutes = time[end_node] - time[start_node]
        leg_path = [nodes[nid] for nid in chain_ids[i:j + 1]]
        segments.append({
            'type': 'transfer' if line == 'Transfer' else 'transit', 'line': line,
            'from': nodes[start_node], 'to': nodes[end_node],
            'minutes': leg_minutes, 'km': path_km(leg_path)
        })
        i = j

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
