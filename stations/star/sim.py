"""A simulated Hamilton STARlet that answers at the USB boundary. SIMULATED, not the instrument.

It stands where `pylabrobot.io.usb.USB` would stand under the real upstream `STARDriver`. Every
frame the driver writes is decoded (module, command, id, parameters) and answered in the reply
shape upstream parses: `<module><command>id<####>er00/00<fields>` (C0) or `...er00<fields>`.
A frame it does not model raises `UnknownFrame`; it never answers OK by default.

Reply values are taken, where upstream has them, from what upstream recorded or captured:
- device facts: pylabrobot/hamilton/star/driver/recordings/starlet_legacy_2021_8ch_head96_
  autoload1D.json (upstream: only its STAR recording was read off a device, this one is derived)
- RU / UA reply shape: pylabrobot/legacy/liquid_handling/backends/hamilton/STAR_tests.py:3061,3066
- VY / VW reply shape: pylabrobot/legacy/liquid_handling/backends/hamilton/STAR_tests.py:2622,223
Everything else (positions, drive parameters, serial) is made up. This STARlet is cut down to
8 channels on 1 arm: no iSWAP, no 96-head, no autoload, so the driver asks for none of them.
Liquid is booked from the av / dv volumes only; air gaps and over-aspiration are not modelled.
"""

import queue
import re
from typing import Callable, Dict, List, Optional, Tuple

from pylabrobot.io.io import IOBase

FRAME = re.compile(r"^(?P<module>[A-Z0-9]{2})(?P<command>[A-Z]{2})id(?P<id>\d{4})(?P<rest>.*)$")
PARAM = re.compile(r"([a-z]{2})([^a-z]*)")
MASTER_FW = "7.6S 25 2021_11_05 (GRU C0)"  # recording: device.firmware_version
CHANNEL_FW = "4.0S j 2022-03-16"  # recording: arms.left.pipettes.channels[*].firmware_version
XARM_FW = "1.4S 2012-04-25"  # recording: device.left_arm.firmware_version
UL_PER_PISTON_INCREMENT = 0.046876  # recording: pipettes.dispensing_drive_uL_per_increment
MM_PER_Z_INCREMENT = 0.01072765  # recording: pipettes.z_drive_mm_per_increment
Z_TOP = 31200  # recording: pipettes.z_range_increments[1]
Point = Tuple[int, int]  # x, y in 0.1 mm on the deck, as the driver writes xp / yp


class UnknownFrame(Exception):
  """The driver sent something this simulator does not model."""


def decode(frame: str) -> Tuple[str, str, int, Dict[str, List[str]]]:
  """Split a firmware command into module, command, id and its parameters.

  A parameter is 2 lowercase letters, then its value; a list holds 1 value per channel, space
  separated, ending in `&` when it stops short of the channel count.
  """
  m = FRAME.match(frame)
  if m is None:
    raise UnknownFrame(f"not a STAR firmware command: {frame!r}")
  params = {name: value.rstrip("&").split() for name, value in PARAM.findall(m["rest"])}
  return m["module"], m["command"], int(m["id"]), params


class SimulatedSTARlet(IOBase):
  """In-memory transport plus device state: tips and liquid per channel, volume per well."""

  def __init__(self, fault: Optional[str] = None, tap: Optional[Callable[[str, str], None]] = None):
    self.fault = fault
    self.tap: Callable[[str, str], None] = tap or (lambda tag, text: None)
    self.wells: Dict[str, Point] = {}
    self.tip_spots: Dict[str, Point] = {}
    self.volume: Dict[str, float] = {}  # uL per well
    self.tips_in_rack: set = set()
    self.tip_on: List[Optional[str]] = [None] * 8  # the tip spot each channel took a tip from
    self.liquid = [0.0] * 8  # uL held in each tip
    self.tip_length = [0] * 8  # 0.1 mm the mounted tip reaches below the stop disc
    self.tip_types: Dict[int, int] = {}  # the volatile tip type table: index -> tip length
    self.initialized = False  # a device just switched on
    self.x = 950  # arm X, 0.1 mm
    self.y = [1530 - 100 * n for n in range(8)]  # 0.1 mm, back to front
    self.z = [Z_TOP] * 8  # stop disc, Z-drive increments
    self.drive = [{"yv": "0001", "yr": "1", "zv": "00001", "zr": "001"} for _ in range(8)]
    self.executed: Dict[str, int] = {}  # module + command -> times carried out
    self.frames: List[str] = []
    self.clock_offset = 0.0  # seconds a lost reply pushes the driver's clock forward
    self._replies: "queue.Queue[bytes]" = queue.Queue()

  def load(self, wells: Dict[str, Point], tip_spots: Dict[str, Point],
           volumes: Dict[str, float]) -> None:
    """Say where wells and tip spots are, and what the wells hold. The device itself cannot know."""
    self.wells, self.tip_spots = wells, tip_spots
    self.volume = {name: 0.0 for name in wells} | volumes
    self.tips_in_rack = set(tip_spots)

  # -- the transport, as pylabrobot.io.usb.USB offers it ---------------------------------------

  async def setup(self, *args, **kwargs) -> None:
    pass

  async def stop(self) -> None:
    pass

  async def write(self, data: bytes, *args, **kwargs) -> None:
    frame = data.decode()
    self.frames.append(frame)
    self.tap("send  ", frame)
    module, command, id_, p = decode(frame)
    handler = getattr(self, f"_{module}_{command}", None)
    if handler is None:
      raise UnknownFrame(f"no simulated answer for {module} {command}: {frame!r}")
    fields = handler(p)
    self.executed[module + command] = self.executed.get(module + command, 0) + 1
    if fields is None:  # carried out, but the reply never reaches the driver
      self.tap("recv  ", "(nothing: the reply was lost)")
      self.clock_offset += 3600.0
      return
    ok = "" if fields.startswith("er") else ("er00/00" if module == "C0" else "er00")
    reply = f"{module}{command}id{id_:04}{ok}{fields}"
    self.tap("recv  ", reply)
    self._replies.put(reply.encode())

  async def read(self, *args, **kwargs) -> bytes:
    try:
      return self._replies.get(timeout=0.005)
    except queue.Empty:
      raise TimeoutError("no reply waiting") from None

  # -- what the device is ------------------------------------------------------------------------

  def _C0_RM(self, p) -> str:
    return "kb01kp08"  # kb bit 0: 1000 uL channels; kp: 8 channels

  def _C0_QM(self, p) -> str:  # ka bit 0: left X drive large; xt 30 tracks; xl bit 0: channels
    return ("ka000001ke00000000xt30xa00xw08000xl01xn00xr00xo00xm03500xx06000xu3540xv3700"
            "kc0kr0ys090kl360km360ym6065yu0060yx0060")

  def _C0_RU(self, p) -> str:
    return "ru00950 08002 30000 30000"

  def _C0_UA(self, p) -> str:
    return "ua5952 0000 -03232 +09772 +30000 +30000"

  def _C0_RI(self, p) -> str:
    return "si0000snSIM1"

  def _C0_RF(self, p) -> str:
    return "rf" + MASTER_FW

  def _X0_RF(self, p) -> str:
    return "rf" + XARM_FW

  def _channel_rf(self, p, n: int) -> str:
    return "rf" + CHANNEL_FW

  def _channel_vw(self, p, n: int) -> str:
    return "vw0 0"

  def _channel_vy(self, p, n: int) -> str:
    return "yc000 194 0"

  # -- start-up and reads ------------------------------------------------------------------------

  def _C0_QW(self, p) -> str:
    return f"qw{int(self.initialized)}"

  def _C0_VI(self, p) -> str:  # the device's own initialization
    self.initialized = True
    return ""

  def _C0_DI(self, p) -> str:  # initialize the channels at the Y positions sent
    self.y, self.z = [int(v) for v in p["yp"]], [Z_TOP] * 8
    return ""

  def _C0_ZA(self, p) -> str:  # every channel up to Z safety
    self.z = [Z_TOP] * 8
    return ""

  def _C0_RT(self, p) -> str:
    return "rt" + " ".join("0" if t is None else "1" for t in self.tip_on)

  def _C0_RY(self, p) -> str:
    return "ry" + " ".join(f"+{y:04}" for y in self.y)

  def _C0_RZ(self, p) -> str:  # lowest point per channel in 0.1 mm: tip bottom, else stop disc
    low = [round(self.z[n] * MM_PER_Z_INCREMENT * 10) - self.tip_length[n] for n in range(8)]
    return "rz" + " ".join(f"+{z:04}" for z in low)

  def _X0_RX(self, p) -> str:  # arm X in 0.1 mm; the motor count upstream mentions is left out
    return f"rx{self.x:05}"

  def _channel_rz(self, p, n: int) -> str:
    return f"rz{self.z[n]:06}"

  def _channel_rd(self, p, n: int) -> str:
    return f"rd{round(self.liquid[n] / UL_PER_PISTON_INCREMENT):05}"

  def _channel_ra(self, p, n: int) -> str:  # read 1 stored drive parameter: `RAra` + its name
    name = next(k for k in p if k != "ra")
    return name + self.drive[n][name]

  def _channel_aa(self, p, n: int) -> str:  # write stored drive parameters, same widths only
    for name, value in p.items():
      if name not in self.drive[n] or len(value[0]) != len(self.drive[n][name]):
        raise UnknownFrame(f"P{n + 1}AA with an unknown parameter or width: {p}")
      self.drive[n][name] = value[0]
    return ""

  def _C0_TT(self, p) -> str:  # write 1 entry of the tip type table: tl = tip length, 0.1 mm
    self.tip_types[int(p["tt"][0])] = int(p["tl"][0])
    return ""

  def _X0_XP(self, p) -> str:  # move the left arm: la in 0.1 mm
    self.x = int(p["la"][0])
    return ""

  def _C0_JY(self, p) -> str:  # move the channels in Y: yp in 0.1 mm, back to front
    self.y = [int(v) for v in p["yp"]]
    return ""

  # -- tips and liquid: each channel named in `tm` acts at its own (xp, yp) ---------------------

  def _targets(self, p, places: Dict[str, Point]) -> List[Tuple[int, str]]:
    out = []
    for n, used in enumerate(p["tm"]):
      if used != "1":
        continue
      x, y = int(p["xp"][min(n, len(p["xp"]) - 1)]), int(p["yp"][n])
      name = next((k for k, (px, py) in places.items() if abs(px - x) <= 10 and abs(py - y) <= 10),
                  None)
      if name is None:
        raise UnknownFrame(f"channel {n + 1} at x={x} y={y} (0.1 mm) is over nothing modelled")
      out.append((n, name))
      self.x, self.y[n] = x, y
    return out

  def _C0_TP(self, p) -> str:  # pick up tips
    for n, spot in self._targets(p, self.tip_spots):
      if self.tip_on[n] is not None or spot not in self.tips_in_rack:
        raise UnknownFrame(f"TP on channel {n + 1} at {spot}: this tip state is not modelled")
      self.tips_in_rack.remove(spot)
      self.tip_on[n], self.tip_length[n] = spot, self.tip_types[int(p["tt"][0])]
    self.tap("state ", f"tips on {sum(t is not None for t in self.tip_on)} of 8 channels")
    return ""

  def _C0_TR(self, p) -> str:  # put tips down, here back into rack spots
    for n, spot in self._targets(p, self.tip_spots):
      if self.tip_on[n] is None or spot in self.tips_in_rack:
        raise UnknownFrame(f"TR on channel {n + 1} at {spot}: this tip state is not modelled")
      self.tips_in_rack.add(spot)
      self.tip_on[n], self.tip_length[n] = None, 0
    self.tap("state ", f"tips on {sum(t is not None for t in self.tip_on)} of 8 channels, "
                       f"{len(self.tips_in_rack)} in the rack")
    return ""

  def _C0_AS(self, p) -> Optional[str]:  # aspirate: av = 0.1 uL per channel
    if self.fault == "device_error":
      return "er99/00 P106/70"  # P1 06/70: liquid surface not detected, errors.py:384-386
    moved = self._targets(p, self.wells)
    for n, well in moved:
      uL = int(p["av"][n]) / 10
      if self.tip_on[n] is None or self.volume[well] < uL:
        raise UnknownFrame(f"AS on channel {n + 1} from {well}: no tip, or too little liquid")
      self.volume[well] -= uL
      self.liquid[n] += uL
    self.tap("state ", self._describe(moved, "left in"))
    return None if self.fault == "lost_reply" else ""

  def _C0_DS(self, p) -> str:  # dispense: dv = 0.1 uL per channel
    moved = self._targets(p, self.wells)
    for n, well in moved:
      uL = int(p["dv"][n]) / 10
      if self.tip_on[n] is None or self.liquid[n] < uL - 1e-9:
        raise UnknownFrame(f"DS on channel {n + 1} into {well}: more than its tip holds")
      self.liquid[n] -= uL
      self.volume[well] += uL
    self.tap("state ", self._describe(moved, "now in"))
    return ""

  def _describe(self, moved: List[Tuple[int, str]], verb: str) -> str:
    wells = sorted({self.volume[w] for _, w in moved})
    held = sorted({round(self.liquid[n], 1) for n, _ in moved})
    plate = moved[0][1].split(":")[0]
    return f"{verb} {plate} wells: {wells} uL each; tips hold {held} uL each"


def _bind(name: str, n: int) -> Callable:
  method = getattr(SimulatedSTARlet, name)
  return lambda self, p: method(self, p, n)


for _n in range(8):  # channel modules P1..P8
  for _cmd in ("RF", "VW", "VY", "RZ", "RD", "RA", "AA"):
    setattr(SimulatedSTARlet, f"_P{_n + 1}_{_cmd}", _bind(f"_channel_{_cmd.lower()}", _n))
