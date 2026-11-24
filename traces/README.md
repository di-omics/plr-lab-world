# Traces

1 file per station and case: `<key>.<case>.json`, 9 stations x 3 cases = 27 files.
Written by `python -m harness.trace`; `harness/test_trace.py` checks they match a fresh run.
Everything in them is SIMULATED. Nothing here ran on a physical instrument.

Cases: `clean` (no fault, outcome `completed`), `lost_reply` (the instrument acts but its reply
never arrives, outcome `hold`), `device_error` (the instrument answers with an error, outcome
`error`).

## A trace

    {"station": "star", "name": "<from stations/<key>/station.json>", "case": "clean",
     "outcome": "completed" | "hold" | "error", "evidence": "<1 line>", "simulated": true,
     "steps": [{"i": 0, "tag": "ask", "text": "...", "state": {...}}, ...]}

- 1 step per log line of the run, in order; `i` counts from 0.
- `tag` is ask (what the harness requests), send (what the driver emitted), recv (the simulated
  reply), state (a note on simulated state) or done (the outcome). `text` is the line without
  its tag. Long frames are cut with "...", as in the station's own output.
- `state` is the simulated device state right after that line was logged, or null when it is
  equal to the state of the step before. Step 0 always carries a full state, so a player keeps
  the last non-null state. On a send step the state is the one before the device acts on it.
- Files are deterministic: sorted keys, indent 1, ASCII, no times or temporary paths.

## State per station (uL and mm rounded to 1 decimal)

- culture: `released` {batch id: worklist id}, `executed` releases carried out,
  `known_batches`.
- seed: `plate` (plate type named by the last START_STEP, or null), `batch_open`, `pump`,
  `prime_uL`, `columns_uL` (24 values, uL per well, 0 where nothing was dispensed), `error`
  ("" or the code and its upstream text).
- star: `initialized`, `tips_on_channel` and `tip_uL` (8 channels), `source_uL` and `dest_uL`
  (wells A1..H1 of each plate), `tips_in_rack` (of 96).
- inc: `plate_at` transfer, shovel or cassette, with `cassette` and `position` (null unless in
  a cassette), `ready`, `error` ("" or the DM200 handling code), `temp_c`.
- rail: `pos_mm`, `target_mm` (last accepted move, null before one), `travel_mm`, `enabled`,
  `homed`, `error` (the error register), `moves` (moves carried out).
- xarm: `pose` [x, y, z] in mm, `jaw_units` of `jaw_max`, `plate_at` hotel, gripper or reader,
  `error_code`.
- hotel: `slots` (24), `occupied` (shelves holding a plate), `reserved` (slots the scheduler
  still holds), `clock_s` (simulated clock), `dwell_s` (the dwell the scheduler waits for, a
  setting), `pickups` (pickups carried out).
- reader: `phase` capture, decode, replay or draft (parts a to d of the example), `tray` in or
  out, `busy`, `plates_read`, `values` (the 384 made-up values of the last read reply, from the
  step it arrives until the next command reaches the reader, otherwise null).
- lcms: `ready`, `rows` (1 per sequence row: `aliquot`, `started` count, `raw` file name or
  null).

All volumes, positions, temperatures and timings are made-up round numbers.
