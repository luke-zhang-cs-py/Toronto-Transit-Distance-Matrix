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
