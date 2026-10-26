"""The browser build in docs/app/: is it current, and does its JavaScript
give the Python's answers?

tools/build_static.py already refuses to write if its checks fail, but two
things it cannot see had no guard at all.

  * Whether anybody ran it. docs/app/ is committed and served by GitHub
    Pages, so an edit to static/js/app.js that was never rebuilt for ships
    the old code to the live demo, with every test green.

  * Whether the JavaScript agrees with the Python. The build compares the
    server against a *Python transcription* of the port's boarding-wait
    rule, which is only as good as the transcription. Here the port itself
    runs, in Node, and its reach times are compared with compute_times'.
    Node is not a dependency of this project, so that half skips without
    it -- GitHub's runners have it, so CI does not skip.
"""

import io
import json
import os
import re
import shutil
import subprocess

import pytest

from feeds import realtime
from trips.routing import compute_times
from tools import build_static

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "docs", "app")

# Places that exercise different parts of the graph: downtown, where the
# subway and streetcars overlap; the far north, where YRT is the way in;
# Mississauga, which is MiWay and GO; and somewhere off the network entirely,
# where every time is a long walk plus a wait.
ORIGINS = [(43.6453, -79.3806), (43.8517, -79.4265), (43.5930, -79.6420),
           (44.2000, -79.0000)]


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def test_docs_app_is_what_the_build_would_write_now():
    _graph, written = build_static.render()
    stale = sorted(name for name, body in written.items()
                   if not os.path.exists(os.path.join(APP, name))
                   or read(os.path.join(APP, name)) != body)
    assert not stale, (
        "docs/app/ is out of date with its sources -- run "
        "`python tools/build_static.py`: %s" % stale)


def node_executable():
    found = shutil.which("node")
    if found:
        return found
    try:
        import nodejs_wheel
    except ImportError:
        return None
    here = os.path.dirname(nodejs_wheel.__file__)
    for candidate in ("node.exe", os.path.join("bin", "node")):
        if os.path.exists(os.path.join(here, candidate)):
            return os.path.join(here, candidate)
    return None


def run_node(tmp_path, script):
    node = node_executable()
    if node is None:
        pytest.skip("Node is not installed")
    path = tmp_path / "probe.js"
    path.write_text(script, encoding="utf-8")
    done = subprocess.run([node, str(path)], capture_output=True, text=True,
                          timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_javascript_reach_search_gives_the_pythons_times(tmp_path):
    script = (read(os.path.join(APP, "js", "network-data.js"))
              + read(os.path.join(APP, "js", "static-reach.js"))
              + "\nconsole.log(JSON.stringify(%s.map(o => "
                "StaticReach.computeTimes(o[0], o[1]))));\n"
              % json.dumps(ORIGINS))
    in_js = run_node(tmp_path, script)

    static = realtime.Conditions.static()
    for origin, js_times in zip(ORIGINS, in_js):
        py_times = compute_times(*origin, conditions=static)
        assert set(js_times) == set(py_times)
        worst = max(abs(js_times[nid] - py_times[nid]) for nid in py_times)
        assert worst < 1e-9, (origin, worst)


def test_the_departure_field_is_seeded_with_torontos_clock(tmp_path):
    """when.js seeded "Leave at..." from the browser's own clock, and the
    server reads that field as Toronto time. From a browser in London that
    was a departure five hours ahead of the one meant. Midnight is in the
    list because an h24 hour cycle writes it as 24:00, which the server
    rejects."""
    source = read(os.path.join(ROOT, "static", "js", "when.js"))
    functions = "\n".join(
        re.search(r"^function %s\(.*?^\}" % name, source,
                  re.MULTILINE | re.DOTALL).group(0)
        for name in ("twoDigit", "torontoClock"))
    instants = ["2026-09-28T16:00:00Z",     # EDT: 12:00 in Toronto
                "2026-01-15T05:00:00Z",     # EST: midnight in Toronto
                "2026-07-01T03:59:59Z"]     # the last second of 30 June
    clocks = run_node(tmp_path, functions + "\nconsole.log(JSON.stringify(%s"
                      ".map(s => torontoClock(new Date(s)))));\n"
                      % json.dumps(instants))
    assert clocks == ["12:00:00", "00:00:00", "23:59:59"]


def test_every_name_the_page_writes_as_html_is_escaped():
    """Stop names reach the page as HTML in two ways: innerHTML templates,
    which already went through esc(), and Leaflet tooltips, which did not --
    bindTooltip() with a string sets it as markup. The names are GTFS stop
    names, from a file this repository does not write."""
    source = read(os.path.join(ROOT, "static", "js", "app.js"))
    interpolated = re.findall(r"\$\{([^{}]*\.name\b[^{}]*)\}", source)
    assert interpolated, "no name interpolation found, so this check is vacuous"
    raw = [expr for expr in interpolated if not expr.startswith("esc(")]
    assert not raw, "names interpolated into markup unescaped: %r" % raw


# Just enough browser for the page scripts to load in Node: every element is
# a record of what was written to it and which listeners it was given, and
# everything else (Leaflet, the map) accepts any call and returns more of
# itself. fetch() is held open until the test answers it, in whatever order.
PAGE_STUBS = r"""
const anything = () => new Proxy(function () {}, {
  get: (t, k) => k === Symbol.toPrimitive ? () => '' : k === 'then' ? undefined : anything(),
  apply: () => anything(),
  set: () => true,
});
const elements = {};
function element(id) {
  if (elements[id]) return elements[id];
  const store = { id, on: {}, innerHTML: '', textContent: '', title: '', style: {}, value: '' };
  return elements[id] = new Proxy(store, {
    get: (t, k) => k in t ? t[k]
      : k === 'addEventListener' ? (type, fn) => { t.on[type] = fn; } : anything(),
    set: (t, k, v) => { t[k] = v; return true; },
  });
}
globalThis.window = globalThis;
globalThis.document = { getElementById: element, querySelector: () => null,
                        querySelectorAll: () => [], documentElement: {} };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.L = anything();
globalThis.setInterval = () => 0;
const pending = [];
globalThis.fetch = (url, opts) => new Promise((resolve, reject) =>
  pending.push({ url, resolve, reject }));
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
"""


def test_only_the_latest_trip_plan_is_drawn(tmp_path):
    """Two /api/trips requests can be in flight at once -- the minute timer
    replanning "leave now" while somebody picks a new destination -- and the
    older answer, arriving second, replaced the trip just asked for. "New
    trip" left `lastTrip` set, so the timer kept replanning the old trip and
    drew its route over the map while the next origin was being chosen. And
    a request that failed outright was an unhandled rejection that left the
    previous trip's options on screen."""
    source = read(os.path.join(ROOT, "static", "js", "app.js"))
    probe = PAGE_STUBS + source + r"""
const option = (arrive) => ({ departAt: '17:00:00', arriveAt: arrive, totalMinutes: 30,
  lines: ['Line 1'], transfers: 0, legs: [], laterDepartures: [], waitSources: [] });
const answer = (request, options) =>
  request.resolve({ ok: true, json: async () => ({ options, live: false }) });
const trips = () => pending.filter((p) => p.url === '/api/trips');
(async () => {
  const out = {};
  lastTrip = { olat: 43.6, olon: -79.4, dlat: 43.7, dlon: -79.4 };
  const first = planTrip();
  lastTrip = { olat: 43.6, olon: -79.4, dlat: 43.8, dlon: -79.3 };
  const second = planTrip();
  answer(trips()[1], [option('17:30:00')]);
  await second;
  answer(trips()[0], [option('18:45:00')]);
  await first;
  out.shown = tripOptions.map((o) => o.arriveAt);

  element('newTripBtn').on.click();
  out.tripAfterNewTrip = lastTrip;

  lastTrip = { olat: 43.6, olon: -79.4, dlat: 43.7, dlon: -79.4 };
  const failing = planTrip();
  trips()[2].reject(new TypeError('Failed to fetch'));
  await failing;
  out.optionsAfterFailure = tripOptions.length;
  out.noteAfterFailure = element('optionList').innerHTML;
  console.log(JSON.stringify(out));
})();
"""
    out = run_node(tmp_path, probe)
    assert out["shown"] == ["17:30:00"], "the older answer replaced the newer"
    assert out["tripAfterNewTrip"] is None, "the minute timer would replan it"
    assert out["optionsAfterFailure"] == 0
    assert "did not answer" in out["noteAfterFailure"]


def test_a_working_compass_does_not_ask_to_be_recalibrated(tmp_path):
    """Android Chrome fires deviceorientationabsolute and, beside it, a
    relative deviceorientation. The relative one replaced the location note
    with "recalibrate the magnetometer" many times a second, on a compass
    whose absolute bearing was arriving fine."""
    source = read(os.path.join(ROOT, "static", "js", "here.js"))
    probe = PAGE_STUBS + source + r"""
hereHint('Located to 5 m.');
onOrientation({ absolute: true, alpha: 90 });
onOrientation({ absolute: false, alpha: 10 });
const afterBoth = element('hereHint').innerHTML;
compassLive = false;
onOrientation({ absolute: false, alpha: 10 });
console.log(JSON.stringify({ afterBoth, live: compassLive,
                             relativeOnly: element('hereHint').innerHTML }));
"""
    out = run_node(tmp_path, probe)
    assert out["afterBoth"] == "Located to 5 m."
    assert "relative angle" in out["relativeOnly"], (
        "with no true bearing at all the advice is still owed")


# ---------------------------------------------------------------------------
# The build's own refusals, and the command itself
# ---------------------------------------------------------------------------
# Every check in build_static.py exists to stop the browser build quietly
# disagreeing with the server, and a check that never fires is a check
# nobody has seen work. Each is tripped here by breaking the one thing it
# guards. The command writes into tmp_path, never docs/app/.

def template():
    return read(os.path.join(ROOT, "templates", "index.html"))


def test_the_build_writes_lf_files_into_directories_it_creates(tmp_path):
    path = tmp_path / "deep" / "er" / "page.js"
    build_static.write(str(path), "one\ntwo\n")
    assert path.read_bytes() == b"one\ntwo\n"


def test_an_anchor_the_template_no_longer_has_stops_the_build():
    with pytest.raises(SystemExit, match="could not relabel the heading -- expected "
                                         "exactly one match .* found 0"):
        build_static.replace_once("<h1>Moved</h1>", "<h1>Old</h1>", "", "relabel the heading")
    with pytest.raises(SystemExit, match="found 2"):
        build_static.replace_once("ab ab", "ab", "", "dedupe")


def test_a_mode_with_no_modelled_wait_stops_the_build(monkeypatch):
    import network
    waits = {mode: wait for mode, wait in network.WAIT_BY_MODE.items() if mode != "bus"}
    monkeypatch.setattr(network, "WAIT_BY_MODE", waits)
    with pytest.raises(SystemExit, match="no modelled wait for bus"):
        build_static.collect_graph()


def test_a_line_with_no_recorded_mode_stops_the_build(monkeypatch):
    import network
    monkeypatch.setattr(network, "mode_of_line",
                        lambda line: None if line == "Line 1 (Yonge-University)" else "x")
    with pytest.raises(SystemExit, match=r"no recorded mode.*: Line 1 \(Yonge-University\)$"):
        build_static.collect_graph()


def test_a_static_model_that_closes_a_line_stops_the_build(monkeypatch):
    """The port skips closure handling because the static model never
    closes anything. The day it does, the port is wrong."""
    class Closing:
        def impact_on(self, line):
            return None if line == "Line 2 (Bloor-Danforth)" else 0.0

    monkeypatch.setattr(realtime.Conditions, "static", classmethod(lambda cls: Closing()))
    with pytest.raises(SystemExit, match=r"prices or closes \['Line 2 \(Bloor-Danforth\)'\]"):
        build_static.collect_graph()


def test_a_ported_wait_that_disagrees_with_the_server_stops_the_build():
    class Server:
        def boarding_wait(self, lines, mode):
            return (4.0 if lines == {"Line 1"} else 99.0), False

    nodes = {"union": {"mode": "subway"}, "spadina": {"mode": "streetcar"}}
    lines = {"union": {"Line 1"}, "spadina": {"510 Spadina", "Line 1"}}
    with pytest.raises(SystemExit) as stopped:
        build_static.check_boarding_waits(
            nodes, {}, Server(), lines.get, {"Line 1": "subway"},
            {"subway": 4.0, "streetcar": 5.0}, 6.0)
    assert "spadina: port says 4.0, realtime says 99.0" in str(stopped.value)
    assert "union" not in str(stopped.value)


def test_jinja_left_in_the_page_stops_the_build():
    with pytest.raises(SystemExit, match=r"unresolved Jinja left in the page: \['\{\{ csrf \}\}'\]"):
        build_static.page(template() + "{{ csrf }}")


def test_a_trip_card_after_the_filter_card_stops_the_build():
    text = ('      <div class="section" id="filterCard">\n'
            '      <div class="section" id="tripCard" style="display:none;">\n')
    with pytest.raises(SystemExit, match="could not find the trip card"):
        build_static.trip_card(text)


def test_the_command_writes_the_build_and_removes_what_it_no_longer_makes(
        tmp_path, monkeypatch, capsys):
    out = tmp_path / "app"
    (out / "js").mkdir(parents=True)
    (out / "js" / "renamed-last-time.js").write_text("old", encoding="utf-8")
    monkeypatch.setattr(build_static, "OUT", str(out))

    build_static.main()

    _graph, written = build_static.render()
    for name, body in written.items():
        assert read(str(out / name)) == body, name
    assert not (out / "js" / "renamed-last-time.js").exists()
    log = capsys.readouterr().out
    assert "removed stale js%srenamed-last-time.js" % os.sep in log
    assert "516 stops" in log
    assert "wrote %d files to docs/app" % len(written) in log
