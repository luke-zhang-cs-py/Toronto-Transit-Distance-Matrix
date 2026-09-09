"""
Bus routes, generated from TTC's static GTFS by tools_build_buses.py.

The other modules in this package are hand-written station lists, which is
reasonable for two subway lines and a streetcar grid and unreasonable for
several hundred bus stops with real travel times between them. GTFS has
both, so `bus_routes.json` is generated and this loads it.

Loaded last, deliberately: the transfer edges connect generated stops to
nodes that subway.py and streetcars.py have to have created first. Without
buses, most of the city was reachable only by subway, and the reach map put
north Etobicoke forty minutes from everywhere when it has a bus every eight.

Absent is fine. If the file has not been generated the package builds
without it, and the graph is what it was before -- so a clone works before
anybody runs a build tool.
"""

import json
import logging
import os

from .graph import add_edge, add_node, chain

log = logging.getLogger(__name__)

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bus_routes.json")

# Buses run less often than the subway and are less punctual, so the wait is
# longer. This is the modelled fallback only -- routes named "<number> <name>"
# pick up live headways and timetabled departures automatically, which is why
# tools_build_buses names them that way.
BUS_WAIT_MIN = 7


def load(path=DATA):
    """Add the generated routes to the shared graph. Returns how many stops."""
    if not os.path.exists(path):
        log.info("no %s; run tools_build_buses.py to add bus routes", path)
        return 0

    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        log.warning("could not read %s: %s", path, exc)
        return 0

    added = 0
    for route in data.get("routes", []):
        stops = route.get("stops", [])
        hops = route.get("hops", [])
        if len(stops) < 2:
            continue

        # Not chain(): its single `hop` applies one time to every edge, and
        # the whole point of generating these is that the times are real and
        # differ between stops. So the nodes go in, then each edge with its
        # own scheduled minutes.
        for stop in stops:
            add_node(stop["id"], stop["name"], stop["lat"], stop["lon"], "bus")
            added += 1
        for (before, after), minutes in zip(zip(stops, stops[1:]), hops):
            add_edge(before["id"], after["id"], minutes, route["line"])

    for node_a, node_b, minutes in data.get("transfers", []):
        add_edge(node_a, node_b, minutes, "Transfer")

    return added


__all__ = ["load", "chain", "BUS_WAIT_MIN"]
