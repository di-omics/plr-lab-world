"""SIMULATED UFACTORY linear track, as seen through the xarm-python-sdk XArmAPI object.

Same method names, arguments and return shapes as xarm-python-sdk 1.18.4
(xarm/wrapper/xarm_api.py:3648-3805, xarm/x3/linear_motor.py:82-219). It validates arguments,
keeps position, enable, homed, motion and error registers, and raises on any call it does not
know. Motion completes at once; real travel times are NOT CHECKED.
"""

import threading
from typing import Any, Callable, List, Optional, Tuple

OK = 0
NOT_INIT = 82  # APIState.LINEAR_MOTOR_NOT_INIT, xarm/x3/code.py:54; linear_motor.py:159-161
POSITION_DEVIATION = 13  # error register value, xarm/core/config/x_code.py:1101-1104


class SimUnknownCall(Exception):
  """The driver made an SDK call this simulator does not know."""


class SimLinearTrack:
  def __init__(self, travel_mm: int = 700, fault: Optional[str] = None) -> None:
    self.travel_mm, self.fault = travel_mm, fault
    self.pos, self.enabled, self.on_zero, self.status, self.error = 0, 0, 0, 0, 0
    self.calls: List[str] = []
    self.pos_moves = 0  # executed set_linear_motor_pos commands
    self.log: Optional[Callable[[str], None]] = None
    self._hung = threading.Event()
    self._moved = False

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

  # -- queries: (code, value) -----------------------------------------------------------------
  def get_linear_motor_is_enabled(self) -> Tuple[int, int]:
    self._send("get_linear_motor_is_enabled()")
    return self._recv((OK, self.enabled))

  def get_linear_motor_on_zero(self) -> Tuple[int, int]:
    self._send("get_linear_motor_on_zero()")
    return self._recv((OK, self.on_zero))

  def get_linear_motor_error(self) -> Tuple[int, int]:
    self._send("get_linear_motor_error()")
    return self._recv((OK, self.error))

  def get_linear_motor_status(self) -> Tuple[int, int]:
    self._send("get_linear_motor_status()")
    return self._recv((OK, self.status))

  def get_linear_motor_pos(self) -> Tuple[int, int]:
    self._send("get_linear_motor_pos()")
    if self.fault == "lost_reply" and self._moved:
      self._hung.wait(5.0)  # the position report never comes back
      return (OK, self.pos)
    return self._recv((OK, self.pos))

  # -- commands: code -------------------------------------------------------------------------
  def set_linear_motor_enable(self, enable: bool) -> int:
    self._send(f"set_linear_motor_enable({enable})")
    if not isinstance(enable, (bool, int)):
      raise SimUnknownCall(f"set_linear_motor_enable({enable!r})")
    self.enabled = int(bool(enable))
    return self._recv(OK)

  def set_linear_motor_back_origin(self, wait: bool = True, **kwargs: Any) -> int:
    self._send(f"set_linear_motor_back_origin(wait={wait},auto_enable="
               f"{kwargs.get('auto_enable', True)})")
    if set(kwargs) - {"auto_enable", "timeout"}:
      raise SimUnknownCall(f"set_linear_motor_back_origin kwargs {kwargs}")
    self.pos, self.on_zero = 0, 1
    if kwargs.get("auto_enable", True):
      self.enabled = 1
    return self._recv(OK)

  def set_linear_motor_pos(self, pos: int, speed: Optional[int] = None, wait: bool = True,
                           timeout: int = 100, **kwargs: Any) -> int:
    self._send(f"set_linear_motor_pos({pos},speed={speed},wait={wait})")
    if not isinstance(pos, int) or not 0 <= pos <= self.travel_mm:
      raise SimUnknownCall(f"set_linear_motor_pos({pos!r}) outside 0..{self.travel_mm}")
    if speed is not None and not (isinstance(speed, int) and 1 <= speed <= 1000):
      raise SimUnknownCall(f"speed {speed!r} outside 1..1000")
    if self.on_zero != 1:
      return self._recv(NOT_INIT)
    self.pos_moves += 1
    if self.fault == "device_error":
      self.pos, self.error = (self.pos + pos) // 2, POSITION_DEVIATION  # stops part way
    else:
      self.pos = pos
    self._moved = True
    return self._recv(OK)
