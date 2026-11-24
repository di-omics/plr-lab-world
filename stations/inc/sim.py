"""SIMULATED LiCONiC STX44 PLC: parses the ASCII commands the REAL legacy upstream backend writes
to its serial transport, keeps plate location and climate state, and answers in the form the
backend parses.

From upstream (REAL), pylabrobot/legacy/storage/liconic/liconic_backend.py:
  commands end in CR (:114, :290); replies end in CR LF (:100-102); CR -> CC handshake (:114-118)
  ST 1801 -> OK (:124-126); RD 1915 ready flag "1" (:132-134, :327-328)
  WR DM0 cassette, DM23 step size, DM25 positions, DM5 slot (:218-221); ST 1904 from transfer
  station (:222); ST 1905 to transfer station (:207); ST 1903 terminate access (:209, :228)
  RD DM982 actual temperature in 0.1 deg C (:357-360); RD 1814 error flag, RD DM200 error (:331-333)
  error replies E0-E5 and handling codes like 00103 (constants.py:66-113)
TODO_1: the reply to a WR/ST command is taken as "OK" (upstream only shows OK for ST 1801, :126).
TODO_2: real move times, and what a real PLC leaves on the shovel after a fault, are unknown.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

READY, PLATE_READY, ERROR_FLAG, ACTIVATE = "1915", "1914", "1814", "1801"
WRITABLE_DM = {"0", "5", "23", "25", "890"}
READABLE_DM = {"200", "890", "982"}


class UnknownCommand(Exception):
  """The simulator got a string it cannot decode. It never answers OK to those."""


class VirtualClock:
  """Stands in for time.time and asyncio.sleep inside the backend module: no real waiting."""

  def __init__(self) -> None:
    self.now = 0.0

  def time(self) -> float:
    return self.now

  async def sleep(self, seconds: float) -> None:
    self.now += seconds
    await asyncio.sleep(0)


@dataclass
class SimSTX44:
  fault: str | None = None  # None | "lost_reply" | "device_error"
  port: str = "sim"
  opened: bool = False  # communication opened by CR
  handling_active: bool = False
  ready: bool = True
  error_code: str = "00000"
  plate: str | None = "transfer"  # "transfer" | "shovel" | "cassette m/n" | None
  dm: dict[str, int] = field(default_factory=lambda: {"890": 370, "982": 370})  # 37.0 deg C
  history: list[str] = field(default_factory=list)  # every place the plate has been
  executions: dict[str, int] = field(default_factory=dict)
  commands: list[str] = field(default_factory=list)  # every command received (REAL strings)
  replies: list[str] = field(default_factory=list)  # every reply produced (SIMULATED)
  _out: bytes = b""

  def snapshot(self) -> dict:
    """PLC state for a replay: where the plate is, ready flag, error register, temperature."""
    place, cassette, position = self.plate, None, None
    if place and place.startswith("cassette "):
      m, n = place.split(" ")[1].split("/")
      place, cassette, position = "cassette", int(m), int(n)
    return {"plate_at": place, "cassette": cassette, "position": position, "ready": self.ready,
            "error": "" if self.error_code == "00000" else self.error_code,
            "temp_c": round(self.dm["982"] / 10, 1)}

  # ---- the pylabrobot.io.Serial surface the backend uses (liconic_backend.py:105-136, 292-293)
  async def setup(self) -> None:
    pass

  async def stop(self) -> None:
    self.opened = False

  async def send_break(self, duration: float) -> None:
    self.opened = False

  async def reset_input_buffer(self) -> None:
    self._out = b""

  async def reset_output_buffer(self) -> None:
    pass

  async def write(self, data: bytes) -> None:
    text = data.decode("ascii")
    if not text.endswith("\r") or "\r" in text[:-1]:
      raise UnknownCommand(f"not 1 CR-terminated command: {data!r}")
    cmd = text[:-1]
    self.commands.append(cmd)
    self.executions[cmd] = self.executions.get(cmd, 0) + 1
    reply = self._execute(cmd)
    if self.fault == "lost_reply" and cmd == "ST 1904":
      logger.info("sim: plate moved in, reply dropped")
      return
    self.replies.append(reply)
    self._out += reply.encode("ascii") + b"\r\n"

  async def read(self, num_bytes: int = 1) -> bytes:
    out, self._out = self._out[:num_bytes], self._out[num_bytes:]
    return out

  async def readline(self) -> bytes:
    i = self._out.find(b"\n") + 1
    out, self._out = (self._out[:i], self._out[i:]) if i else (self._out, b"")
    return out

  # ---- decoding ----
  def _execute(self, cmd: str) -> str:
    if cmd == "CR":
      self.opened = True
      return "CC"
    if not self.opened:
      return "E1"  # errors.py:37: "check if communication is opened by CR"
    parts = cmd.split(" ")
    op = parts[0]
    if op == "RD" and len(parts) == 2:
      return self._read(parts[1])
    if op == "WR" and len(parts) == 3 and parts[1].startswith("DM"):
      reg = parts[1][2:]
      if reg not in WRITABLE_DM or not parts[2].isdigit():
        raise UnknownCommand(f"write to unknown register: {cmd!r}")
      self.dm[reg] = int(parts[2])
      return "OK"
    if op == "ST" and len(parts) == 2:
      return self._set(parts[1])
    raise UnknownCommand(f"unknown command: {cmd!r}")

  def _read(self, what: str) -> str:
    if what == READY:
      return "1" if self.ready else "0"
    if what == ERROR_FLAG:
      return "1" if self.error_code != "00000" else "0"
    if what.startswith("DM") and what[2:] in READABLE_DM:
      return self.error_code if what == "DM200" else str(self.dm[what[2:]])
    raise UnknownCommand(f"read of unknown relay or register: {what!r}")

  def _slot(self) -> str:
    m, n, positions = self.dm.get("0"), self.dm.get("5"), self.dm.get("25")
    if not m or not n or not positions or n > positions or "23" not in self.dm:
      raise UnknownCommand(f"move without a valid cassette/slot in DM0/DM5/DM23/DM25: {self.dm}")
    return f"cassette {m}/{n}"

  def _set(self, relay: str) -> str:
    if relay == ACTIVATE:
      self.handling_active = True
      return "OK"
    if relay == "1903":  # terminate access
      return "OK"
    if relay not in ("1904", "1905"):
      raise UnknownCommand(f"unknown relay: ST {relay}")
    if not self.handling_active:
      return "E1"
    slot = self._slot()
    if relay == "1904":  # import: transfer station -> shovel -> cassette slot
      if self.plate != "transfer":
        raise UnknownCommand(f"ST 1904 but plate is at {self.plate}")
      self.plate = "shovel"
      if self.fault == "device_error":
        self.ready, self.error_code = False, "00103"  # constants.py:92
        return "OK"
      self.plate = slot
      self.history += ["shovel", slot]
    else:  # export: cassette slot -> shovel -> transfer station
      if self.plate != slot:
        raise UnknownCommand(f"ST 1905 for {slot} but plate is at {self.plate}")
      self.plate = "transfer"
      self.history += ["shovel", "transfer"]
    return "OK"
