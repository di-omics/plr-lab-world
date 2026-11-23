"""SIMULATED xArm 6 + bio-gripper, standing in for the xarm-python-sdk XArmAPI object.

The upstream driver never sees bytes: it calls methods on an XArmAPI object (pylabrobot/ufactory/xarm6/xarm6.py:120-122).
This class has the same method names and return shapes as xarm-python-sdk 1.18.4:
commands return an int code, queries return (code, data). It checks every argument the driver
passes and raises SimUnknownCall on anything it does not know. Poses are made up.
"""

import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

# Return codes copied from xarm-python-sdk 1.18.4 (xarm/x3/code.py:25-26, x_config.py:501).
OK = 0
HAS_ERROR = 1  # APIState.HAS_ERROR, what wait_move returns when error_code != 0 (base.py:2525)
# Controller error 31, title from xarm/core/config/x_code.py:657-660.
COLLISION = (31, "Collision Caused Abnormal Current")
UNITS_MAX = 850  # bio-gripper position units, as upstream xarm6.py:34
JAW_MIN_MM, JAW_MAX_MM = 71.0, 150.0  # upstream defaults, xarm6.py:41-42


class SimUnknownCall(Exception):
  """The driver made an SDK call this simulator does not know."""


def _mm(units: int) -> float:
  return JAW_MIN_MM + units / UNITS_MAX * (JAW_MAX_MM - JAW_MIN_MM)


def _units(mm: float) -> int:
  return int(round((mm - JAW_MIN_MM) / (JAW_MAX_MM - JAW_MIN_MM) * UNITS_MAX))


class SimXArmAPI:
  """Arm pose, jaw opening, error and state codes, and where the 1 plate is."""

  def __init__(self, nests: Dict[str, Tuple[float, float, float]], plate_at: str,
               plate_width_mm: float = 85.5, fault: Optional[str] = None,
               fault_pose: Optional[Tuple[float, float, float]] = None) -> None:
    self.nests = nests  # nest name -> (x, y, z) gripping pose, made up
    self.plate_at = plate_at  # a nest name, or "gripper"
    self.plate_width_mm = plate_width_mm  # made up
    self.fault, self.fault_pose = fault, fault_pose
    self.ip: Optional[str] = None
    self.pose = [300.0, 0.0, 300.0, 180.0, 0.0, 0.0]
    self.jaw_units = UNITS_MAX
    self.error_code, self.state, self.mode = 0, 4, 0
    self.motion_enabled = self.gripper_enabled = False
    self.connected = True
    self.calls: List[str] = []
    self.moves: Dict[Tuple[float, float, float], int] = {}  # executions per target xyz
    self.log: Optional[Callable[[str], None]] = None
    self._hung = threading.Event()

  # -- tap --------------------------------------------------------------------------------
  def _send(self, text: str) -> None:
    self.calls.append(text)
    if self.log:
      self.log(f"send  {text}")

  def _recv(self, ret: Any) -> Any:
    if self.log:
      self.log(f"recv  {ret}")
    return ret

  def __getattr__(self, name: str) -> Any:
    if name.startswith("__"):
      raise AttributeError(name)
    raise SimUnknownCall(f"unknown SDK call {name}")

  def release_hung(self) -> None:
    self._hung.set()

  # -- lifecycle (xarm6.py:99-145) ---------------------------------------------------------
  def clean_error(self) -> int:
    self._send("clean_error()")
    self.error_code = 0
    return self._recv(OK)

  def clean_warn(self) -> int:
    self._send("clean_warn()")
    return self._recv(OK)

  def motion_enable(self, enable: bool) -> int:
    self._send(f"motion_enable({enable})")
    self.motion_enabled = bool(enable)
    return self._recv(OK)

  def set_mode(self, mode: int) -> int:
    self._send(f"set_mode({mode})")
    if mode not in (0, 2):
      raise SimUnknownCall(f"set_mode({mode})")
    self.mode = mode
    return self._recv(OK)

  def set_state(self, state: int) -> int:
    self._send(f"set_state({state})")
    if state != 0:
      raise SimUnknownCall(f"set_state({state})")
    if self.error_code == 0 and self.motion_enabled:
      self.state = 0
    return self._recv(OK)

  def set_gripper_mode(self, mode: int) -> int:
    self._send(f"set_gripper_mode({mode})")
    return self._recv(OK)

  def set_gripper_enable(self, enable: bool) -> int:
    self._send(f"set_gripper_enable({enable})")
    self.gripper_enabled = bool(enable)
    return self._recv(OK)

  def disconnect(self) -> None:
    self._send("disconnect()")
    self.connected = False
    return self._recv(None)

  # -- gripper (xarm6.py:158-188) ----------------------------------------------------------
  def set_gripper_position(self, pos: int, wait: bool = False, speed: int = 0) -> int:
    self._send(f"set_gripper_position({pos},wait={wait},speed={speed})")
    if not isinstance(pos, int) or not 0 <= pos <= UNITS_MAX or not self.gripper_enabled:
      raise SimUnknownCall(f"set_gripper_position({pos})")
    here = self._nest_here()
    if _mm(pos) < self.plate_width_mm and self.plate_at in (here, "gripper"):
      self.plate_at = "gripper"
      self.jaw_units = _units(self.plate_width_mm)  # jaws stop on the plate
    else:
      if self.plate_at == "gripper":
        self.plate_at = here or "dropped"
      self.jaw_units = pos
    # The real SDK maps gripper codes 1, 2 and 9 to 0 unless the arm error is 19 or 28
    # (xarm/x3/base.py:2559-2578); this sim always answers 0.
    return self._recv(OK)

  def get_gripper_position(self) -> Tuple[int, int]:
    self._send("get_gripper_position()")
    return self._recv((OK, self.jaw_units))

  # -- arm (xarm6.py:214-251) --------------------------------------------------------------
  def get_position(self) -> Tuple[int, List[float]]:
    self._send("get_position()")
    return self._recv((OK, list(self.pose)))

  def set_position(self, *, x: float, y: float, z: float, roll: float, pitch: float,
                   yaw: float, speed: float, mvacc: float, wait: bool) -> int:
    f = lambda v: f"{v:g}"  # noqa: E731
    self._send(f"set_position(x={f(x)},y={f(y)},z={f(z)},roll={f(roll)},pitch={f(pitch)},"
               f"yaw={f(yaw)},speed={f(speed)},mvacc={f(mvacc)},wait={wait})")
    if not wait or self.mode != 0:
      raise SimUnknownCall("set_position outside position mode or without wait")
    if self.error_code != 0 or self.state != 0:
      return self._recv(HAS_ERROR)
    target = (float(x), float(y), float(z))
    self.moves[target] = self.moves.get(target, 0) + 1
    if self.fault == "device_error" and target == self.fault_pose:
      self.error_code, self.state = COLLISION[0], 4  # stops before the target
      return self._recv(HAS_ERROR)
    self.pose = [x, y, z, roll, pitch, yaw]
    if self.fault == "lost_reply" and target == self.fault_pose:
      self._hung.wait(5.0)  # the move happened; the reply never reaches the driver
      return OK
    return self._recv(OK)

  def _nest_here(self) -> Optional[str]:
    for name, xyz in self.nests.items():
      if all(abs(a - b) < 0.5 for a, b in zip(self.pose[:3], xyz)):
        return name
    return None
