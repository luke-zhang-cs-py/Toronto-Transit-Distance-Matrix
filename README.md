# Toronto Transit Reach

[![CI](https://github.com/luke-zhang-cs-py/Toronto-Transit-Distance-Matrix/actions/workflows/python-package-conda.yml/badge.svg)](https://github.com/luke-zhang-cs-py/Toronto-Transit-Distance-Matrix/actions/workflows/python-package-conda.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.12-blue.svg)](https://www.python.org/)

How far can you get from any point in Toronto in 30 minutes? Click the map and
find out — plus how to make a specific trip, and what time you'd actually arrive.

![The reach map: click a point, see every stop you can reach, shaded by travel time](docs/screenshot.png)

**[Read the full write-up →](https://luke-zhang-cs-py.github.io/Toronto-Transit-Distance-Matrix/)**
— where each number comes from, the graph it searches, and every bug this has
had. (Or open [`docs/index.html`](docs/index.html) locally.)

## Run it

```bash
pip install -r requirements.txt
python app.py                      # http://127.0.0.1:5000
python tools_build_schedule.py     # optional: adds timetabled departures
```

No API key, no billing account. OpenStreetMap tiles in the browser; every
travel time is computed locally against TTC's own open timetable and live feed.

## Every wait says where it came from

Three kinds of number share one screen and they don't deserve equal trust, so
each one is labelled:

| Source | Means | Covers |
|---|---|---|
| **timetable** | the next actual departure | subway + 6 streetcar routes |
| **headway** | half the observed gap, live | surface routes |
| **modelled** | half an assumed headway | YRT, MiWay, GO |

Live service alerts apply on top — a closed line drops out of the graph, so
trips route around it.

## Tests

```bash
pytest -q
```

220 tests, 100% of 1,014 statements — and that figure is itself checked, because
it had already gone stale once. The suite never touches the network: the
realtime tests run against recorded feeds, one containing a real Line 2 closure.

## License

[MIT](LICENSE) — see [CONTRIBUTING.md](CONTRIBUTING.md) for setup and test conventions.
