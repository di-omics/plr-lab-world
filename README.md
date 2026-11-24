# Reverse engineering the hall

How software reaches each instrument of a simulated in vitro automation hall, shown with
PyLabRobot. 9 stations, 1 example each, simulation only.

For every station the question is the same: is the instrument already decoded?

- Yes, in PyLabRobot: the example runs the real upstream driver against a simulated instrument
  that decodes the frames the driver sends.
- The maker publishes an SDK: nothing to decode. The example wraps the SDK.
- No: the example shows the method (capture, decode, replay behind guards) on a synthetic
  instrument whose payloads are placeholders.

## Run it

    uv run pytest                          # every test
    uv run python -m stations.star.drive   # 1 station, with its wire traffic
    uv run python -m harness.walk          # 1 plate through all 9, then a lost reply at the reader
    uv run python build_page.py            # rebuild index.html from the code and its real output

## Watch it

`replay.html` plays each station's recorded simulation step by step: the lines on the wire on
the left, the simulated instrument's state drawn on the right. Pick a station or "All 9", then a
clean run, a lost reply or an instrument error. It opens offline.

    uv run python -m harness.trace             # record all 27 runs again into traces/
    uv run python build_replay.py              # rebuild replay.html from traces/
    uv run python build_replay.py --fixtures   # build from the hand-written replay_src/fixtures/

Each trace is 1 JSON file: every line of the run with the simulated instrument's state after
it. The format is in `traces/README.md`, so another viewer can play the same runs.

## Layout

    stations/<key>/drive.py      the example: run(fault=None) -> completed, hold or error
    stations/<key>/sim.py        the simulated instrument
    stations/<key>/station.json  the facts the page shows, with sources
    harness/walk.py              the same call at every station, 1 run record
    harness/trace.py             records each run step by step, with the simulated state
    traces/<key>.<case>.json     the recordings: 9 stations x 3 cases
    build_page.py                cuts the code, runs it, counts the tests, writes the page
    build_replay.py              puts the recordings and replay_src/ into 1 page
    index.html                   how each station is reached (opens offline)
    replay.html                  each station running in simulation (opens offline)

Station keys match the 3D hall: culture, seed, star, inc, rail, xarm, hotel, reader, lcms.

## Limits

- Nothing here ran on a physical instrument.
- A simulated instrument answers only the commands its example sends.
- Every volume, position, temperature and timing is a made-up round number.
- A replay is a recording of a simulation, not a video of a machine.
- Pinned to PyLabRobot commit 182f92e (23 Nov 2026) and plr-reverse-engineer 264ca78.
