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

# Typical wait for the next vehicle, by mode. Half the headway, roughly: a
# subway every 4-5 minutes averages a 4-minute wait, a GO train every 40
# averages 20.
WAIT_BY_MODE = {'subway': 4, 'tram': 6, 'bus': 7, 'yrt': 8, 'go': 20,
                'miway': 10}

# For a mode not in that table. It was written as a bare 6 at the one call
# site, which made it look like a considered number for streetcars rather
# than what it is: a shrug for a mode nobody has measured. A test asserts
# every mode in the graph has a real entry, so reaching this means somebody
# added a mode and forgot the wait.
DEFAULT_WAIT_MIN = 6

nodes = {}   # id -> {'name','lat','lon','mode'}
adj = {}     # id -> [{'to','min','line'}]

# line name -> the mode that actually runs it, e.g. 'GO Transit (Milton/
# Lakeshore W + bus)' -> 'go'. Recorded here rather than trusted from a
# node's `mode`, because a node is shared by every line that calls at it
# (Union is a subway stop AND a GO stop) while a line has exactly one mode.
# `add_node` keeps only the first mode it ever sees for a given id -- whoever
# builds the node first "owns" it -- so at an interchange the node's mode can
# be the wrong agency entirely for a line boarded there. Keying by line name
# instead gives every line its own, correct answer.
LINE_MODES = {}


def add_node(nid, name, lat, lon, mode):
    if nid not in nodes:
        nodes[nid] = {'name': name, 'lat': lat, 'lon': lon, 'mode': mode}
        adj[nid] = []


def add_edge(a, b, minutes, line, mode=None):
    """Connect two existing stops, in both directions.

    A missing endpoint used to be skipped in silence, so a mistyped station
    id in any of the network modules produced a graph that was quietly
    missing a link -- and the only symptom is a route that takes the long way
    round, which looks like a modelling choice rather than a typo. It is
    still not fatal (the rest of the map is worth building), but it says so.

    `mode` records which agency actually runs `line`, independent of
    whatever mode the endpoint nodes happen to carry (see LINE_MODES above).
    Omit it for edges -- like 'Transfer' -- that are not a line anybody
    boards.
    """
    if a not in nodes or b not in nodes:
        log.warning("dropping %s edge %s->%s: %s not in the graph", line, a, b,
                    a if a not in nodes else b)
        return
    if mode is not None:
        LINE_MODES[line] = mode
    adj[a].append({'to': b, 'min': minutes, 'line': line})
    adj[b].append({'to': a, 'min': minutes, 'line': line})


def mode_of_line(line):
    """The mode that actually runs `line`, or None if it was never recorded
    (e.g. 'Transfer', or a line added through a direct add_edge call that
    forgot to pass mode)."""
    return LINE_MODES.get(line)


def chain(seq, hop, mode, line):
    """Add a sequence of stations as nodes, connected in order by edges
    of the given line. Stations that already exist (e.g. an interchange
    shared by two lines) are left as-is; only new edges are added."""
    prev = None
    for s in seq:
        add_node(s['id'], s['name'], s['lat'], s['lon'], mode)
        if prev is not None:
            add_edge(prev, s['id'], hop, line, mode)
        prev = s['id']


def lines_at(node_id):
    """The lines that call at a stop, ignoring transfer edges.

    A graph query, so it lives with the graph. routing.py and
    tools/build_schedule.py both had their own copy -- identical apart from
    quote style -- and both need it to answer the same question: which
    services can somebody board here.
    """
    return {edge['line'] for edge in adj[node_id] if edge['line'] != 'Transfer'}
