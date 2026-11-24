"""Tissue-culture station: a STAND-IN adapter, because the supplier and interface are open.

It records that a cell batch was released for seeding and that the receiving worklist names
that batch. The message format is made up (see sim.py); a real adapter would wrap whatever the
chosen supplier documents. Simulation only. Batch and worklist ids are made up.
"""

import asyncio
import json
from typing import Callable, Dict, List, Optional

from stations.culture.sim import SimCultureStation

STATION = "culture"


class ReleaseNotConfirmed(Exception):
  pass


class ReleaseRefused(Exception):
  pass


class CultureAdapter:
  """Stand-in: 1 operation, release(batch, worklist), safe to call again."""

  def __init__(self, station: SimCultureStation) -> None:
    self.station = station
    self.records: List[Dict[str, str]] = []

  def release(self, batch: str, worklist_id: str, worklist: List[Dict[str, str]]) -> None:
    wrong = [row["well"] for row in worklist if row["batch"] != batch]
    if not worklist or wrong:
      raise ReleaseRefused(f"worklist {worklist_id} does not match batch {batch}: {wrong}")
    line = json.dumps({"op": "release", "batch": batch, "worklist": worklist_id})
    reply = self.station.handle(line)
    if reply is None:
      raise ReleaseNotConfirmed(f"release of {batch} sent, no acknowledgement")
    msg = json.loads(reply)
    if not msg["ok"]:
      raise ReleaseRefused(f"{msg['error']} {msg['batch']}")
    self.records.append({"batch": batch, "worklist": worklist_id})


async def run(fault: Optional[str] = None, log: Callable[[str], None] = print,
              watch: Optional[Callable[[object], None]] = None) -> dict:
  """Run the example once, in simulation only. watch(sim) sees the simulator once, first."""
  station = SimCultureStation(batches=["CB-0001"], fault=fault)
  if watch is not None:
    watch(station)
  station.log = log
  out = {"station": STATION, "sim": station}
# --8<-- snippet
  adapter = CultureAdapter(station)
  worklist = [{"plate": "seed_plate_1", "well": w, "batch": "CB-0001"}
              for w in ("A1", "A2", "A3")]
  log("ask   release CB-0001 for seeding against worklist WL-7")
  try:
    adapter.release("CB-0001", "WL-7", worklist)
  except ReleaseNotConfirmed as e:
    out.update(outcome="hold", evidence=str(e))
  except ReleaseRefused as e:
    out.update(outcome="error", evidence=str(e))
  else:
    out.update(outcome="completed", evidence="CB-0001 released, worklist WL-7 matches")
# --8<-- end
  log(f"state released {station.released}, executed {station.releases_executed}")
  log(f"done  {out['outcome']}: {out['evidence']}")
  out["adapter"] = adapter
  return out


if __name__ == "__main__":
  asyncio.run(run())
