"""Seed cells into a 384-well plate with the REAL upstream EL406 driver, against SimEL406.

Simulation only. Volumes are made up and round: 500 uL prime, 40 uL per well in all 24 columns.
The peristaltic dispenser is used: upstream gives it dispense, prime and purge
(peristaltic_dispenser.py:83-318).
"""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import patch

from pylabrobot.agilent.biotek.el406 import EL406
from pylabrobot.agilent.biotek.el406.errors import EL406DeviceError
from pylabrobot.resources.cellvis.plates import cellvis_384_wellplate_120uL_Fb

from .sim import NAMES, PLATE_TYPES, SimEL406, VirtualClock

STATION = "seed"
FULL = {0x8D, 0x90, 0x8F}  # frames worth printing in full; the rest are listed by command


def _hex(b: bytes, width: int = 86) -> str:
  s = b.hex(" ")
  return s if len(s) <= width else s[: width - 3] + "..."


class Tap:
  """Logs what crossed the replaced transport since the last call, one phase at a time."""

  def __init__(self, sim: SimEL406, log) -> None:
    self.sim, self.log, self.nf, self.nr = sim, log, 0, 0

  def ask(self, text: str) -> None:
    self.flush()
    self.log(f"ask   {text}")

  def flush(self) -> None:
    frames, replies = self.sim.frames[self.nf :], self.sim.replies[self.nr :]
    self.nf, self.nr = len(self.sim.frames), len(self.sim.replies)
    if not frames:
      return
    rest: list[str] = []
    for f in frames + [b""]:
      cmd = int.from_bytes(f[2:4], "little") if f else -1
      if f and cmd not in FULL:
        rest.append(NAMES.get(cmd, f"0x{cmd:04x}"))
        continue
      if rest:
        self.log(f"send  {len(rest)} frames, by command: {' '.join(rest)}"[:100])
        rest = []
      if f:
        self.log(f"send  {_hex(f)}")
    last = replies[-1] if replies else b""
    self.log(f"recv  {len(replies)} replies, last: {_hex(last, 76)}")
    s = self.sim
    plate = PLATE_TYPES.get(s.plate_type, "-") if s.plate_type is not None else "-"
    cols = sorted(set(s.column_ul.values()))
    self.log(
      f"state plate {plate}, batch {'open' if s.batch_open else 'closed'}, "
      f"prime {s.primed_ul} uL, {len(s.column_ul)} cols at {cols} uL, err 0x{s.error_code:04x}"
    )


async def run(fault: str | None = None, log=print) -> dict:
  """Run the example once, in simulation only."""
  sim, clock = SimEL406(fault=fault), VirtualClock()
  tap = Tap(sim, log)
  mod = importlib.import_module("pylabrobot.agilent.biotek.el406.el406")
  fake_time = SimpleNamespace(monotonic=clock.monotonic)
  fake_asyncio = SimpleNamespace(sleep=clock.sleep, Lock=asyncio.Lock)
  outcome, evidence = "completed", ""
  with patch.object(mod, "time", fake_time), patch.object(mod, "asyncio", fake_asyncio):
    try:
      # --8<-- snippet
      el406 = EL406(name="el406")
      el406.io = sim  # the only swap: the FTDI transport becomes the simulator
      tap.ask("set up: FTDI 38400 8N2, TEST_COMM, INIT_STATE, RESET")
      await el406.setup()

      plate = cellvis_384_wellplate_120uL_Fb(name="cells_384")
      el406.set_plate(plate)
      tap.ask("open a batch for the 384-well plate")
      async with el406.batch():
        tap.ask("prime the peristaltic lines, 500 uL")
        await el406.peristaltic_dispenser.prime(volume=500)

        tap.ask("dispense 40 uL per well, columns 1-24")
        volumes = {column: 40 for column in range(1, 25)}  # uL per well, by column
        await el406.peristaltic_dispenser.dispense(volumes=volumes)
        tap.ask("close the batch: home motors, end-of-batch marker")
      await el406.stop()
      # --8<-- end
    except TimeoutError as e:
      outcome = "hold"
      evidence = (
        f"PERI_DISPENSE: {e}; not resent (sim ran it {sim.executions.get(0x8F, 0)}x), "
        "check plate"
      )
    except EL406DeviceError as e:
      outcome, evidence = "error", f"{e}"
  tap.flush()
  if outcome == "completed":
    full = sim.column_ul == {c: 40 for c in range(1, 25)}
    outcome = "completed" if full and not sim.batch_open else "error"
    evidence = (
      f"sim: {len(sim.column_ul)}/24 columns at 40 uL/well, {sim.dispenser} pump, "
      f"plate byte {sim.plate_type} ({PLATE_TYPES.get(sim.plate_type, '?')})"
    )
  log(f"done  {outcome}: {evidence}"[:100])
  return {"station": STATION, "outcome": outcome, "evidence": evidence, "sim": sim}


if __name__ == "__main__":
  asyncio.run(run())
