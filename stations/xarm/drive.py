"""Carry 1 plate from a hotel nest to the reader nest with the REAL upstream XArm6 driver.

Only the xarm-python-sdk XArmAPI object is replaced, the same way upstream's own tests do it
(pylabrobot/ufactory/xarm6/xarm6_tests.py:11-18: a fake xarm.wrapper module in sys.modules). Simulation only; nothing
here ran on an arm. Poses, widths and the timeout are made up.
"""

import asyncio
import sys
import types
from typing import Callable, Optional
from unittest import mock

from pylabrobot.resources import Coordinate, Rotation
from pylabrobot.ufactory.xarm6 import XArm6, XArm6Error

from stations.xarm.sim import SimXArmAPI

STATION = "xarm"
HOTEL = Coordinate(x=300, y=200, z=100)  # made up gripping pose at the hotel nest
READER = Coordinate(x=300, y=-200, z=50)  # made up gripping pose at the reader nest
REPLY_TIMEOUT_S = 0.2  # boundary we control; a real carry needs a measured budget (TODO_1)


# --8<-- snippet
async def carry(arm: XArm6) -> None:
  up = Coordinate(z=80)
  down = Rotation(x=180, y=0, z=0)
  await arm.move_to_location(HOTEL + up, down)
  await arm.move_gripper(width=arm.max_gripper_width)
  await arm.pick_up_at_location(HOTEL, down, resource_width=80)
  await arm.move_to_location(HOTEL + up, down)
  await arm.move_to_location(READER + up, down)
  await arm.drop_at_location(READER, down, resource_width=80)
  await arm.move_to_location(READER + up, down)

# arm = XArm6(ip="192.168.1.220"); await arm.setup(); await carry(arm)
# --8<-- end


def _sdk_module(sim: SimXArmAPI) -> dict:
  wrapper = types.ModuleType("xarm.wrapper")
  wrapper.XArmAPI = lambda ip: (setattr(sim, "ip", ip), sim)[1]  # type: ignore[attr-defined]
  xarm = types.ModuleType("xarm")
  xarm.wrapper = wrapper  # type: ignore[attr-defined]
  return {"xarm": xarm, "xarm.wrapper": wrapper}


async def run(fault: Optional[str] = None, log: Callable[[str], None] = print) -> dict:
  """Run the example once, in simulation only."""
  nests = {"hotel": (HOTEL.x, HOTEL.y, HOTEL.z), "reader": (READER.x, READER.y, READER.z)}
  sim = SimXArmAPI(nests, plate_at="hotel", fault=fault, fault_pose=nests["reader"])
  out = {"station": STATION, "sim": sim}
  arm = XArm6(ip="192.168.1.220")  # made-up address, never contacted
  try:
    with mock.patch.dict(sys.modules, _sdk_module(sim)):
      log("ask   setup()")
      await arm.setup()
      log(f"state setup made {len(sim.calls)} SDK calls, all returned 0; mode {sim.mode}, "
          f"state {sim.state}, gripper enabled {sim.gripper_enabled}")
      sim.log = log
      log("ask   carry 1 plate: hotel nest -> reader nest")
      await asyncio.wait_for(carry(arm), timeout=REPLY_TIMEOUT_S)
  except asyncio.TimeoutError:
    n = sim.moves.get(nests["reader"], 0)
    out.update(outcome="hold", evidence=f"place move sent {n} time, no reply in "
               f"{REPLY_TIMEOUT_S} s; plate position unknown")
  except XArm6Error as e:
    out.update(outcome="error", evidence=f"{e}; sim error {sim.error_code} "
               "(collision), unread by XArm6")
  else:
    out.update(outcome="completed", evidence=f"plate at {sim.plate_at} nest, jaws at "
               f"{sim.jaw_units} of 850 units, error_code {sim.error_code}")
  finally:
    sim.release_hung()
  sim.log = None
  log(f"state plate at {sim.plate_at}, pose {[round(v) for v in sim.pose[:3]]}, "
      f"error_code {sim.error_code}")
  log(f"done  {out['outcome']}: {out['evidence']}")
  return out


if __name__ == "__main__":
  asyncio.run(run())
