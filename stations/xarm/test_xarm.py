import asyncio
import sys

import pytest
from unittest import mock

from pylabrobot.resources import Coordinate, Rotation
from pylabrobot.ufactory.xarm6 import XArm6

from stations.xarm import drive
from stations.xarm.sim import SimUnknownCall, SimXArmAPI

PLACE = "set_position(x=300,y=-200,z=50,roll=180,pitch=0,yaw=0,speed=100,mvacc=2000,wait=True)"


def _quiet(_: str) -> None:
  pass


def test_completed_moves_the_plate() -> None:
  r = asyncio.run(drive.run(None, log=_quiet))
  sim = r["sim"]
  assert r["outcome"] == "completed"
  assert sim.plate_at == "reader" and sim.jaw_units == 850 and sim.error_code == 0
  assert PLACE in sim.calls
  assert "set_gripper_position(97,wait=True,speed=0)" in sim.calls  # 80 mm -> 97 units


def test_lost_reply_holds_and_sends_once() -> None:
  r = asyncio.run(drive.run("lost_reply", log=_quiet))
  sim = r["sim"]
  assert r["outcome"] == "hold"
  assert sim.calls.count(PLACE) == 1 and sim.moves[(300.0, -200.0, 50.0)] == 1
  assert sim.plate_at == "gripper"  # the arm got there; the driver does not know it


def test_device_error_keeps_code() -> None:
  r = asyncio.run(drive.run("device_error", log=_quiet))
  assert r["outcome"] == "error"
  assert "XArm6Error 1" in r["evidence"] and "sim error 31" in r["evidence"]
  assert r["sim"].plate_at == "gripper"


def test_unknown_call_raises() -> None:
  sim = SimXArmAPI({}, plate_at="hotel")
  with pytest.raises(SimUnknownCall):
    sim.set_servo_angle(angle=[0] * 6)
  with pytest.raises(SimUnknownCall):
    sim.set_position(x=0, y=0, z=0, roll=0, pitch=0, yaw=0, speed=1, mvacc=1, wait=False)


def _with_arm(body) -> SimXArmAPI:
  nests = {"hotel": (300.0, 200.0, 100.0)}
  sim = SimXArmAPI(nests, plate_at="hotel")

  async def go() -> None:
    with mock.patch.dict(sys.modules, drive._sdk_module(sim)):
      arm = XArm6(ip="192.168.1.220")
      await arm.setup()
      await body(arm, sim)

  asyncio.run(go())
  return sim


def test_limit_ok_code_while_arm_in_error() -> None:
  async def body(arm: XArm6, sim: SimXArmAPI) -> None:
    sim.error_code = 31
    await arm.move_gripper(width=100)  # SDK returns 0, driver raises nothing

  assert _with_arm(body).error_code == 31


def test_limit_grip_width_is_clamped() -> None:
  async def body(arm: XArm6, sim: SimXArmAPI) -> None:
    await arm.move_gripper(width=200)
    await arm.move_gripper(width=10)

  calls = _with_arm(body).calls
  assert "set_gripper_position(850,wait=True,speed=0)" in calls
  assert "set_gripper_position(0,wait=True,speed=0)" in calls


def test_limit_no_plate_held_query() -> None:
  seen = {}

  async def body(arm: XArm6, sim: SimXArmAPI) -> None:
    await arm.pick_up_at_location(Coordinate(300, 200, 100), Rotation(x=180), resource_width=80)
    seen["closed"] = await arm.is_gripper_closed()
    seen["held"] = sim.plate_at == "gripper"

  _with_arm(body)
  assert seen == {"closed": False, "held": True}
