"""A SYNTHETIC plate reader. It is NOT a PHERAstar and none of its commands are PHERAstar commands.

What is REAL here: the frame envelope, built and checked with upstream PyLabRobot's BMG framing
(pylabrobot/bmg_labtech/protocol/framing.py:5-7, STX | size | header | payload | 24-bit sum | CR),
which upstream uses for the CLARIOstar's FTDI link (the VANTAstar is USB only). Whether the
PHERAstar uses it is unknown.

What is MADE UP: the header byte, every command payload (literally the ASCII text "TODO_1" ...
"TODO_4", so nobody can mistake them for the instrument's bytes), the reply id of the data reply,
the flag positions, the error code and all 384 well values. The reply envelope (reply id, a status
header whose low nibble is its length and whose bits 4-7 mean refused, busy, error, warning) copies
the VANTAstar layout in pylabrobot/bmg_labtech/vantastar/driver/responses.py:1-11 and
pylabrobot/bmg_labtech/vantastar/driver/master.py:108-111 as a hypothesis to test, not a fact
about the PHERAstar.
"""

import json
import logging
from collections import Counter
from typing import Callable, Dict, List, Optional

from pylabrobot.bmg_labtech.protocol.framing import (
  FTDI_STX,
  ftdi_extract_payload,
  ftdi_validate_frame,
  ftdi_wrap_payload,
)

logger = logging.getLogger(__name__)

# Made up. Upstream's readers use 0x0C (pylabrobot/bmg_labtech/clariostar/driver/framing.py:12)
# and 0x16 (pylabrobot/bmg_labtech/vantastar/driver/framing.py:13). The PHERAstar's header
# byte, if it has one, is unknown.
SYNTHETIC_HEADER = 0x3F

# Made-up command payloads. Their meaning comes only from the action marks of the capture.
TODO_1 = b"TODO_1"  # synthetic "tray out"
TODO_2 = b"TODO_2"  # synthetic "tray in"
TODO_3 = b"TODO_3"  # synthetic "read the plate"
TODO_4 = b"TODO_4"  # synthetic "status"
COMMANDS = {TODO_1: "TODO_1", TODO_2: "TODO_2", TODO_3: "TODO_3", TODO_4: "TODO_4"}

CONFIRMATION_ID = 0x01  # VANTAstar (vantastar/driver/responses.py:17), hypothesis only
TODO_DATA_ID = 0x7D  # made up
REFUSED_BIT, BUSY_BIT, ERROR_BIT = 1 << 4, 1 << 5, 1 << 6  # VANTAstar layout, hypothesis only
FLAG_TRAY_OUT, FLAG_PLATE = 1 << 0, 1 << 1  # made-up positions in flag byte 0
TODO_ERROR_CODE = 6  # made up; what the PHERAstar reports on a fault is unknown
TODO_QUIT_NOT_READY = 99  # made up
WELLS = 384


class UnknownFrame(Exception):
  """The synthetic reader got a frame it does not know. It never answers OK to one."""


def wrap(payload: bytes) -> bytes:
  """Frame a payload with upstream's BMG FTDI framing and the made-up header byte."""
  return ftdi_wrap_payload(payload, header=SYNTHETIC_HEADER)


def reply(reply_id: int, bits: int, flags: int, body: bytes) -> bytes:
  """A reply payload: id, status header (length 3 = itself + 2 flag bytes), flags, body."""
  return bytes([reply_id, 0x03 | bits, flags, 0x00]) + body


class SyntheticReader:
  """Keeps state (tray in or out, plate on tray, reads done) and answers TODO_n frames."""

  def __init__(self) -> None:
    self.tray_out = False
    self.plate_on_tray = False
    self.busy = False  # moves finish at once in simulation, so it is never seen busy
    self.plates_read = 0
    self.fault: Optional[str] = None  # "lost_reply" | "device_error", fires on the next TODO_3
    self.phase = "capture"
    self.executed: Dict[str, Counter] = {}
    self.last_values: Optional[List[int]] = None  # from the last data reply, until the next frame

  def _count(self, name: str) -> None:
    self.executed.setdefault(self.phase, Counter())[name] += 1

  def load_plate(self) -> None:
    """The operator puts a plate on the tray. Needs the tray out."""
    if not self.tray_out:
      raise RuntimeError("simulated operator: the tray is in, no plate can be placed")
    self.plate_on_tray = True

  def _confirmation(self, bits: int = 0, codes: bytes = bytes(5)) -> bytes:
    flags = (FLAG_TRAY_OUT if self.tray_out else 0) | (FLAG_PLATE if self.plate_on_tray else 0)
    if self.busy:
      bits |= BUSY_BIT
    return reply(CONFIRMATION_ID, bits, flags, bytes([5]) + codes)

  def handle(self, frame: bytes) -> Optional[bytes]:
    """Decode one host frame and return the reply frame, or None if the reply is lost."""
    if not frame or frame[0] != FTDI_STX:
      raise UnknownFrame(f"not a framed message: {frame.hex()}")
    ftdi_validate_frame(frame, header=SYNTHETIC_HEADER)  # size, CR and checksum (raises)
    payload = ftdi_extract_payload(frame)
    self.last_values = None
    name = COMMANDS.get(payload)
    if name is None:
      raise UnknownFrame(f"unknown payload {payload.hex()}")
    if payload == TODO_4:
      return wrap(self._confirmation())
    if payload in (TODO_1, TODO_2):
      self.tray_out = payload == TODO_1
      self._count(name)
      return wrap(self._confirmation())
    # TODO_3: read the plate
    if self.tray_out or not self.plate_on_tray:
      return wrap(self._confirmation(REFUSED_BIT, bytes([TODO_QUIT_NOT_READY, 0, 0, 0, 0])))
    if self.fault == "device_error":
      self.fault = None
      return wrap(self._confirmation(ERROR_BIT, bytes([TODO_ERROR_CODE, 0, 0, 0, 0])))
    self._count(name)
    self.plates_read += 1
    values = b"".join((1000 + (i * 37) % 500).to_bytes(2, "big") for i in range(WELLS))
    if self.fault == "lost_reply":
      self.fault = None
      logger.info("synthetic reader: plate read, reply dropped (fault lost_reply)")
      return None
    out = wrap(reply(TODO_DATA_ID, 0, FLAG_PLATE, values))
    body = ftdi_extract_payload(out)[4:]  # the values as they stand in the reply frame
    self.last_values = [int.from_bytes(body[i : i + 2], "big") for i in range(0, len(body), 2)]
    return out

  def state(self) -> str:
    return (
      f"tray {'out' if self.tray_out else 'in'}, plate {'on' if self.plate_on_tray else 'off'}"
      f" tray, plates read {self.plates_read}"
    )


class SimByteConn:
  """plr_re ByteConn shape (plr-reverse-engineer/plr_re/transports.py:22-25): sync write and
  read, onto the sim."""

  def __init__(self, sim: SyntheticReader, tap: Callable[[str, bytes], None]) -> None:
    self.sim, self.tap, self._rx = sim, tap, b""

  def write(self, data: bytes) -> None:
    self.tap("send", data)
    out = self.sim.handle(bytes(data))
    if out is not None:
      self.tap("recv", out)
      self._rx += out

  def read(self, size: int = 512) -> bytes:
    data, self._rx = self._rx[:size], self._rx[size:]
    return data

  def close(self) -> None:
    pass


class SimTransport:
  """The pylabrobot.io FTDI shape the draft needs (async write, async read(num_bytes))."""

  def __init__(self, sim: SyntheticReader, tap: Callable[[str, bytes], None]) -> None:
    self.conn = SimByteConn(sim, tap)

  async def setup(self) -> None:
    pass

  async def stop(self) -> None:
    pass

  async def write(self, data: bytes) -> int:
    self.conn.write(data)
    return len(data)

  async def read(self, num_bytes: int = 1) -> bytes:
    return self.conn.read(num_bytes)


class VendorStandIn:
  """A stand-in for the vendor PC software: 1 action at a time, then a status poll, as
  upstream's drivers poll status after a move
  (pylabrobot/bmg_labtech/clariostar/driver/master.py:426-454).

  It writes what passes on the wire in plr_re's serial capture format, JSONL of {t, hex}
  (plr-reverse-engineer/plr_re/capture.py:131), 1 file per direction, because capture_serial
  reads 1 real port and records no direction (plr-reverse-engineer/plr_re/capture.py:119-131).
  """

  def __init__(self, sim: SyntheticReader, host_path: str, reader_path: str, clock) -> None:
    self.sim, self.host_path, self.reader_path, self.clock = sim, host_path, reader_path, clock

  def _log(self, path: str, data: bytes) -> None:
    with open(path, "a", encoding="utf-8") as fh:
      fh.write(json.dumps({"t": self.clock(), "hex": data.hex()}) + "\n")

  def _exchange(self, payload: bytes) -> None:
    frame = wrap(payload)
    self._log(self.host_path, frame)
    out = self.sim.handle(frame)
    if out is not None:
      self._log(self.reader_path, out)

  def do(self, action: str) -> List[str]:
    """Carry out 1 named action and its status poll. Returns the commands used."""
    payload = {"tray_out": TODO_1, "tray_in": TODO_2, "read_plate": TODO_3}[action]
    self._exchange(payload)
    if action == "tray_out":
      self.sim.load_plate()
    self._exchange(TODO_4)
    return [COMMANDS[payload], "TODO_4"]
