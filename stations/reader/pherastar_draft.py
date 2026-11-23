"""DRAFT driver shape for a BMG LABTECH PHERAstar FSX. UNVERIFIED. It has never run on hardware.

Every command constant is TODO_n: nobody here knows the PHERAstar's commands. The values below are
the made-up payloads of the synthetic reader in sim.py, so this class runs against that simulator
only. On a real reader each TODO_n must be replaced by a frame recovered from a capture.

Shape follows docs/contributor_guide/device-driver-guide.md section 2 (upstream 182f92e): 1 plain
class, async setup and stop, a pylabrobot.io-style transport injected, move-to-state methods that
read state, move only if needed and confirm, and a loud warning that it is unverified.

Hypotheses borrowed from the 2 BMG readers upstream already drives, each to be tested first:
- framing: the FTDI frame in pylabrobot/bmg_labtech/protocol/framing.py (the CLARIOstar's link);
- reply envelope and error bits: the VANTAstar's, reimplemented here
  (pylabrobot/bmg_labtech/vantastar/driver/responses.py:79-91 and master.py:108-110),
  because the guide says 1 device's package never imports another's
  (docs/contributor_guide/device-driver-guide.md:30).
"""

import logging
from typing import Dict, List, Protocol, Tuple

from pylabrobot.bmg_labtech.protocol.errors import FrameError
from pylabrobot.bmg_labtech.protocol.framing import (
  FTDI_OVERHEAD,
  ftdi_extract_payload,
  ftdi_validate_frame,
  ftdi_wrap_payload,
)

logger = logging.getLogger(__name__)

TODO_HEADER = 0x3F  # unknown on the PHERAstar; 0x3F is the synthetic reader's
TODO_1_TRAY_OUT = b"TODO_1"  # unknown; synthetic placeholder
TODO_2_TRAY_IN = b"TODO_2"  # unknown; synthetic placeholder
TODO_3_READ_PLATE = b"TODO_3"  # unknown; synthetic placeholder
TODO_4_STATUS = b"TODO_4"  # unknown; synthetic placeholder
TODO_FLAG_TRAY_OUT = 1 << 0  # unknown bit position
_REFUSED_BIT, _ERROR_BIT = 1 << 4, 1 << 6  # VANTAstar layout, hypothesis


class Transport(Protocol):
  """What the draft needs from a pylabrobot.io FTDI or USB object (which one: TODO)."""

  async def setup(self) -> None: ...
  async def stop(self) -> None: ...
  async def write(self, data: bytes) -> int: ...
  async def read(self, num_bytes: int = 1) -> bytes: ...


class ReplyLost(TimeoutError):
  """A command went out and no reply came back. Its effect on the reader is unknown."""


class ReaderDeviceError(Exception):
  """The reader answered with the error bit set. Codes kept as sent."""

  def __init__(self, payload: bytes, codes: Tuple[int, ...]):
    self.payload, self.codes = payload, codes
    super().__init__(f"device error after {payload!r}: codes {'/'.join(map(str, codes))}")


class ReaderRefused(Exception):
  """The reader refused the command (refused bit set)."""


def _split_reply(reply: bytes) -> Tuple[int, bytes, bytes]:
  """id, status header byte, flags, body; VANTAstar layout (responses.py:79-91), hypothesis."""
  length = reply[1] & 0x0F if len(reply) > 1 else 0
  if length < 1 or len(reply) < 1 + length:
    raise FrameError(f"reply shorter than its status header: {reply.hex()}")
  return reply[1], reply[2 : 1 + length], reply[1 + length :]


class PHERAstarDraft:
  """Unverified draft. Commands are TODO_n placeholders (see module docstring)."""

  def __init__(self, transport: Transport, read_attempts: int = 3) -> None:
    self.transport = transport
    self.read_attempts = read_attempts

  async def setup(self) -> None:
    logger.warning("PHERAstarDraft is UNVERIFIED: TODO_n commands, never run on hardware")
    await self.transport.setup()

  async def stop(self) -> None:
    await self.transport.stop()

  async def _read_frame(self, payload: bytes) -> bytes:
    """Read 1 reply frame; its length comes from the size field (as in upstream's
    pylabrobot/bmg_labtech/transport/ftdi_interface.py:3). Never re-sends: an empty read
    raises ReplyLost."""
    frame = b""
    for _ in range(self.read_attempts):
      need = 3 if len(frame) < 3 else int.from_bytes(frame[1:3], "big") - len(frame)
      if need <= 0:
        break
      chunk = await self.transport.read(need)
      if chunk:
        frame += chunk
    if len(frame) < FTDI_OVERHEAD:
      raise ReplyLost(f"no reply to {payload!r}; not re-sent, reader state unknown")
    ftdi_validate_frame(frame, header=TODO_HEADER)
    return ftdi_extract_payload(frame)

  async def _command(self, payload: bytes) -> Tuple[bytes, bytes]:
    """Send 1 payload once and return (flags, body). Raises on refused or error bits."""
    await self.transport.write(ftdi_wrap_payload(payload, header=TODO_HEADER))
    status, flags, body = _split_reply(await self._read_frame(payload))
    if status & _ERROR_BIT:
      raise ReaderDeviceError(payload, tuple(body[1:6]))
    if status & _REFUSED_BIT:
      raise ReaderRefused(f"{payload!r} refused: codes {tuple(body[1:6])}")
    return flags, body

  async def request_status(self) -> Dict[str, bool]:
    flags, _ = await self._command(TODO_4_STATUS)
    return {"tray_out": bool(flags[0] & TODO_FLAG_TRAY_OUT)}

  async def _move_tray(self, out: bool) -> None:
    if (await self.request_status())["tray_out"] == out:
      logger.info("tray already %s, not moved", "out" if out else "in")
      return
    await self._command(TODO_1_TRAY_OUT if out else TODO_2_TRAY_IN)
    if (await self.request_status())["tray_out"] != out:
      raise RuntimeError(f"tray did not reach {'out' if out else 'in'}")

  async def ensure_tray_out(self) -> None:
    """Be out: read state, move only if needed, confirm."""
    await self._move_tray(True)

  async def ensure_tray_in(self) -> None:
    """Be in: read state, move only if needed, confirm."""
    await self._move_tray(False)

  async def read_plate(self, wells: int = 384) -> List[int]:
    """Read the plate once. Never retried: a lost reply raises ReplyLost for a human to check."""
    _, body = await self._command(TODO_3_READ_PLATE)
    if len(body) != 2 * wells:
      raise FrameError(f"expected {wells} values, got {len(body)} bytes")
    return [int.from_bytes(body[i : i + 2], "big") for i in range(0, len(body), 2)]

