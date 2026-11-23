import asyncio

import pytest

from stations.culture import drive
from stations.culture.sim import SimCultureStation, SimUnknownMessage

FRAME = '{"op": "release", "batch": "CB-0001", "worklist": "WL-7"}'


def _quiet(_: str) -> None:
  pass


def test_completed_records_release() -> None:
  lines: list = []
  r = asyncio.run(drive.run(None, log=lines.append))
  assert r["outcome"] == "completed"
  assert r["sim"].released == {"CB-0001": "WL-7"}
  assert r["adapter"].records == [{"batch": "CB-0001", "worklist": "WL-7"}]
  assert f"send  {FRAME}" in lines


def test_lost_reply_holds_released_once() -> None:
  r = asyncio.run(drive.run("lost_reply", log=_quiet))
  assert r["outcome"] == "hold" and r["sim"].releases_executed == 1
  assert r["adapter"].records == []


def test_device_error_keeps_code() -> None:
  r = asyncio.run(drive.run("device_error", log=_quiet))
  assert r["outcome"] == "error" and "unknown_batch CB-0001" in r["evidence"]
  assert r["sim"].released == {}


def test_unknown_message_raises() -> None:
  with pytest.raises(SimUnknownMessage):
    SimCultureStation(["CB-0001"]).handle('{"op": "thaw", "batch": "CB-0001"}')


def test_mismatched_worklist_refused_before_sending() -> None:
  sim = SimCultureStation(["CB-0001"])
  with pytest.raises(drive.ReleaseRefused):
    drive.CultureAdapter(sim).release("CB-0001", "WL-7", [{"well": "A1", "batch": "CB-0002"}])
  assert sim.releases_executed == 0
