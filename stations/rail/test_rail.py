import asyncio

import pytest

from stations.rail import drive
from stations.rail.linear_track import LinearTrack
from stations.rail.sim import SimLinearTrack, SimUnknownCall


def _quiet(_: str) -> None:
  pass


def test_completed_reaches_station() -> None:
  r = asyncio.run(drive.run(None, log=_quiet))
  sim = r["sim"]
  assert r["outcome"] == "completed"
  assert sim.pos == 450 and sim.on_zero == 1 and sim.error == 0 and sim.pos_moves == 1
  assert "set_linear_motor_pos(450,speed=200,wait=False)" in sim.calls
  assert sim.enabled == 0  # stop() restored the state found at setup


def test_lost_reply_holds_and_moves_once() -> None:
  r = asyncio.run(drive.run("lost_reply", log=_quiet))
  sim = r["sim"]
  assert r["outcome"] == "hold"
  assert sim.pos_moves == 1
  assert sim.calls.count("set_linear_motor_pos(450,speed=200,wait=False)") == 1


def test_device_error_keeps_code() -> None:
  r = asyncio.run(drive.run("device_error", log=_quiet))
  assert r["outcome"] == "error"
  assert "LinearTrackError 13" in r["evidence"] and r["sim"].error == 13


def test_unknown_call_raises() -> None:
  sim = SimLinearTrack()
  with pytest.raises(SimUnknownCall):
    sim.set_linear_track_jog(5)
  with pytest.raises(SimUnknownCall):
    sim.set_linear_motor_pos(450.5)


def test_move_is_idempotent() -> None:
  async def go() -> SimLinearTrack:
    sim = SimLinearTrack()
    track = LinearTrack(arm=sim, reply_timeout=0.2, poll_interval=0)
    await track.setup()
    await track.home()
    await track.home()
    await track.move_to(300)
    await track.move_to(300)
    return sim

  sim = asyncio.run(go())
  assert sim.pos_moves == 1
  assert sim.calls.count("set_linear_motor_back_origin(wait=False,auto_enable=True)") == 1


def test_out_of_range_refused_before_sending() -> None:
  sim = SimLinearTrack()
  track = LinearTrack(arm=sim, travel_mm=700)
  with pytest.raises(ValueError):
    asyncio.run(track.move_to(800))
  assert sim.calls == []
