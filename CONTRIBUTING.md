# Contributing

## Setup

```bash
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5000
```

Nothing needs an API key. TTC publishes GTFS-realtime openly, and the app
fetches it at startup and then every 30 seconds on a background thread.

## The one thing that will confuse you

`schedule_index.json` is **not in the repository.** It is built from TTC's
36 MB static GTFS archive:

```bash
python tools_build_schedule.py
```

Without it the app still works — boarding waits fall back to live headways,
then to a modelled figure per mode. But the numbers change, and so does the
*order of the trip options*, because a modelled 4-minute wait is longer than
a timetabled one. Driving Union to Finch beats transit at 35.3 minutes
against 42.7 once the timetable is gone.

That is why CI is not the same as your machine, and it is worth knowing
before you debug a failure that will not reproduce:

```bash
mv schedule_index.json /tmp/   # what CI sees
pytest -q
mv /tmp/schedule_index.json .  # what you see
```

The suite has to pass both ways — 160 with the index, 149 and 11 skipped
without. If a test needs the timetable, mark it
`@pytest.mark.skipif(not schedule.available(), ...)` rather than assuming.

`network/bus_routes.json` *is* committed, built by `tools_build_buses.py`.
Rebuilding it is idempotent; if it is not, that is a bug.

## Tests

```bash
pytest -q --cov=. --cov-report=term-missing
python -m flake8 . --select=E9,F63,F7,F82,F401,F402,F811,F841,E722,E741
```

Both must be clean before a push. CI runs the same lint selection plus an
advisory pass at `--max-line-length=127`.

Do not assert on `plan()["options"][0]` expecting transit. Options are sorted
by duration across every kind, so the first one is whichever is quickest,
which is sometimes a car. Ask for the kind you mean.

## Conventions

Comments explain *why*, especially where a number encodes a modelling
decision — `DRIVE_KMH = 26.0` is a claim about city traffic, not a speed
limit, and it says so above the constant. Shared helpers live in `geo.py` and
`gtfs.py`; a structural test fails if a build tool redefines one.

See [CODE_AUDIT.md](CODE_AUDIT.md) for the current state of the code smells,
complexity and coverage.
