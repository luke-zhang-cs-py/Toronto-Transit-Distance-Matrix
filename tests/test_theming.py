"""The themes: every token set, every pairing AA, dark with no JavaScript,
and a toggle that remembers.

Three pages carry a theme, from two sets of tokens:

  * the app -- templates/index.html, and docs/app/index.html, which
    tools/build_static.py makes from it -- reads static/css/style.css;
  * the write-up, docs/index.html, carries the family's shared template
    block in its own <style>.

Each opens dark from a class written into <html>, and a toggle steps
through the page's THEMES list. Adding a theme is one block plus one name,
so everything here loops over THEMES rather than naming dark and light:
a third theme is checked the moment it is added.

What is checked from the source, with no browser, so it runs everywhere:

  * every theme sets the same tokens, the contract's thirteen among them;
  * every foreground/background pair the page actually uses meets WCAG AA
    in every theme -- including pairs a first-load scan never sees: the
    chosen option, a "live" or "est" tag, a hover, the browser-build banner;
  * the map is not themed: its colours sit outside the theme blocks;
  * a line badge's ink reads on its line's colour (Node, as elsewhere here).

What needs a browser (Playwright; skipped without it, installed in CI):
the page with JavaScript off, the toggle and its memory, a saved theme that
no longer exists, and a contrast scan of every visible text node in each
theme with the trip card, the reach readout or the table view open.
"""

import io
import json
import os
import re

import pytest

from test_static_build import run_node

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "templates", "index.html")
APP_CSS = os.path.join(ROOT, "static", "css", "style.css")
APP_PAGE = os.path.join(ROOT, "docs", "app", "index.html")
WRITEUP = os.path.join(ROOT, "docs", "index.html")

CONTRACT = {
    "--color-bg", "--color-surface", "--color-surface-subtle", "--color-border",
    "--color-border-strong", "--color-text-primary", "--color-text-muted",
    "--color-text-subtle", "--color-accent", "--color-accent-hover",
    "--color-accent-subtle", "--color-text-on-accent", "--color-danger",
}

TEXT, UI = 4.5, 3.0


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


# ---------------------------------------------------------------- parsing
def rules(css):
    """[(selector, {token: value})] for every rule, comments removed."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        tokens = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+?)\s*(?:;|$)", body))
        out.append((selector.strip(), tokens))
    return out


def theme_blocks(css):
    """{name: {token: value}} for every .theme-<name> block."""
    blocks = {}
    for selector, tokens in rules(css):
        for name in re.findall(r"\.theme-([a-z]+)\b", selector):
            blocks.setdefault(name, {}).update(tokens)
    return blocks


def themes_list(page):
    found = re.search(r"var THEMES = \[([^\]]*)\]", page)
    assert found, "the page has no THEMES list"
    return re.findall(r"'([a-z]+)'", found.group(1))


def writeup_css():
    return re.search(r"<style>(.*?)</style>", read(WRITEUP), re.S).group(1)


# Which tokens each page pairs, read off its rules. `fg` is a text colour
# (4.5:1) or a mark that carries meaning (3:1) and `bg` what it sits on.
APP_TEXT = (
    [(fg, bg) for fg in ("text-primary", "text-muted")
     for bg in ("bg", "surface", "surface-subtle", "surface-selected")]
    + [(fg, bg) for fg in ("accent",)
       for bg in ("bg", "surface", "surface-subtle", "surface-selected",
                  "accent-subtle", "accent-subtle-hover")]
    + [("text-subtle", "surface"), ("text-subtle", "surface-subtle"),
       ("text-subtle", "surface-selected"),          # the arrows between badges
       ("text-muted", "notice-subtle"), ("text-primary", "notice-subtle"),
       ("accent", "notice-subtle"), ("accent-hover", "notice-subtle"),
       ("accent-hover", "surface"),                  # the browser-build banner and note
       ("success", "success-subtle"), ("warning", "warning-subtle"),
       ("neutral", "neutral-subtle"), ("neutral", "surface"),   # tags, the trip note
       ("text-on-accent", "accent"), ("danger", "bg"), ("danger", "surface")]
)
APP_UI = (
    [("border-strong", bg) for bg in ("bg", "surface", "surface-subtle", "surface-selected")]
    + [("accent", "bg"), ("accent", "surface"), ("accent", "surface-subtle"),   # focus, chosen option
       ("warning", "surface"),                       # a wait step's dot
       ("compass-north", "surface-subtle")]          # the needle
)
WRITEUP_TEXT = (
    [(fg, bg) for fg in ("text-primary", "text-muted", "text-subtle")
     for bg in ("bg", "surface")]
    + [("text-primary", "surface-subtle"),           # code and the trip sample
       ("accent", "surface"), ("accent", "bg"),      # step numbers, a pressed button
       ("success", "surface"), ("danger", "surface"),
       ("text-on-warning", "warning"), ("text-on-accent", "accent")]
)
WRITEUP_UI = [("accent", "track"), ("accent", "bg"), ("accent", "surface")]   # bars, focus

PAGES = {
    "app": (lambda: read(APP_CSS), lambda: read(TEMPLATE), APP_TEXT, APP_UI),
    "writeup": (writeup_css, lambda: read(WRITEUP), WRITEUP_TEXT, WRITEUP_UI),
}


def luminance(hex_colour):
    value = hex_colour.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
               for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    high, low = sorted([luminance(a), luminance(b)], reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_contrast_is_the_wcag_formula():
    """A guard on the arithmetic every check below rests on."""
    assert round(contrast("#000", "#fff"), 2) == 21.0
    assert round(contrast("#767676", "#ffffff"), 2) == 4.54


# ------------------------------------------------------------ the tokens
@pytest.mark.parametrize("page", sorted(PAGES))
def test_every_theme_sets_the_same_tokens(page):
    css, markup, _, _ = PAGES[page]
    blocks = theme_blocks(css())
    themes = themes_list(markup())
    assert themes and themes[0] == "dark", "the first theme is the one in the markup"
    default = set(blocks.get(themes[0], {}))
    missing = CONTRACT - default
    assert not missing, "the default theme lacks contract tokens: %s" % sorted(missing)
    for name in themes:
        assert name in blocks, "THEMES names %r but there is no .theme-%s block" % (name, name)
        assert set(blocks[name]) == default, (
            "theme %r differs from %r: %s" % (name, themes[0],
                                              sorted(set(blocks[name]) ^ default)))


@pytest.mark.parametrize("page", sorted(PAGES))
def test_the_dark_block_is_also_the_no_class_fallback(page):
    """`:where(:root)` beside `.theme-dark`: a page with no theme class, or
    an unknown one left by a stale saved value, is still fully dark."""
    css = PAGES[page][0]()
    selectors = [sel for sel, tokens in rules(css) if ".theme-dark" in sel]
    assert any(":where(:root)" in sel for sel in selectors), selectors


@pytest.mark.parametrize("path", [TEMPLATE, APP_PAGE, WRITEUP],
                         ids=["template", "docs-app", "writeup"])
def test_every_page_opens_dark_in_its_markup(path):
    page = read(path)
    assert re.search(r'<html lang="en" class="theme-dark">', page)
    assert "prefers-color-scheme" not in page, "theme follows the system again"
    assert "localStorage.getItem('theme')" in page.split("</head>")[0], (
        "no restore in <head>, so a saved theme flashes dark first")


def pairs_for(page):
    css, markup, text, ui = PAGES[page]
    blocks = theme_blocks(css())
    for name in themes_list(markup()):
        for fg, bg in text:
            yield name, fg, bg, TEXT, blocks[name]
        for fg, bg in ui:
            yield name, fg, bg, UI, blocks[name]


@pytest.mark.parametrize("page", sorted(PAGES))
def test_every_pairing_meets_aa_in_every_theme(page):
    short = []
    checked = 0
    for name, fg, bg, need, tokens in pairs_for(page):
        a, b = tokens["--color-" + fg], tokens["--color-" + bg]
        ratio = contrast(a, b)
        checked += 1
        if ratio < need:
            short.append("%s: %s %s on %s %s = %.2f (needs %.1f)"
                         % (name, fg, a, bg, b, ratio, need))
    assert checked > 20, "the pair matrix is nearly empty, so this check is vacuous"
    assert not short, "pairings under WCAG AA:\n  " + "\n  ".join(short)


def test_the_map_is_not_themed():
    """The map's colours -- the reach ramp, its background, the overlays
    drawn on it -- are data: the legend is a sample of the ramp the dots are
    painted with, and app.js reads that ramp once. They live outside the
    theme blocks, so no theme can move them."""
    css = read(APP_CSS)
    for name, tokens in theme_blocks(css).items():
        leaked = sorted(t for t in tokens if t.startswith(("--color-reach-", "--color-map-")))
        assert not leaked, "theme %r sets map colours: %s" % (name, leaked)
    data = {}
    for selector, tokens in rules(css):
        if selector == ":root":
            data.update(tokens)
    for token in ("--color-reach-fast", "--color-reach-mid", "--color-reach-slow"):
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", data.get(token, "")), (
            "app.js parses %s as six hex digits" % token)
    assert "getPropertyValue(name)" in read(os.path.join(ROOT, "static", "js", "app.js"))
    for token in ("'--color-reach-fast'", "'--color-reach-mid'", "'--color-reach-slow'"):
        assert token in read(os.path.join(ROOT, "static", "js", "app.js")), token
    # The pill on the map: its text against its translucent fill over the map.
    fill = [int(v) for v in re.findall(r"\d+", data["--color-map-overlay"])[:3]]
    alpha = float(re.search(r",\s*([\d.]+)\)", data["--color-map-overlay"]).group(1))
    under = [int(data["--color-map-bg"][i:i + 2], 16) for i in (1, 3, 5)]
    seen = "#" + "".join("%02x" % round(alpha * f + (1 - alpha) * u) for f, u in zip(fill, under))
    assert contrast(data["--color-map-text"], seen) >= TEXT


def test_no_component_rule_carries_a_raw_colour():
    """Components read tokens. The exceptions are data, and say so."""
    css = re.sub(r"/\*.*?\*/", "", read(APP_CSS), flags=re.S)
    raw = []
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        selector = selector.strip()
        if selector.startswith(":root") or ".theme-" in selector or selector.startswith(":where"):
            continue
        if re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", body):
            raw.append(selector)
    assert raw == [".badge.walk,.badge.drive"], raw


def test_a_line_badges_ink_reads_on_its_line(tmp_path):
    """The badge is the line's own colour, so its ink is chosen per line.
    One dark ink for all of them left Line 4, YRT and GO under 4.5:1."""
    source = read(os.path.join(ROOT, "static", "js", "app.js"))
    pieces = [re.search(r"^const BADGE_INK = .*?;$", source, re.M).group(0)]
    pieces += [re.search(r"^function %s\(.*?^\}" % name, source, re.M | re.S).group(0)
               for name in ("luminance", "contrast", "inkOn", "lineColor")]
    colours = sorted(set(re.findall(r"return '(#[0-9a-fA-F]{6})'",
                                    re.search(r"^function lineColor\(.*?^\}", source,
                                              re.M | re.S).group(0))))
    assert len(colours) >= 8, colours
    inks = run_node(tmp_path, "\n".join(pieces) + "\nconsole.log(JSON.stringify(%s.map(inkOn)));\n"
                    % json.dumps(colours))
    short = ["%s with %s: %.2f" % (c, ink, contrast(c, ink))
             for c, ink in zip(colours, inks) if contrast(c, ink) < TEXT]
    assert not short, short


# ------------------------------------------------------------- in a browser
SCAN = r"""() => {
  const parse = c => { const n = c.match(/[\d.]+/g).map(Number); const unit = c.startsWith('color(') ? 1 : 255;
                       return { rgb: n.slice(0, 3).map(v => v / unit), a: n.length > 3 ? n[3] : 1 }; };
  const lum = c => { const [r, g, b] = parse(c).rgb.map(v => v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
                     return .2126 * r + .7152 * g + .0722 * b; };
  const behind = el => { for (let e = el; e; e = e.parentElement) { const bg = getComputedStyle(e).backgroundColor;
                     if (/\d/.test(bg) && parse(bg).a > .5) return bg; } return getComputedStyle(document.body).backgroundColor; };
  const out = []; let seen = 0;
  for (const el of document.querySelectorAll('body *')) {
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    const s = getComputedStyle(el); if (s.visibility === 'hidden' || s.display === 'none' || !el.getClientRects().length) continue;
    if (el.closest('[hidden], noscript')) continue;
    seen++;
    const big = parseFloat(s.fontSize) >= 24 || (parseFloat(s.fontSize) >= 18.66 && +s.fontWeight >= 700);
    const [L1, L2] = [lum(s.color), lum(behind(el))].sort((a, b) => b - a);
    const r = (L1 + .05) / (L2 + .05);
    if (r < (big ? 3 : 4.5)) out.push(el.tagName + '.' + el.className + ' ' + r.toFixed(2) + ' "' + el.textContent.trim().slice(0, 24) + '"');
  }
  return { seen, short: [...new Set(out)] };
}"""
THEME = r"(document.documentElement.className.match(/(?:^|\s)theme-(\S+)/) || [])[1]"
BODY_BG = "getComputedStyle(document.body).backgroundColor"


def hex_to_rgb(value):
    return "rgb(%d, %d, %d)" % tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def bg_of(page, theme):
    css = PAGES["writeup" if page == "writeup" else "app"][0]()
    return hex_to_rgb(theme_blocks(css)[theme]["--color-bg"])


@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as pw:
        try:
            launched = pw.chromium.launch()
        except Exception as exc:                       # no browser installed
            pytest.skip("Chromium is not installed for Playwright: %s" % exc)
        yield launched
        launched.close()


@pytest.fixture
def open_page(browser, client):
    """open_page(name, js=True, saved=None, width=1280) -> a loaded page.

    The Flask page is served by the app's own test client, under a host that
    never resolves, so it is the real template with the real endpoints and
    the live feed still pointed at .invalid. Map tiles are refused: the map
    is not themed, and the suite does not fetch from OpenStreetMap."""
    contexts = []
    errors = {}

    def serve(route):
        request = route.request
        path = request.url.split("flask.test", 1)[1]
        if request.method == "POST":
            res = client.post(path, data=request.post_data,
                              headers={"Content-Type": "application/json"})
        else:
            res = client.get(path)
        route.fulfill(status=res.status_code, body=res.data,
                      headers={"Content-Type": res.headers.get("Content-Type", "text/plain")})

    urls = {"flask": "http://flask.test/",
            "app": "file:///" + APP_PAGE.replace("\\", "/").lstrip("/"),
            "writeup": "file:///" + WRITEUP.replace("\\", "/").lstrip("/")}

    def opener(name, js=True, saved=None, width=1280):
        context = browser.new_context(java_script_enabled=js, color_scheme="light",
                                      viewport={"width": width, "height": 900})
        contexts.append(context)
        page = context.new_page()
        errors[page] = []
        page.on("pageerror", lambda exc, page=page: errors[page].append(str(exc)))
        page.route("**/*tile.openstreetmap.org/**", lambda route: route.abort())
        page.route("http://flask.test/**", serve)
        if saved is not None:
            page.add_init_script("try { localStorage.setItem('theme', %s) } catch (e) {}"
                                 % json.dumps(saved))
        page.goto(urls[name])
        page.wait_for_timeout(300)
        return page

    opener.errors = errors
    yield opener
    for context in contexts:
        context.close()


BROWSER_PAGES = ["app", "flask", "writeup"]


@pytest.mark.parametrize("name", BROWSER_PAGES)
def test_with_javascript_off_the_page_is_dark(open_page, name):
    page = open_page(name, js=False)
    assert page.evaluate("document.documentElement.className") == "theme-dark"
    assert page.evaluate(BODY_BG) == bg_of(name, "dark")
    assert page.evaluate("getComputedStyle(document.documentElement).colorScheme") == "dark"
    scan = page.evaluate(SCAN)
    assert scan["seen"] > 10 and not scan["short"], scan


@pytest.mark.parametrize("name", BROWSER_PAGES)
def test_the_toggle_switches_and_remembers(open_page, name):
    page = open_page(name)
    themes = page.evaluate("THEMES")
    assert page.evaluate(THEME) == themes[0] == "dark"
    for step in themes[1:] + themes[:1]:
        assert page.get_attribute("#themeBtn", "aria-label") == "Switch to %s theme" % step
        page.click("#themeBtn")
        assert page.evaluate(THEME) == step
        assert page.evaluate(BODY_BG) == bg_of(name, step)
        assert page.evaluate("localStorage.getItem('theme')") == step
    page.click("#themeBtn")
    page.reload()
    page.wait_for_timeout(300)
    assert page.evaluate(THEME) == themes[1], "the choice did not survive a reload"


@pytest.mark.parametrize("name", BROWSER_PAGES)
@pytest.mark.parametrize("saved, expected", [("light", "light"), ("sepia", "dark"),
                                             ("light dark", "dark")])
def test_a_saved_theme_is_restored_or_falls_back_to_dark(open_page, name, saved, expected):
    """A name with no block falls back to dark; one that is not a bare word
    is never put in the class list at all -- classList.replace throws on a
    space, which would be an error on every load until storage is cleared."""
    page = open_page(name, saved=saved)
    assert not open_page.errors[page], open_page.errors[page]
    assert page.evaluate("(document.documentElement.className.match(/theme-\\S+/g) || []).join()") \
        == "theme-" + expected
    assert page.evaluate(BODY_BG) == bg_of(name, expected)


def open_states(page, name):
    """The states a first-load scan never sees."""
    if name == "writeup":
        page.click("#tableBtn")
        return
    if not page.evaluate("typeof L !== 'undefined'"):
        pytest.skip("Leaflet did not load from its CDN, so the map cannot be driven")
    page.wait_for_function("typeof NETWORK !== 'undefined' && NETWORK", timeout=20000)
    page.evaluate("setOrigin(43.6453, -79.3806)")
    page.wait_for_function("document.getElementById('stCount').textContent !== '—'")
    if name == "flask":
        page.evaluate("setDestination(43.7805, -79.4151)")
        page.wait_for_selector(".optRow", timeout=20000)
        page.click('.seg[data-when="at"]')
        page.wait_for_selector(".optRow", timeout=20000)


@pytest.mark.parametrize("name", BROWSER_PAGES)
def test_every_visible_text_meets_aa_in_every_theme(open_page, name):
    page = open_page(name)
    open_states(page, name)
    for theme in page.evaluate("THEMES"):
        page.evaluate("""name => { const root = document.documentElement;
            root.className = root.className.replace(/(^|\\s)theme-\\S+/g, '').trim() + ' theme-' + name; }""",
                      theme)
        page.wait_for_timeout(500)   # buttons and option rows ease their colours in
        scan = page.evaluate(SCAN)
        assert scan["seen"] > 20, "almost no text was scanned, so this check is vacuous"
        assert not scan["short"], "%s: %s" % (theme, scan["short"])
