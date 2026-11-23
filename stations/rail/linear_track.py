"""UFACTORY linear track, driven through the maker's xarm-python-sdk. Not in PyLabRobot.

One plain class in the shape of PyLabRobot's device-driver guide (sections 2 and 5). The track
hangs off the xArm controller, so it is reached through the same XArmAPI object as the arm.
SDK names, units and return codes are from xarm-python-sdk 1.18.4:
  xarm/wrapper/xarm_api.py:3648-3805 (get/set_linear_motor_*; the *_linear_track_* names are
  aliases, xarm_api.py:120-133), xarm/x3/linear_motor.py, xarm/x3/code.py:52-57.
Like upstream XArm6 it calls the vendor SDK, not a pylabrobot.io transport (guide section 2).
UNVERIFIED: never run against a real track.
"""

import asyncio
import logging
from typing import Any, Literal, Optional

logger = logging.getLogger(__name__)

# Error register titles copied from xarm/core/config/x_code.py:1070-1104
# (LinearMotorErrorCodeMap, subset).
_TRACK_ERRORS = {10: "Linear Motor Current Detection Error", 11: "Linear Motor Current Overlimit",
                 12: "Linear Motor Speed Overlimit",
                 13: "Linear Motor Large Motor Position Deviation"}


class LinearTrackError(Exception):
  def __init__(self, code: int, message: str):
    self.code = code
    super().__init__(f"LinearTrackError {code}: {message}")


class LinearTrackTimeout(Exception):
  """An SDK call did not return within reply_timeout. Device state is unknown."""


class LinearTrack:
  """Position-controlled linear track. Positions in whole mm, speeds in mm/s.

  Args:
    ip: xArm controller IP. Ignored when ``arm`` (an XArmAPI-like object) is given.
    travel_mm: Stroke of the model (SDK doc: 700, 1000 or 1500 mm by serial number).
    reply_timeout: Seconds to wait for any 1 SDK call before giving up.
  """

  def __init__(self, ip: str = "", travel_mm: Literal[700, 1000, 1500] = 700,
               arm: Any = None, reply_timeout: float = 30.0, poll_interval: float = 0.1):
    self._ip, self._arm, self._own_arm = ip, arm, arm is None
    self.travel_mm, self.reply_timeout, self.poll_interval = travel_mm, reply_timeout, poll_interval
    self._was_enabled: Optional[bool] = None

  async def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
    try:
      ret = await asyncio.wait_for(
        asyncio.to_thread(getattr(self._arm, name), *args, **kwargs), self.reply_timeout)
    except asyncio.TimeoutError:
      logger.error("%s: no reply within %s s", name, self.reply_timeout)
      raise LinearTrackTimeout(f"{name}: no reply within {self.reply_timeout} s") from None
    code, data = (ret[0], ret[1]) if isinstance(ret, (tuple, list)) else (ret, None)
    if code != 0:  # 80 = fault, 81 = SCI low, 82 = not homed (xarm/x3/code.py:52-54)
      raise LinearTrackError(code, f"{name} returned code {code}")
    return data

  async def setup(self) -> None:
    logger.warning("LinearTrack is not verified on hardware. Please report results.")
    if self._arm is None:
      from xarm.wrapper import XArmAPI  # type: ignore[import-not-found,import-untyped]
      self._arm = XArmAPI(self._ip)
    self._was_enabled = bool(await self._call("get_linear_motor_is_enabled"))
    if not self._was_enabled:
      await self._call("set_linear_motor_enable", True)

  async def stop(self) -> None:
    """Restore the enable state found at setup, then disconnect if we connected."""
    if self._arm is None:
      return
    if self._was_enabled is False:
      await self._call("set_linear_motor_enable", False)
    if self._own_arm:
      await asyncio.to_thread(self._arm.disconnect)
      self._arm = None

  async def request_position(self) -> int:
    return int(await self._call("get_linear_motor_pos"))

  async def _check_error(self) -> None:
    err = await self._call("get_linear_motor_error")
    if err:
      raise LinearTrackError(err, _TRACK_ERRORS.get(err, "see the SDK linear motor error table"))

  async def home(self) -> None:
    """Be homed. The SDK refuses moves until on_zero is 1 (xarm/x3/linear_motor.py:158-161)."""
    if await self._call("get_linear_motor_on_zero") == 1:
      return
    await self._call("set_linear_motor_back_origin", wait=False, auto_enable=True)
    while await self._call("get_linear_motor_on_zero") != 1:
      await self._check_error()
      await asyncio.sleep(self.poll_interval)

  async def move_to(self, position_mm: int, speed: int = 200) -> int:
    """Be at ``position_mm``. Moves only if needed, then confirms the arrival."""
    if not 0 <= position_mm <= self.travel_mm or not 1 <= speed <= 1000:
      raise ValueError(f"position 0..{self.travel_mm} mm and speed 1..1000 mm/s")
    if await self.request_position() == position_mm:
      return position_mm
    await self._call("set_linear_motor_pos", position_mm, speed=speed, wait=False)
    while True:
      await self._check_error()
      if (await self._call("get_linear_motor_status")) & 0x01 == 0:  # bit 0 = in motion
        break
      await asyncio.sleep(self.poll_interval)
    arrived = await self.request_position()
    if arrived != position_mm:
      raise LinearTrackError(-1, f"stopped at {arrived} mm, asked {position_mm} mm")
    return arrived
