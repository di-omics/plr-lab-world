"""The real upstream STARDriver against the simulated STARlet. Plain pytest, no plugins."""

import asyncio

import pytest

from stations.star.drive import run
from stations.star.sim import SimulatedSTARlet, UnknownFrame, decode

COL1 = "ABCDEFGH"


def _quiet(_line: str) -> None:
  pass


def test_completed_conserves_liquid_and_tips():
  result = asyncio.run(run(log=_quiet))
  sim = result["sim"]
  assert result["outcome"] == "completed"
  left = sum(100.0 - sim.volume[f"source:{r}1"] for r in COL1)
  arrived = sum(sim.volume[f"destination:{r}1"] for r in COL1)
  assert left == pytest.approx(arrived)
  assert arrived == pytest.approx(8 * 55.1)  # 8 x av00551, the corrected 50 uL
  assert sim.liquid == [0.0] * 8
  assert sim.tip_on == [None] * 8 and len(sim.tips_in_rack) == 96
  assert all(v == 0 for k, v in sim.volume.items() if k.split(":")[1][1:] != "1")


def test_exact_wire_frames():
  sim = asyncio.run(run(log=_quiet))["sim"]
  assert sim.frames[0] == "C0RMid0001"  # discovery starts by asking what the device is
  tp = next(f for f in sim.frames if f.startswith("C0TP"))
  assert tp == (
    "C0TPid0117xp01179 01179 01179 01179 01179 01179 01179 01179"
    "yp1458 1368 1278 1188 1098 1008 0918 0828tm1 1 1 1 1 1 1 1tt01tp2244tz2164th2828td0"
  )
  module, command, _, params = decode(next(f for f in sim.frames if f.startswith("C0AS")))
  assert (module, command) == ("C0", "AS")
  assert params["av"] == ["00551"] * 8 and params["tm"] == ["1"] * 8
  assert sim.executed["C0VI"] == 1 and sim.executed["C0DI"] == 1


def test_lost_reply_holds_and_never_resends():
  result = asyncio.run(run("lost_reply", log=_quiet))
  sim = result["sim"]
  assert result["outcome"] == "hold"
  assert sim.executed["C0AS"] == 1
  assert sum(sim.liquid) == pytest.approx(8 * 55.1)  # it did happen on the simulated device
  assert "C0DS" not in sim.executed


def test_device_error_keeps_the_code():
  result = asyncio.run(run("device_error", log=_quiet))
  assert result["outcome"] == "error"
  assert "er99/00 P106/70" in result["evidence"]
  assert result["sim"].volume["source:A1"] == 100.0
  assert result["sim"].executed["C0AS"] == 1


def test_unknown_frames_raise():
  sim = SimulatedSTARlet()
  with pytest.raises(UnknownFrame):
    asyncio.run(sim.write(b"C0XXid0001"))
  with pytest.raises(UnknownFrame):
    asyncio.run(sim.write(b"not a frame"))
  assert sim.executed == {}


def test_decode_reads_a_short_list():
  _, _, id_, params = decode("C0DIid0036xp08000&yp4050 3783tm1 1")
  assert id_ == 36 and params == {"xp": ["08000"], "yp": ["4050", "3783"], "tm": ["1", "1"]}
