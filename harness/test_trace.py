"""Tests for the replay traces: schema, determinism, files on disk, and the simulated end state."""
import asyncio
import json

from harness.trace import CASES, TAGS, TRACES, dumps, record, station_name
from harness.walk import ORDER

OUTCOME = {"clean": "completed", "lost_reply": "hold", "device_error": "error"}


def _num(v) -> bool:
  return isinstance(v, (int, float)) and not isinstance(v, bool)


def _nums(n: int):
  return lambda v: isinstance(v, list) and len(v) == n and all(_num(x) for x in v)


def _bools(n: int):
  return lambda v: isinstance(v, list) and len(v) == n and all(isinstance(x, bool) for x in v)


def _ints(v) -> bool:
  return isinstance(v, list) and all(isinstance(x, int) and not isinstance(x, bool) for x in v)


def _int(v) -> bool:
  return isinstance(v, int) and not isinstance(v, bool)


def _opt(check):
  return lambda v: v is None or check(v)


def _str(v) -> bool:
  return isinstance(v, str)


def _bool(v) -> bool:
  return isinstance(v, bool)


def _one_of(*allowed):
  return lambda v: v in allowed


def _row(v) -> bool:
  return (isinstance(v, dict) and set(v) == {"aliquot", "started", "raw"} and _str(v["aliquot"])
          and _int(v["started"]) and _opt(_str)(v["raw"]))


SCHEMA = {
  "culture": {"released": lambda v: isinstance(v, dict) and all(
                _str(k) and _str(x) for k, x in v.items()),
              "executed": _int, "known_batches": lambda v: isinstance(v, list) and all(
                _str(x) for x in v)},
  "seed": {"plate": _opt(_str), "batch_open": _bool, "pump": _opt(_str), "prime_uL": _num,
           "columns_uL": _nums(24), "error": _str},
  "star": {"initialized": _bool, "tips_on_channel": _bools(8), "tip_uL": _nums(8),
           "source_uL": _nums(8), "dest_uL": _nums(8), "tips_in_rack": _int},
  "inc": {"plate_at": _one_of("transfer", "shovel", "cassette"), "cassette": _opt(_int),
          "position": _opt(_int), "ready": _bool, "error": _str, "temp_c": _num},
  "rail": {"pos_mm": _num, "target_mm": _opt(_num), "travel_mm": _num, "enabled": _bool,
           "homed": _bool, "error": _int, "moves": _int},
  "xarm": {"pose": _nums(3), "jaw_units": _int, "jaw_max": _int,
           "plate_at": _one_of("hotel", "gripper", "reader"), "error_code": _int},
  "hotel": {"slots": lambda v: v == 24, "occupied": _ints, "reserved": _ints,
            "clock_s": _num, "dwell_s": _num, "pickups": _int},
  "reader": {"phase": _one_of("capture", "decode", "replay", "draft"),
             "tray": _one_of("in", "out"), "busy": _bool, "plates_read": _int,
             "values": _opt(_nums(384))},
  "lcms": {"ready": _bool,
           "rows": lambda v: isinstance(v, list) and len(v) == 8 and all(_row(r) for r in v)},
}


def _all() -> dict:
  return {(k, c): asyncio.run(record(k, c)) for k in ORDER for c in CASES}


TRACES_NOW = _all()


def _final(trace: dict) -> dict:
  return [s["state"] for s in trace["steps"] if s["state"] is not None][-1]


def _states(trace: dict) -> list:
  """The state in force at every step (nulls filled in from the step before)."""
  out, cur = [], None
  for s in trace["steps"]:
    cur = s["state"] if s["state"] is not None else cur
    out.append(cur)
  return out


def _sends(trace: dict, start: str) -> int:
  return sum(1 for s in trace["steps"] if s["tag"] == "send" and s["text"].startswith(start))


def test_schema_of_all_27():
  assert len(TRACES_NOW) == 27
  for (key, case), t in TRACES_NOW.items():
    assert set(t) == {"station", "name", "case", "outcome", "evidence", "simulated", "steps"}
    assert t["station"] == key and t["case"] == case and t["simulated"] is True
    assert t["name"] == station_name(key) and t["name"]
    assert t["outcome"] in ("completed", "hold", "error") and _str(t["evidence"])
    assert t["steps"] and t["steps"][0]["state"] is not None, (key, case)
    prev = None
    for n, s in enumerate(t["steps"]):
      assert set(s) == {"i", "tag", "text", "state"} and s["i"] == n
      assert s["tag"] in TAGS and _str(s["text"]) and s["text"] == s["text"].strip()
      if s["state"] is not None:
        assert set(s["state"]) == set(SCHEMA[key]), (key, case, n)
        for name, check in SCHEMA[key].items():
          assert check(s["state"][name]), (key, case, n, name, s["state"][name])
        assert s["state"] != prev, (key, case, n, "repeated state should be null")
        prev = s["state"]
    assert t["steps"][-1]["tag"] == "done"


def test_recording_is_deterministic():
  again = _all()
  for k in TRACES_NOW:
    assert dumps(again[k]) == dumps(TRACES_NOW[k]), k


def test_files_match_a_fresh_recording():
  for (key, case), t in TRACES_NOW.items():
    path = TRACES / f"{key}.{case}.json"
    assert path.read_text(encoding="ascii") == dumps(t), path.name
    assert json.loads(path.read_text()) == t


def test_outcome_per_case():
  for (key, case), t in TRACES_NOW.items():
    assert t["outcome"] == OUTCOME[case], (key, case, t["evidence"])


def test_clean_final_states():
  f = {k: _final(TRACES_NOW[(k, "clean")]) for k in ORDER}
  first = TRACES_NOW[("star", "clean")]["steps"][0]["state"]
  star = f["star"]
  lost = [round(a - b, 1) for a, b in zip(first["source_uL"], star["source_uL"])]
  gained = [round(a - b, 1) for a, b in zip(star["dest_uL"], first["dest_uL"])]
  assert lost == gained and all(x > 0 for x in lost)
  assert star["tips_on_channel"] == [False] * 8 and star["tips_in_rack"] == 96
  assert f["seed"]["columns_uL"] == [40.0] * 24 and not f["seed"]["batch_open"]
  assert f["inc"]["plate_at"] == "transfer" and f["inc"]["error"] == ""
  assert f["rail"]["pos_mm"] == f["rail"]["target_mm"] == 450.0 and f["rail"]["moves"] == 1
  assert f["xarm"]["plate_at"] == "reader" and f["xarm"]["error_code"] == 0
  assert f["hotel"]["occupied"] == [] and f["hotel"]["reserved"] == []
  assert f["hotel"]["pickups"] == 1
  assert f["reader"]["phase"] == "draft" and len(f["reader"]["values"]) == 384
  assert len(f["lcms"]["rows"]) == 8
  assert all(r["started"] == 1 and r["raw"] for r in f["lcms"]["rows"])
  assert len({r["raw"] for r in f["lcms"]["rows"]}) == 8
  assert f["culture"]["released"] == {"CB-0001": "WL-7"} and f["culture"]["executed"] == 1


def test_lost_reply_shows_the_action_happened_once():
  t = {k: TRACES_NOW[(k, "lost_reply")] for k in ORDER}
  f = {k: _final(v) for k, v in t.items()}
  assert f["culture"]["executed"] == 1 and f["culture"]["released"] == {"CB-0001": "WL-7"}
  assert f["seed"]["columns_uL"] == [40.0] * 24  # twice would read 80
  clean_star = _final(TRACES_NOW[("star", "clean")])
  assert f["star"]["source_uL"] == clean_star["source_uL"]  # 1 aspiration, not 2
  assert [round(s + h, 1) for s, h in zip(f["star"]["source_uL"], f["star"]["tip_uL"])] == \
         [100.0] * 8
  assert f["inc"]["plate_at"] == "cassette" and (f["inc"]["cassette"], f["inc"]["position"]) == \
         (1, 1)
  assert sum(s["text"].count("ST 1904") for s in t["inc"]["steps"] if s["tag"] == "send") == 1
  assert f["rail"]["moves"] == 1 and f["rail"]["pos_mm"] == 450.0
  assert _sends(t["xarm"], "set_position(x=300,y=-200,z=50,") == 1
  assert f["xarm"]["pose"] == [300.0, -200.0, 50.0] and f["xarm"]["plate_at"] == "gripper"
  assert f["hotel"]["pickups"] == 1 and f["hotel"]["occupied"] == []
  assert f["hotel"]["reserved"] == [5]
  read = "02 00 0e 3f 54 4f 44 4f 5f 33"  # framed TODO_3, the synthetic read command
  reads = [st for s, st in zip(t["reader"]["steps"], _states(t["reader"]))
           if s["tag"] == "send" and s["text"].startswith(read) and st["phase"] == "draft"]
  assert len(reads) == 1 and f["reader"]["plates_read"] == 3 and f["reader"]["values"] is None
  rows = f["lcms"]["rows"]
  assert [r["started"] for r in rows] == [1, 1, 1, 1, 0, 0, 0, 0] and rows[3]["raw"] is None
