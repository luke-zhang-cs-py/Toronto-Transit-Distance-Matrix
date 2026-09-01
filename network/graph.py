"""
Core graph primitives shared by every network-building module.

`nodes` and `adj` are the single source of truth for the whole transit
graph. Every module in this package (subway, streetcars, regional)
calls add_node / add_edge / chain to add its own stations and lines
into these same two dictionaries — nothing here is agency-specific.
"""

WALK_KMH = 4.8          # average walking pace used everywhere
TRANSFER = 3            # minutes penalty for a same-spot mode/line change
WAIT_BY_MODE = {'subway': 4, 'tram': 6, 'yrt': 8, 'go': 20, 'miway': 10}

nodes = {}   # id -> {'name','lat','lon','mode'}
adj = {}     # id -> [{'to','min','line'}]


def add_node(nid, name, lat, lon, mode):
    if nid not in nodes:
        nodes[nid] = {'name': name, 'lat': lat, 'lon': lon, 'mode': mode}
        adj[nid] = []


def add_edge(a, b, minutes, line):
    if a in nodes and b in nodes:
        adj[a].append({'to': b, 'min': minutes, 'line': line})
        adj[b].append({'to': a, 'min': minutes, 'line': line})


def chain(seq, hop, mode, line):
    """Add a sequence of stations as nodes, connected in order by edges
    of the given line. Stations that already exist (e.g. an interchange
    shared by two lines) are left as-is; only new edges are added."""
    prev = None
    for s in seq:
        add_node(s['id'], s['name'], s['lat'], s['lon'], mode)
        if prev is not None:
            add_edge(prev, s['id'], hop, line)
        prev = s['id']
