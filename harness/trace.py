"""Record every station run as a step-by-step trace that a replay page can play back.

    python -m harness.trace

For each station and each case (clean, lost_reply, device_error) the station runs once, in
simulation only. Every log line becomes 1 step: its tag, its text, and the simulated device state
right after that line (or null when the state did not change since the step before). The files
go to traces/<key>.<case>.json. The format is described in traces/README.md.
"""
from __future__ import annotations

import asyncio
import gc
import importlib
import json
import logging
from pathlib import Path

from harness.walk import ORDER

ROOT = Path(__file__).resolve().parent.parent
TRACES = ROOT / "traces"
CASES = {"clean": None, "lost_reply": "lost_reply", "device_error": "device_error"}
TAGS = ("ask", "send", "recv", "state", "done")


def station_name(key: str) -> str:
  return json.loads((ROOT / "stations" / key / "station.json").read_text())["name"]


async def record(key: str, case: str) -> dict:
  """Run 1 station once for 1 case and return its trace."""
  if case not in CASES:
    raise ValueError(f"unknown case {case!r}, expected one of {sorted(CASES)}")
  drive = importlib.import_module(f"stations.{key}.drive")
  watched: list = []
  steps: list[dict] = []
  last: list = [None]

  def watch(obj: object) -> None:
    watched.append(obj)

  def log(line: str) -> None:
    tag, text = line[:6].strip(), line[6:].strip()
    if tag not in TAGS:
      raise ValueError(f"{key}: log line without a known tag: {line!r}")
    if len(watched) != 1:
      raise RuntimeError(f"{key}: watch was called {len(watched)} times before the first line")
    state = json.loads(json.dumps(watched[0].snapshot()))  # a JSON-safe deep copy
    same = bool(steps) and state == last[0]
    last[0] = state
    steps.append({"i": len(steps), "tag": tag, "text": text, "state": None if same else state})

  gc.collect()  # finish off earlier garbage now, so its warnings never land inside this run
  result = await drive.run(fault=CASES[case], log=log, watch=watch)
  return {"station": key, "name": station_name(key), "case": case,
          "outcome": result["outcome"], "evidence": str(result["evidence"]),
          "simulated": True, "steps": steps}


def dumps(trace: dict) -> str:
  return json.dumps(trace, sort_keys=True, indent=1, ensure_ascii=True) + "\n"


def main() -> None:
  logging.getLogger().addHandler(logging.NullHandler())  # keep upstream warnings off stderr
  TRACES.mkdir(exist_ok=True)
  for key in ORDER:
    for case in CASES:
      trace = asyncio.run(record(key, case))
      path = TRACES / f"{key}.{case}.json"
      path.write_text(dumps(trace), encoding="ascii")
      print(f"traces/{path.name}: {trace['outcome']}, {len(trace['steps'])} steps")


if __name__ == "__main__":
  main()
