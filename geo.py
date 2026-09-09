"""
geo.py
-------
Great-circle distance, in one place.

There were three copies of this: `routing.haversine_km`, and a `metres`
function in each of the two GTFS build tools, byte-identical to each other.
Three copies of eleven lines of trigonometry is not expensive, but it is
three places to fix if the earth's radius or the formula ever needs a
second look -- and it was already drifting, since the build tools returned
metres and routing returned kilometres with no shared definition saying so.

Both units are here because both are the natural one somewhere: a walk is
minutes over kilometres, and a stop-matching tolerance is metres.
"""

import math

# Mean earth radius. The WGS-84 equatorial radius is 6378 km and the polar
# 6357; this is the usual spherical compromise, and at Toronto's latitudes
# the error against a true ellipsoidal distance is well under a metre per
# kilometre -- far below the precision of anything here.
EARTH_RADIUS_KM = 6371.0
EARTH_RADIUS_M = EARTH_RADIUS_KM * 1000.0


def km(lat1, lon1, lat2, lon2):
    """Straight-line distance in kilometres."""
    return _haversine(lat1, lon1, lat2, lon2) * EARTH_RADIUS_KM


def metres(lat1, lon1, lat2, lon2):
    """Straight-line distance in metres."""
    return _haversine(lat1, lon1, lat2, lon2) * EARTH_RADIUS_M


def _haversine(lat1, lon1, lat2, lon2):
    """The central angle between two points, in radians.

    Split out from the two wrappers so the formula appears once and the unit
    is the only thing that differs between them.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return 2 * math.asin(math.sqrt(a))
