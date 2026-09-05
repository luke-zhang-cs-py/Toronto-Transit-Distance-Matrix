"""
Core graph primitives shared by every network-building module.

`nodes` and `adj` are the single source of truth for the whole transit
graph. Every module in this package (subway, streetcars, regional)
calls add_node / add_edge / chain to add its own stations and lines
into these same two dictionaries — nothing here is agency-specific.
"""

import logging

log = logging.getLogger(__name__)

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
    """Connect two existing stops, in both directions.

    A missing endpoint used to be skipped in silence, so a mistyped station
    id in any of the network modules produced a graph that was quietly
    missing a link -- and the only symptom is a route that takes the long way
    round, which looks like a modelling choice rather than a typo. It is
    still not fatal (the rest of the map is worth building), but it says so.
    """
    if a not in nodes or b not in nodes:
        log.warning("dropping %s edge %s->%s: %s not in the graph", line, a, b,
                    a if a not in nodes else b)
        return
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
