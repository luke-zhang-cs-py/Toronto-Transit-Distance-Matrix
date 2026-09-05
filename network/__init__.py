"""
The `network` package is the transit graph, split by feature:

    graph.py       core add_node / add_edge / chain primitives + nodes/adj
    subway.py      TTC Line 1 + Line 2, including their outer extensions
    streetcars.py  downtown streetcar grid + subway<->streetcar transfers
    regional.py    YRT/Viva, MiWay, and the highway-corridor hubs

Build order matters: streetcars.build() adds transfer edges that assume
subway stations already exist, and regional.build() connects onto both
subway stations (union, kipling, finch, vaughanmc) and streetcar nodes.
Importing this package runs that build once; every other module in the
app just imports `nodes` and `adj` from here.
"""

from .graph import nodes, adj, WALK_KMH, WAIT_BY_MODE, DEFAULT_WAIT_MIN
from . import subway, streetcars, regional

subway.build()
streetcars.build()
regional.build()

__all__ = ['nodes', 'adj', 'WALK_KMH', 'WAIT_BY_MODE', 'DEFAULT_WAIT_MIN']
