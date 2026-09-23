/* ---------------------------------------------------------------------------
   static-reach.js — the reachability search, in the browser
   ---------------------------------------------------------------------------
   A port of `routing.compute_times` for the build that has no Python behind
   it. It is deliberately a *narrow* port: only the reachability Dijkstra,
   only under the fixed schedule model — the same thing the server does when
   a request carries `{"live": false}`, which is also what the test suite
   routes against.

   Nothing here fetches a live feed, because there is nothing to fetch it
   with: GTFS-realtime is protobuf over a host that sends no CORS headers, so
   a page on GitHub Pages cannot read it. Rather than quietly serving assumed
   numbers under a "live" label, this build only ever claims `modelled`.

   What the Python does, and therefore what this does:

     * every stop starts at "walk there from the origin, then wait for the
       first vehicle" — `walk_minutes(haversine) + boarding_wait`;
     * `boarding_wait` is the *smallest* wait among the lines calling at the
       stop, because you board whatever turns up first, floored by the node's
       own modelled wait (realtime.Conditions.boarding_wait seeds `best` with
       it before looking at any line);
     * a line's wait comes from the mode that *runs the line* — LINE_MODES —
       and not from the mode tag the node happens to carry. Union is a
       `subway` node and a GO train boarded there is still a 20-minute wait,
       not a 4-minute one. That distinction was a real bug on the server
       (fixed in 484058d); reintroducing it here would make the browser build
       disagree with the Python for every interchange;
     * under the static model `realtime.impact_on` returns 0.0 for every
       line and never None, so no edge is dropped and no edge is surcharged.
       That is asserted by the build script rather than assumed here.

   Exposed as one object rather than loose globals: app.js already owns a
   `NETWORK`, and a classic script that drops another dozen names into the
   global scope beside it is one rename away from clobbering something.
   --------------------------------------------------------------------------- */

const StaticReach = (function () {
  'use strict';

  const D = NETWORK_DATA;
  const NODES = D.nodes;                 /* id -> {name, lat, lon, mode}      */
  const ADJ = D.adj;                     /* id -> [[to, minutes, line], ...]  */
  const TO = 0, MIN = 1, LINE = 2;       /* the compact edge layout           */

  /* ------------------------------------------------------------------ geo */
  /* geo.py, transcribed. Written the same way round as the Python — radians
     first, then one haversine, then one radius multiply — so the two can be
     read side by side. The constant is geo.EARTH_RADIUS_KM. */
  const EARTH_RADIUS_KM = 6371.0;
  const RAD = Math.PI / 180;

  function haversineKm(lat1, lon1, lat2, lon2) {
    const phi1 = lat1 * RAD, phi2 = lat2 * RAD;
    const dphi = (lat2 - lat1) * RAD;
    const dlambda = (lon2 - lon1) * RAD;
    const a = Math.sin(dphi / 2) ** 2 +
              Math.cos(phi1) * Math.cos(phi2) * Math.sin(dlambda / 2) ** 2;
    return 2 * Math.asin(Math.sqrt(a)) * EARTH_RADIUS_KM;
  }

  function walkMinutes(km) {
    return km / D.walkKmh * 60;
  }

  /* ---------------------------------------------------------------- waits */
  /* network.graph.lines_at: what you can board here, transfers excluded —
     a transfer edge is a walk between platforms, not a service. */
  function linesAt(nid) {
    const out = new Set();
    for (const edge of ADJ[nid] || []) {
      if (edge[LINE] !== 'Transfer') out.add(edge[LINE]);
    }
    return out;
  }

  function modelledWait(mode) {
    const value = D.waitByMode[mode];
    return value === undefined ? D.defaultWaitMin : value;
  }

  /* realtime.Conditions.boarding_wait, with an empty headway table.
     `best` is seeded from the node's own mode and only ever lowered, which
     is the Python's behaviour and not the same as a plain min over the
     lines: a GO-only platform tagged `subway` by whichever module built it
     first keeps the 4-minute floor on the server too. */
  function boardingWait(nid) {
    const nodeMode = NODES[nid].mode;
    let best = modelledWait(nodeMode);
    for (const line of linesAt(nid)) {
      const lineMode = D.lineModes[line] || nodeMode;
      const value = modelledWait(lineMode);
      if (value < best) best = value;
    }
    return best;
  }

  /* Origin-independent, so computed once for the whole session rather than
     516 times per click. */
  let waits = null;
  function boardingWaits() {
    if (waits) return waits;
    waits = Object.create(null);
    for (const nid of Object.keys(NODES)) waits[nid] = boardingWait(nid);
    return waits;
  }

  /* ----------------------------------------------------------------- heap */
  /* A binary heap ordered exactly as Python's `heapq` orders the tuples
     `(minutes, node_id)`: by time, then by id. The tie-break does not change
     any distance — every weight is positive — but matching it keeps the two
     searches settling nodes in the same order, which is what makes a
     disagreement between them mean something. */
  function Heap() { this.items = []; }

  Heap.prototype.size = function () { return this.items.length; };

  Heap.prototype.less = function (a, b) {
    if (a[0] !== b[0]) return a[0] < b[0];
    return a[1] < b[1];
  };

  Heap.prototype.push = function (t, id) {
    const items = this.items;
    items.push([t, id]);
    let i = items.length - 1;
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (!this.less(items[i], items[parent])) break;
      const swap = items[i]; items[i] = items[parent]; items[parent] = swap;
      i = parent;
    }
  };

  Heap.prototype.pop = function () {
    const items = this.items;
    const top = items[0];
    const last = items.pop();
    if (items.length) {
      items[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1, r = l + 1;
        let small = i;
        if (l < items.length && this.less(items[l], items[small])) small = l;
        if (r < items.length && this.less(items[r], items[small])) small = r;
        if (small === i) break;
        const swap = items[i]; items[i] = items[small]; items[small] = swap;
        i = small;
      }
    }
    return top;
  };

  /* ------------------------------------------------------------- dijkstra */
  /* routing.compute_times(olat, olon) with conditions = Conditions.static().
     `with_paths` is not ported: nothing in this build reconstructs a path,
     and a predecessor map nobody reads is a second thing to keep correct. */
  function computeTimes(olat, olon) {
    const wait = boardingWaits();
    const time = Object.create(null);
    const ids = Object.keys(NODES);

    for (const nid of ids) {
      const n = NODES[nid];
      time[nid] = walkMinutes(haversineKm(olat, olon, n.lat, n.lon)) + wait[nid];
    }

    const pq = new Heap();
    for (const nid of ids) pq.push(time[nid], nid);

    /* The same single staleness check the Python has, and for the same
       reason: a node is re-pushed whenever a cheaper way in is found, the
       cheaper entry pops first and marks it, and every superseded entry for
       it is caught here. */
    const visited = new Set();
    while (pq.size()) {
      const top = pq.pop();
      const t = top[0], u = top[1];
      if (visited.has(u)) continue;
      visited.add(u);
      for (const edge of ADJ[u] || []) {
        /* conditions.impact_on(line) is 0.0 for every line under the static
           model, so there is no closure to route around and nothing to
           surcharge. tools/build_static.py checks that before writing the
           bundle; if the model ever grows static closures this loop is
           where they would go. */
        const v = edge[TO];
        const nt = t + edge[MIN];
        if (nt < time[v]) {
          time[v] = nt;
          pq.push(nt, v);
        }
      }
    }
    return time;
  }

  /* ------------------------------------------------- the /api/network body */
  /* app.py's api_network, to the letter: one entry per undirected (pair,
     line), first direction seen wins. Derived here rather than shipped
     twice — the adjacency already holds it, and two copies of the same
     edge list in one bundle is two things to keep in step. */
  let payload = null;
  function networkPayload() {
    if (payload) return payload;
    const seen = new Set();
    const edges = [];
    for (const a of Object.keys(ADJ)) {
      for (const edge of ADJ[a]) {
        const b = edge[TO];
        const pair = a < b ? a + '\u0000' + b : b + '\u0000' + a;
        const key = pair + '\u0000' + edge[LINE];
        if (seen.has(key)) continue;
        seen.add(key);
        edges.push([a, b, edge[MIN], edge[LINE]]);
      }
    }
    payload = { nodes: NODES, edges: edges };
    return payload;
  }

  return {
    computeTimes: computeTimes,
    networkPayload: networkPayload,
    boardingWait: boardingWait,
    haversineKm: haversineKm,
    walkMinutes: walkMinutes,
  };
})();
