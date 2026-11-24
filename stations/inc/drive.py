"""Take 1 plate into a LiCONiC STX44 and fetch it back, with the REAL legacy upstream backend
against SimSTX44. Simulation only. Cassette 1, position 1 and 37.0 deg C are made up.
"""

from __future__ import annotations

import asyncio
import importlib
import warnings
from types import SimpleNamespace
from unittest.mock import patch

from pylabrobot.legacy.storage import ExperimentalLiconicBackend, Incubator
from pylabrobot.legacy.storage.liconic.racks import liconic_rack_17mm_22
from pylabrobot.resources import Coordinate
from pylabrobot.resources.cellvis.plates import cellvis_384_wellplate_120uL_Fb

from .sim import SimSTX44, VirtualClock

STATION = "inc"


def _runs(items: list[str]) -> str:
  """Join items with ' | ', folding repeats: 'RD 1915 x600'."""
  out: list[str] = []
  for item in items:
    if out and out[-1].split(" x")[0] == item:
      n = int(out[-1].rsplit(" x", 1)[1]) + 1 if " x" in out[-1] else 2
      out[-1] = f"{item} x{n}"
    else:
      out.append(item)
  s = " | ".join(out)
  return s if len(s) <= 93 else s[:90] + "..."


class Tap:
  """Logs what crossed the replaced serial transport since the last call, per phase."""

  def __init__(self, sim: SimSTX44, log) -> None:
    self.sim, self.log, self.nc, self.nr = sim, log, 0, 0

  def ask(self, text: str) -> None:
    self.flush()
    self.log(f"ask   {text}")

  def flush(self) -> None:
    cmds, replies = self.sim.commands[self.nc :], self.sim.replies[self.nr :]
    self.nc, self.nr = len(self.sim.commands), len(self.sim.replies)
    if cmds:
      self.log(f"send  {_runs(cmds)}")
      self.log(f"recv  {_runs(replies)}")
      s = self.sim
      self.log(f"state plate at {s.plate}, ready {int(s.ready)}, error {s.error_code}, "
               f"temp {s.dm['982'] / 10:.1f} deg C")


async def run(fault: str | None = None, log=print, watch=None) -> dict:
  """Run the example once, in simulation only. watch(sim) sees the simulator once, first."""
  sim, clock = SimSTX44(fault=fault), VirtualClock()
  if watch is not None:
    watch(sim)
  tap = Tap(sim, log)
  mod = importlib.import_module("pylabrobot.legacy.storage.liconic.liconic_backend")
  fake_time = SimpleNamespace(time=clock.time)
  fake_asyncio = SimpleNamespace(sleep=clock.sleep)
  outcome, evidence = "completed", ""
  with patch.object(mod, "time", fake_time), patch.object(mod, "asyncio", fake_asyncio), \
       warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    try:
      # --8<-- snippet
      backend = ExperimentalLiconicBackend(model="STX44_IC", port="/dev/ttyUSB0")
      backend.io = sim  # the only swap: the Serial transport becomes the simulator
      rack = liconic_rack_17mm_22(name="cassette_1")  # 22 positions, 23 mm pitch
      stx = Incubator(backend=backend, name="stx44", size_x=600, size_y=600, size_z=700,
                      racks=[rack], loading_tray_location=Coordinate(0, 0, 0))
      tap.ask("set up: break, CR handshake, activate handling, wait ready")
      await stx.setup()

      plate = cellvis_384_wellplate_120uL_Fb(name="cells_384")
      stx.loading_tray.assign_child_resource(plate)
      tap.ask("take the plate in from the transfer station to cassette 1, position 1")
      await stx.take_in_plate(rack.sites[0])

      tap.ask("fetch the plate back out to the transfer station")
      await stx.fetch_plate_to_loading_tray("cells_384")

      tap.ask("read the temperature")
      temperature = await stx.get_temperature()
      # --8<-- end
    except RuntimeError as e:
      if "No response" not in str(e):
        raise
      outcome = "hold"
      evidence = (f"no reply to ST 1904, not resent (sim ran it {sim.executions['ST 1904']}x); "
                  f"sim: {sim.plate}, PLR: tray")
    except Exception as e:
      if not type(e).__module__.endswith("liconic.errors"):
        raise
      code = sim.replies[sim.commands.index("RD DM200")]
      outcome, evidence = "error", f"DM200={code} {type(e).__name__}: {e}"
  tap.flush()
  for w in caught:
    if issubclass(w.category, (ResourceWarning, DeprecationWarning, PendingDeprecationWarning)):
      continue  # interpreter housekeeping, not something the driver said
    log(f"state upstream warning: {w.message}")
  if outcome == "completed":
    back = sim.history == ["shovel", "cassette 1/1", "shovel", "transfer"]
    back = back and plate.parent is stx.loading_tray
    outcome = "completed" if back and rack.sites[0].resource is None else "error"
    evidence = f"sim: plate path {' > '.join(sim.history)}; {temperature} deg C"
  log(f"done  {outcome}: {evidence}"[:100])
  return {"station": STATION, "outcome": outcome, "evidence": evidence, "sim": sim}


if __name__ == "__main__":
  asyncio.run(run())
