/* ---------------------------------------------------------------------------
   static-api.js — the four endpoints, answered in the page
   ---------------------------------------------------------------------------
   app.js talks to the server in exactly four places: `/api/live`,
   `/api/network`, `/api/reach` and `/api/trips`. This intercepts those four
   and answers them here, so the *same* app.js runs in both builds.

   A fetch shim rather than a forked app.js. The alternative — a second copy
   of the 486-line file with its fetch calls edited out — is a fork that
   looks like a copy, and it rots the first time somebody fixes a bug in one
   of them. Everything under docs/app/js/ that is shared is copied byte for
   byte by tools/build_static.py; this file is the only thing standing
   between it and a server.

   Loaded *before* app.js, because app.js calls loadNetwork() and
   loadLiveStatus() as it finishes.
   --------------------------------------------------------------------------- */

(function () {
  'use strict';

  const REPO = 'https://github.com/luke-zhang-cs-py/Toronto-Transit-Distance-Matrix';

  /* Enough of a Response for the four call sites: `.ok`, `.status`, `.json()`.
     Not a real Response object — constructing one is possible, but then the
     shim would be claiming to be the platform's fetch rather than a stand-in
     for four known callers, and the first thing to use a fifth feature of it
     would fail somewhere far from here. */
  function reply(status, body) {
    return Promise.resolve({
      ok: status >= 200 && status < 300,
      status: status,
      statusText: status === 200 ? 'OK' : 'Static build',
      json: function () { return Promise.resolve(body); },
      text: function () { return Promise.resolve(JSON.stringify(body)); },
    });
  }

  /* app.py's _coord, narrowed to what this build can be handed: the page
     only ever passes a Leaflet click, but a NaN reaching the search turns
     every distance into NaN and the map goes blank with no error. */
  function coord(body, key, low, high) {
    if (!body || typeof body !== 'object') throw new Error('Body must be a JSON object.');
    if (!(key in body)) throw new Error("'" + key + "' is required.");
    const value = Number(body[key]);
    if (!Number.isFinite(value)) throw new Error("'" + key + "' must be a finite number.");
    if (value < low || value > high) {
      throw new Error("'" + key + "' must be between " + low + " and " + high + '.');
    }
    return value;
  }

  function parseBody(init) {
    if (!init || init.body == null) return {};
    try { return JSON.parse(init.body); } catch (e) { return null; }
  }

  /* ------------------------------------------------------------ /api/live */
  /* Honest about being nothing. The server's /api/live reports feed age,
     closures and how many routes have a measured headway; none of those
     exist here, and inventing plausible-looking values for them would make
     the page claim a freshness it does not have. So: `live: false`, zero
     coverage, and a note saying why. app.js renders that as "scheduled"; the
     static build's own script relabels it "modelled", which is the more
     precise word for what this is. */
  const LIVE = {
    live: false,
    static: true,
    note: 'Browser-only build: no GTFS-realtime feed. Every wait is the ' +
          'modelled half-headway for the line\'s mode (network/graph.py ' +
          'WAIT_BY_MODE), which is what the Flask app serves when a request ' +
          'sets "live": false. Run the Flask app for live waits and closures.',
    source: REPO,
    feedTimestamp: null,
    ageSeconds: null,
    routesWithObservedHeadway: 0,
    closed: [],
    detour: [],
    notes: [],
    schedule: null,
  };

  const ROUTES = {
    '/api/network': function () {
      return reply(200, StaticReach.networkPayload());
    },

    '/api/live': function () {
      return reply(200, LIVE);
    },

    '/api/reach': function (init) {
      const body = parseBody(init);
      let lat, lon;
      try {
        lat = coord(body, 'lat', -90, 90);
        lon = coord(body, 'lon', -180, 180);
      } catch (err) {
        return reply(400, { error: err.message });
      }
      const times = StaticReach.computeTimes(lat, lon);
      const out = {};
      /* One decimal, as app.py rounds it, so the tooltips read the same in
         both builds. */
      for (const nid of Object.keys(times)) out[nid] = Math.round(times[nid] * 10) / 10;
      return reply(200, { times: out, live: false });
    },

    /* --------------------------------------------------------- /api/trips */
    /* Not ported, on purpose. itinerary.py is 576 lines over a 0.6 MB
       timetable index built from TTC's static GTFS, and it answers "what
       time do I arrive", which is a claim that is either right or worthless.
       A partial port would print departures nobody can catch, and a wrong
       clock time is worse than no clock time — the reader has no way to tell
       it is wrong. So the trip planner is switched off in this build and
       says so, rather than being approximated.

       This still returns a real error rather than an empty option list: a
       planner that says "no trip found" for a trip that plainly exists is
       the same lie in a quieter voice. */
    '/api/trips': function () {
      return reply(501, {
        error: 'Trip planning needs the local Flask app — see the README.',
        why: 'itinerary.py plans against a timetable index that is not part ' +
             'of this bundle, and an approximation of an arrival time is not ' +
             'an arrival time.',
        source: REPO,
      });
    },
  };

  const realFetch = typeof window.fetch === 'function' ? window.fetch.bind(window) : null;

  window.fetch = function (input, init) {
    const url = String(typeof input === 'string' ? input : (input && input.url) || '');
    const handler = ROUTES[url.split('?')[0]];
    if (handler) return handler(init || {});
    if (realFetch) return realFetch(input, init);
    return Promise.reject(new Error('no fetch available for ' + url));
  };

  window.StaticBuild = { live: LIVE, repo: REPO };
})();
