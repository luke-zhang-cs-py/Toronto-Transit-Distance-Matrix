"""
itinerary.py
-------------
Trips for a departure time, with clock times, and several of them.

`routing.py` answers "how long does this take", as a duration, from a graph
with fixed weights. That is the right question for the reach map and the
wrong one for a trip: leaving at 17:20 on a Tuesday is not the same journey
as leaving at 02:20, and a duration cannot say what time you arrive.

Two things change here.

The state includes the line you are on
--------------------------------------
routing.py charges a boarding wait once, at the origin, and never again.
Its Transfer edges cost a flat three minutes -- the walk between platforms --
with no wait for the next vehicle, so a trip with two changes undercounted
by two waits. That is not a rounding error: two missing five-minute waits on
a forty-minute trip is a quarter of it.

Fixing it means the search state cannot just be "which stop". Staying on a
train through a station is free; arriving at the same station and changing
lines is not. So a state is (stop, line you are currently riding), and a
wait is charged exactly when the line changes -- which is what boarding is.

The clock is part of the cost
-----------------------------
With a departure time, the wait at each boarding is the gap until the next
scheduled departure, from schedule.py, not an average. Dijkstra still
applies: transit is FIFO -- leaving later cannot get you there earlier --
so a frontier ordered by arrival time is still explored in the right order.

Waits fall back in three steps, and every leg says which it got:
    timetable  the next scheduled departure  (schedule.py)
    headway    half the observed gap         (realtime.py)
    modelled   half the assumed headway      (WAIT_BY_MODE)

Alternatives
------------
Two kinds, because "another option" means two different things.

*Different routings* -- the same departure by another way round. Found by
banning the line the best trip leaned on hardest and searching again, which
is the cheap and honest version of k-shortest-paths: it yields routes that
differ in the decision that matters rather than in one stop.

*Later departures* -- the same routing on the next few vehicles, which is
what somebody actually wants when they are deciding whether to hurry.
"""

import datetime as dt
import heapq

import realtime
import schedule
from network import adj, nodes
from routing import haversine_km, path_km, walk_minutes

# How far somebody will walk to reach the network, and to leave it.
#
# Both ends need a cap. Without one at the far end, a search whose useful
# lines have been banned still "succeeds": it rides partway and then walks
# for two and a half hours, and reports that as an option. A 155-minute walk
# is not a leg of a journey, it is the search admitting it failed.
MAX_ACCESS_WALK_MIN = 25.0
MAX_EGRESS_WALK_MIN = 25.0

# An alternative has to be a real alternative. Anything this much worse than
# the best trip is not another way to go, it is a worse way to go, and
# offering it as a choice wastes the reader's attention.
ALTERNATIVE_TOLERANCE = 1.6
ALTERNATIVE_SLACK_MIN = 12.0

# How many alternative routings to look for beyond the best one.
DEFAULT_ALTERNATIVES = 2

# How many later departures to offer for a routing.
DEFAULT_LATER = 3

TRANSFER_LINE = "Transfer"


class Leg:
    """One continuous part of a trip: a walk, a wait, or a ride."""

    def __init__(self, kind, minutes, **extra):
        self.kind = kind
        self.minutes = minutes
        self.extra = extra

    def as_dict(self, start, end):
        out = {"type": self.kind,
               "minutes": round(self.minutes, 1),
               "startTime": start.strftime("%H:%M"),
               "endTime": end.strftime("%H:%M")}
        out.update(self.extra)
        return out


def _wait_for(node_id, line, moment, conditions):
    """(minutes, source) until the next vehicle on `line` at `node_id`.

    Three sources in order of what they actually know. The source travels
    with the number so a leg can say "17:22, timetabled" rather than
    presenting an assumption in the same typeface as a measurement.
    """
    timetabled = schedule.wait_minutes(node_id, line, moment)
    if timetabled is not None:
        return timetabled, "timetable"

    mode = nodes[node_id]["mode"]
    minutes, measured = conditions.wait_for(line, mode)
    return minutes, "headway" if measured else "modelled"


def _access_nodes(lat, lon):
    """Nodes worth walking to from a point, with the walk in minutes."""
    reachable = []
    for node_id, node in nodes.items():
        walk = walk_minutes(haversine_km(lat, lon, node["lat"], node["lon"]))
        if walk <= MAX_ACCESS_WALK_MIN:
            reachable.append((node_id, walk))
    if reachable:
        return reachable
    # Nothing within the cap: offer the single nearest, so a request from far
    # outside the network gets a long walk rather than no answer.
    nearest = min(nodes, key=lambda n: haversine_km(lat, lon, nodes[n]["lat"],
                                                    nodes[n]["lon"]))
    return [(nearest, walk_minutes(haversine_km(lat, lon, nodes[nearest]["lat"],
                                                nodes[nearest]["lon"])))]


def _search(origin, destination, depart_at, conditions, banned_lines=frozenset()):
    """Earliest arrival, as a chain of (node, line, clock) steps.

    Returns (arrival_datetime, steps) or (None, None). `steps` is the
    reconstructed path: a list of (node_id, line_boarded_or_None, arrival).
    """
    olat, olon = origin
    dlat, dlon = destination

    # state -> (arrival datetime, previous state, line taken to get here,
    #           wait minutes paid on boarding, wait source)
    best = {}
    frontier = []

    for node_id, walk in _access_nodes(olat, olon):
        arrival = depart_at + dt.timedelta(minutes=walk)
        state = (node_id, None)
        if state not in best or arrival < best[state][0]:
            best[state] = (arrival, None, None, 0.0, None)
            heapq.heappush(frontier, (arrival, node_id, None))

    settled = set()
    while frontier:
        arrival, node_id, on_line = heapq.heappop(frontier)
        state = (node_id, on_line)
        if state in settled or arrival > best[state][0]:
            continue
        settled.add(state)

        for edge in adj[node_id]:
            line = edge["line"]
            if line in banned_lines:
                continue
            impact = conditions.impact_on(line)
            if impact is None:
                continue                      # closed: not an option at all

            if line == TRANSFER_LINE:
                # A walk between platforms. It ends you off any vehicle, so
                # the next ride pays a boarding wait -- which is the whole
                # point of tracking the line in the state.
                cost, wait, source, next_line = edge["min"], 0.0, None, None
            elif on_line == line:
                cost, wait, source, next_line = edge["min"] + impact, 0.0, None, line
            else:
                wait, source = _wait_for(node_id, line, arrival, conditions)
                cost, next_line = wait + edge["min"] + impact, line

            reached = arrival + dt.timedelta(minutes=cost)
            target = (edge["to"], next_line)
            if target not in best or reached < best[target][0]:
                best[target] = (reached, state, line, wait, source)
                heapq.heappush(frontier, (reached, edge["to"], next_line))

    # Finish by walking from wherever we got to.
    finish, final_state = None, None
    for (node_id, on_line), entry in best.items():
        walk = walk_minutes(haversine_km(nodes[node_id]["lat"], nodes[node_id]["lon"],
                                         dlat, dlon))
        if walk > MAX_EGRESS_WALK_MIN:
            continue                          # too far to be the end of a trip
        landed = entry[0] + dt.timedelta(minutes=walk)
        if finish is None or landed < finish:
            finish, final_state = landed, (node_id, on_line)

    if final_state is None:
        return None, None

    chain = []
    state = final_state
    while state is not None:
        arrival, previous, line, wait, source = best[state]
        chain.append((state[0], line, arrival, wait, source))
        state = previous
    chain.reverse()
    return finish, chain


def _to_legs(chain, origin, destination, depart_at, arrival):
    """The step chain as walk / wait / ride legs with clock times."""
    olat, olon = origin
    dlat, dlon = destination
    legs = []

    first_node = nodes[chain[0][0]]
    access_km = haversine_km(olat, olon, first_node["lat"], first_node["lon"])
    clock = depart_at
    if access_km > 0.01:
        minutes = walk_minutes(access_km)
        end = clock + dt.timedelta(minutes=minutes)
        legs.append((Leg("walk", minutes, km=round(access_km, 2),
                         **{"from": {"name": "Start", "lat": olat, "lon": olon},
                            "to": {"name": first_node["name"],
                                   "lat": first_node["lat"], "lon": first_node["lon"]}}),
                     clock, end))
        clock = end

    # Runs of the same line collapse into one ride, with its wait in front.
    index = 1
    while index < len(chain):
        node_id, line, reached, wait, source = chain[index]
        if line == TRANSFER_LINE:              # a walk between platforms
            previous = nodes[chain[index - 1][0]]
            here = nodes[node_id]
            minutes = (reached - clock).total_seconds() / 60.0
            end = clock + dt.timedelta(minutes=minutes)
            legs.append((Leg("transfer", minutes,
                             km=round(haversine_km(previous["lat"], previous["lon"],
                                                   here["lat"], here["lon"]), 2),
                             **{"from": {"name": previous["name"]},
                                "to": {"name": here["name"]}}), clock, end))
            clock = end
            index += 1
            continue

        start_node = nodes[chain[index - 1][0]]
        if wait and wait > 0:
            end = clock + dt.timedelta(minutes=wait)
            legs.append((Leg("wait", wait, line=line, source=source,
                             boardAt=end.strftime("%H:%M"),
                             **{"at": {"name": start_node["name"]}}), clock, end))
            clock = end

        run_start = index - 1
        while (index < len(chain) and chain[index][1] == line):
            index += 1
        end_node_id = chain[index - 1][0]
        ride_minutes = (chain[index - 1][2] - clock).total_seconds() / 60.0
        end = clock + dt.timedelta(minutes=max(0.0, ride_minutes))
        path = [nodes[step[0]] for step in chain[run_start:index]]
        legs.append((Leg("transit", max(0.0, ride_minutes), line=line,
                         km=round(path_km(path), 2),
                         stops=max(0, index - 1 - run_start),
                         **{"from": {"name": start_node["name"],
                                     "lat": start_node["lat"], "lon": start_node["lon"]},
                            "to": {"name": nodes[end_node_id]["name"],
                                   "lat": nodes[end_node_id]["lat"],
                                   "lon": nodes[end_node_id]["lon"]}}), clock, end))
        clock = end

    last_node = nodes[chain[-1][0]]
    egress_km = haversine_km(last_node["lat"], last_node["lon"], dlat, dlon)
    if egress_km > 0.01:
        minutes = walk_minutes(egress_km)
        legs.append((Leg("walk", minutes, km=round(egress_km, 2),
                         **{"from": {"name": last_node["name"],
                                     "lat": last_node["lat"], "lon": last_node["lon"]},
                            "to": {"name": "Destination", "lat": dlat, "lon": dlon}}),
                     clock, arrival))
    return [leg.as_dict(start, end) for leg, start, end in legs]


def _signature_line(legs):
    """The line a trip leans on hardest, by time aboard.

    Banning this is what makes the next search produce a genuinely different
    trip rather than the same one via one different stop.
    """
    aboard = {}
    for leg in legs:
        if leg["type"] == "transit":
            aboard[leg["line"]] = aboard.get(leg["line"], 0) + leg["minutes"]
    return max(aboard, key=aboard.get) if aboard else None


def _describe(option_legs, chain, depart_at, arrival, later):
    """One search result as the option a reader sees."""
    signature = _signature_line(option_legs)
    return {
        "departAt": depart_at.strftime("%H:%M"),
        "arriveAt": arrival.strftime("%H:%M"),
        "totalMinutes": round((arrival - depart_at).total_seconds() / 60.0, 1),
        "totalKm": round(sum(leg.get("km", 0) for leg in option_legs), 2),
        # Line changes, not platform walks. Counting only the walks reported
        # "0 transfers" for a trip that boarded three different lines,
        # because two of the changes happened at a shared stop with no walk
        # between them. What a rider counts is how many times they have to
        # get on something.
        "transfers": max(0, sum(1 for leg in option_legs
                                if leg["type"] == "transit") - 1),
        "platformWalks": sum(1 for leg in option_legs if leg["type"] == "transfer"),
        "lines": [leg["line"] for leg in option_legs if leg["type"] == "transit"],
        "via": signature,
        "waitSources": sorted({leg["source"] for leg in option_legs
                               if leg["type"] == "wait"}),
        "legs": option_legs,
        "laterDepartures": _later_departures(chain, later),
    }


def _worth_choosing_between(options):
    """Distinct trips only, and only ones worth offering.

    Banning a line can yield the same arrival by the same lines when the ban
    made no difference, and it can yield a trip so much worse that presenting
    it as a choice is misleading rather than helpful.
    """
    options = sorted(options, key=lambda o: o["totalMinutes"])
    if not options:
        return []

    best = options[0]["totalMinutes"]
    limit = max(best * ALTERNATIVE_TOLERANCE, best + ALTERNATIVE_SLACK_MIN)

    seen, unique = set(), []
    for option in options:
        if option["totalMinutes"] > limit:
            continue
        key = (option["arriveAt"], tuple(option["lines"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(option)
    return unique


def plan(origin, destination, depart_at=None, conditions=None,
         alternatives=DEFAULT_ALTERNATIVES, later=DEFAULT_LATER):
    """Several ways to make one trip, each with clock times.

    Returns {"departAt", "options": [...], "scheduleAvailable", "live"}.
    Options are ordered by how long they take: the one that gets you there
    first is first, which is not always the one that leaves first.
    """
    depart_at = depart_at or dt.datetime.now().replace(second=0, microsecond=0)
    conditions = conditions or realtime.Conditions.static()

    options, banned = [], set()
    for _attempt in range(1 + max(0, alternatives)):
        arrival, chain = _search(origin, destination, depart_at, conditions,
                                 frozenset(banned))
        if arrival is None or not chain:
            break
        legs = _to_legs(chain, origin, destination, depart_at, arrival)
        option = _describe(legs, chain, depart_at, arrival, later)
        options.append(option)
        if option["via"] is None:
            break                              # a pure walk: no line to ban
        banned.add(option["via"])

    return {
        "departAt": depart_at.strftime("%H:%M"),
        "departDate": depart_at.strftime("%Y-%m-%d"),
        "options": _worth_choosing_between(options),
        "scheduleAvailable": schedule.available(),
        "live": conditions.live,
    }


def _later_departures(chain, count):
    """The next few times you could catch this trip's first vehicle.

    Taken from the chain, which holds real datetimes, rather than from the
    rendered leg. Re-parsing the displayed "17:22" put the boundary at
    17:22:00, so the 17:22:16 train somebody was already catching came back
    as a later option -- a list of alternatives whose first entry is the
    thing you are already doing.

    Timetable only: "the next one is at 17:26" is worth saying, and "the next
    one is in about six minutes on average" is not.
    """
    if count <= 0:
        return []
    for index in range(1, len(chain)):
        _node_id, line, _reached, _wait, source = chain[index]
        if line and line != TRANSFER_LINE and source == "timetable":
            departure = _boarding_time(chain, index)
            if departure is None:
                return []
            after = departure + dt.timedelta(seconds=1)
            return [when.strftime("%H:%M")
                    for when in schedule.departures_after(chain[index - 1][0], line,
                                                          after, limit=count)]
    return []


def _boarding_time(chain, index):
    """When the vehicle reached at chain[index] actually departed.

    The chain records arrivals. A boarding happened `wait` minutes after
    arriving at the previous stop, so that is where the departure is.
    """
    previous_arrival = chain[index - 1][2]
    wait = chain[index][3] or 0.0
    return previous_arrival + dt.timedelta(minutes=wait)
