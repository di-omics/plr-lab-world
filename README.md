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

## Layout

    stations/<key>/drive.py      the example: run(fault=None) -> completed, hold or error
    stations/<key>/sim.py        the simulated instrument
    stations/<key>/station.json  the facts the page shows, with sources
    harness/walk.py              the same call at every station, 1 run record
    build_page.py                cuts the code, runs it, counts the tests, writes the page
    index.html                   the page (opens offline)

Station keys match the 3D hall: culture, seed, star, inc, rail, xarm, hotel, reader, lcms.

## Limits

- Nothing here ran on a physical instrument.
- A simulated instrument answers only the commands its example sends.
- Every volume, position, temperature and timing is a made-up round number.
- Pinned to PyLabRobot commit 182f92e (23 Nov 2026) and plr-reverse-engineer 264ca78.
