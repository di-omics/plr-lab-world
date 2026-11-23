"""SIMULATED Agilent BioTek EL406: decodes the frames the real upstream driver writes to its FTDI
transport, keeps device state, and answers in the shape the driver reads.

Everything about the frames the driver SENDS comes from upstream (REAL):
  framing + checksum  pylabrobot/agilent/biotek/el406/protocol.py:12-50
  command codes       el406.py:290,303,540,724,735,781,795,842; peristaltic_dispenser.py:193,373
  payload layouts     peristaltic_dispenser.py:393-403 (prime), 446-461 (dispense)
  poll reply layout   el406.py:548-557 (validity u16, state u16, 4 bytes, status u8)
What the driver READS back is only partly fixed by upstream: an ACK byte 0x06 (el406.py:236),
then an 11-byte header whose bytes 7-8 give the data length (el406.py:369) and bytes 2-3 echo
the command (el406.py:443). TODO_1: the other reply header bytes (markers, checksum) of a real
EL406 are unknown; this sim fills them with the request layout, and the driver does not check them.
TODO_2: how long a real step stays RUNNING, and what state a real EL406 reports after a fault,
are unknown; this sim reports RUNNING once, then INITIAL (1) or, after a fault, STOPPED (4).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from pylabrobot.agilent.biotek.el406.error_codes import get_error_message
from pylabrobot.agilent.biotek.el406.protocol import build_framed_message

logger = logging.getLogger(__name__)

ACK = b"\x06"
PRE_BATCH = {0xBF, 0xC1, 0xF2, 0xF4, 0x0154, 0x0102, 0x010A}  # el406.py:724, meaning not named
NAMES = {
  0x73: "TEST_COMM", 0xA0: "INIT_STATE", 0x70: "RESET", 0x8D: "START_STEP", 0x92: "STATUS_POLL",
  0x90: "PERI_PRIME", 0x8F: "PERI_DISPENSE", 0xC8: "HOME_MOTORS", 0x8C: "END_OF_BATCH",
}
PLATE_TYPES = {0: "1536 std", 1: "384 std", 2: "384 PCR", 4: "96", 14: "1536 flanged"}
STEP_COMMANDS = {0x90, 0x8F}
PERI_FAULT_CODE = 0x1355  # error_codes.py:41 "The Peri-pump module is not configured"


class UnknownFrame(Exception):
  """The simulator got bytes it cannot decode. It never answers OK to those."""


class VirtualClock:
  """Stands in for time.monotonic and asyncio.sleep inside the driver module: no real waiting."""

  def __init__(self) -> None:
    self.now = 0.0

  def monotonic(self) -> float:
    return self.now

  async def sleep(self, seconds: float) -> None:
    self.now += seconds
    await asyncio.sleep(0)


@dataclass
class SimEL406:
  fault: str | None = None  # None | "lost_reply" | "device_error"
  serial: dict = field(default_factory=dict)
  plate_type: int | None = None
  batch_open: bool = False
  steps: list[str] = field(default_factory=list)
  dispenser: str | None = None
  primed_ul: int = 0
  column_ul: dict[int, int] = field(default_factory=dict)  # 1-based column -> uL per well
  executions: dict[int, int] = field(default_factory=dict)
  frames: list[bytes] = field(default_factory=list)  # every complete frame received (REAL bytes)
  replies: list[bytes] = field(default_factory=list)  # every reply produced (SIMULATED bytes)
  error_code: int = 0
  _rx: bytes = b""
  _tx: bytes = b""
  _busy_polls: int = 0

  # ---- the pylabrobot.io.FTDI surface the driver uses (el406.py:147-173, 208, 229, 269) ----
  async def setup(self) -> None:
    self.serial["open"] = True

  async def stop(self) -> None:
    self.serial["open"] = False

  async def set_baudrate(self, baudrate: int) -> None:
    self.serial["baud"] = baudrate

  async def set_line_property(self, bits: int, stopbits: int, parity: int) -> None:
    self.serial["line"] = (bits, stopbits, parity)

  async def set_flowctrl(self, flowctrl: int) -> None:
    self.serial["flow"] = flowctrl

  async def set_rts(self, level: bool) -> None:
    self.serial["rts"] = level

  async def set_dtr(self, level: bool) -> None:
    self.serial["dtr"] = level

  async def usb_purge_rx_buffer(self) -> None:
    self._tx = b""  # device -> host bytes not yet read are dropped

  async def usb_purge_tx_buffer(self) -> None:
    pass

  async def write(self, data: bytes) -> int:
    self._rx += data
    while len(self._rx) >= 11:
      length = int.from_bytes(self._rx[7:9], "little")
      if len(self._rx) < 11 + length:
        break  # the driver writes header and payload separately (el406.py:349-354)
      frame, self._rx = self._rx[: 11 + length], self._rx[11 + length :]
      self._handle(frame)
    return len(data)

  async def read(self, num_bytes: int = 1) -> bytes:
    out, self._tx = self._tx[:num_bytes], self._tx[num_bytes:]
    return out

  # ---- decoding ----
  def _handle(self, frame: bytes) -> None:
    if frame[0] != 0x01 or frame[1] != 0x02 or frame[4] != 0x01:
      raise UnknownFrame(f"bad header markers: {frame[:11].hex(' ')}")
    cmd = int.from_bytes(frame[2:4], "little")
    data = frame[11:]
    checksum = int.from_bytes(frame[9:11], "little")
    if (sum(frame[:9]) + sum(data) + checksum) & 0xFFFF != 0:
      raise UnknownFrame(f"checksum mismatch in {frame.hex(' ')}")
    if build_framed_message(cmd, data) != frame:
      raise UnknownFrame(f"frame does not match upstream framing: {frame.hex(' ')}")
    if cmd not in NAMES and cmd not in PRE_BATCH:
      raise UnknownFrame(f"unknown command 0x{cmd:04X}: {frame.hex(' ')}")
    self.frames.append(frame)
    self.executions[cmd] = self.executions.get(cmd, 0) + 1
    reply_data = self._execute(cmd, data)
    if self.fault == "lost_reply" and cmd == 0x8F:
      logger.info("sim: dispense carried out, reply dropped")
      return
    reply = ACK + build_framed_message(cmd, reply_data)  # TODO_1: real reply header unknown
    self.replies.append(reply)
    self._tx += reply

  def _execute(self, cmd: int, data: bytes) -> bytes:
    if cmd == 0x92:
      state = 1
      if self._busy_polls:
        self._busy_polls -= 1
        state = 2
      elif self.error_code:
        state = 4
      return (
        self.error_code.to_bytes(2, "little") + state.to_bytes(2, "little") + bytes(4) + b"\x00"
      )
    if cmd == 0x70:
      self.steps.append("reset")
    elif cmd == 0x8D:
      if data[0] not in PLATE_TYPES:
        raise UnknownFrame(f"START_STEP with unknown plate byte {data[0]}")
      self.plate_type, self.batch_open = data[0], True
      self.error_code = 0
    elif cmd in STEP_COMMANDS:
      if not self.batch_open or data[0] != self.plate_type:
        raise UnknownFrame(f"step 0x{cmd:02X} outside a batch or for another plate type")
      self._busy_polls = 1
      if cmd == 0x90:
        self._prime(data)
      else:
        self._dispense(data)
    elif cmd == 0xC8:
      self.steps.append(f"home type {data[0]}")
    elif cmd == 0x8C:
      self.batch_open = False
      self.steps.append("end of batch")
    return b""

  def _prime(self, data: bytes) -> None:
    if len(data) != 11:
      raise UnknownFrame(f"PERI_PRIME payload is {len(data)} bytes, expected 11")
    volume = int.from_bytes(data[1:3], "little")
    self.dispenser, self.primed_ul = "peristaltic", volume
    self.steps.append(f"peristaltic prime {volume} uL")

  def _dispense(self, data: bytes) -> None:
    if len(data) != 24:
      raise UnknownFrame(f"PERI_DISPENSE payload is {len(data)} bytes, expected 24")
    if self.fault == "device_error":
      self.error_code = PERI_FAULT_CODE
      self.steps.append(f"dispense refused: {get_error_message(PERI_FAULT_CODE)}")
      return
    volume = int.from_bytes(data[1:3], "little")
    mask = int.from_bytes(data[12:18], "little")
    columns = [i + 1 for i in range(48) if mask >> i & 1]
    for col in columns:
      self.column_ul[col] = self.column_ul.get(col, 0) + volume
    self.dispenser = "peristaltic"
    self.steps.append(f"peristaltic dispense {volume} uL x {len(columns)} columns")
