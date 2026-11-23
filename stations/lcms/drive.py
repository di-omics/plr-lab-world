"""LC-MS bench the way the playbook in plr-reverse-engineer reaches its example: no protocol to
decode. Read the Ready line, close the Start line, and pick each raw file up from the data folder.

The toolkit runs in DRY RUN here (Guards(armed=False)): it transmits nothing and logs the pulse it
would send (plr-reverse-engineer/plr_re/instruments/agilent6530.py:97-103). This example hands
that logged note to the simulated workstation in sim.py, which stands in for the Start contact
closing.
"""

import asyncio
import csv
import logging
import os
import tempfile
from typing import List, Optional

from plr_re.guards import Guards
from plr_re.instruments.agilent6530 import Agilent6530Remote, AgilentPinMap

from .sim import SimulatedWorkstation

STATION = "lcms"
PLATE = "PLATE01"  # made up
WELLS = ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1"]
# Pin numbers and pulse length copied from the toolkit's example pin map
# (plr-reverse-engineer/configs/agilent-pinmap.example.json:2-7); Pi-side choices, not
# instrument facts.
PINS = AgilentPinMap(ready=17, start=27, stop=22, ready_active_low=False, out_active_low=True,
                     pulse_s=0.25)


class _Notes(logging.Handler):
  """Collects the toolkit's dry-run notes (logger "plr_re"), so they can be relayed."""

  def __init__(self) -> None:
    super().__init__(logging.WARNING)
    self.notes: List[str] = []

  def emit(self, record: logging.LogRecord) -> None:
    self.notes.append(record.getMessage())


def write_sequence(path: str) -> List[str]:
  """The injection sequence: 1 row per aliquot, all made-up ids from 1 plate."""
  aliquots = [f"{PLATE}-{w}" for w in WELLS]
  with open(path, "w", newline="", encoding="ascii") as fh:
    out = csv.writer(fh)
    out.writerow(["row", "plate", "well", "aliquot_id", "volume_uL"])
    for row, (well, aliquot) in enumerate(zip(WELLS, aliquots), 1):
      out.writerow([row, PLATE, well, aliquot, 2])  # 2 uL, made up
  return aliquots


async def wait_for_raw_file(folder: str, row: int, aliquot: str, sleep=asyncio.sleep,
                            polls: int = 3) -> Optional[str]:
  """Adapter: the raw file for this row and aliquot, or None after `polls` looks."""
  name = f"{row:03d}_{aliquot}.raw.stub"  # the naming rule set in the simulated software
  for _ in range(polls):
    if os.path.exists(os.path.join(folder, name)):
      return name
    await sleep(0)  # a real wait would be minutes; injected as 0 here
  return None


async def run(fault: str | None = None, log=print) -> dict:
  """Run the example once, in simulation only."""
  notes = _Notes()
  toolkit_log = logging.getLogger("plr_re")
  toolkit_log.addHandler(notes)
  with tempfile.TemporaryDirectory() as tmp:
    raw_dir = os.path.join(tmp, "data")
    os.mkdir(raw_dir)
    aliquots = write_sequence(os.path.join(tmp, "sequence.csv"))
    station = SimulatedWorkstation(raw_dir, PINS.ready, PINS.start, PINS.stop)
    station.load_sequence(aliquots)
    station.fault = fault
    log(f"ask   run sequence.csv: {len(aliquots)} injections from {PLATE}, 1 start each")
    matched, outcome, evidence = {}, "completed", ""
    try:
      # --8<-- snippet
      remote = Agilent6530Remote(PINS, Guards(armed=False), io=station)  # dry run
      for row, aliquot in enumerate(aliquots, 1):
        if not remote.is_ready():  # reads the Ready line
          outcome = "error"
          evidence = f"Ready low before row {row}: {station.fault_text}; no Start sent"
          break
        remote.start_run()  # dry run: logs the Start pulse, sends nothing
        for note in notes.notes:
          log(f"send  {note}")
          station.on_note(note)  # the simulated workstation acts on it
        notes.notes.clear()
        raw = await wait_for_raw_file(raw_dir, row, aliquot)
        if raw is None:  # started, no file: hold, never start this aliquot again
          outcome = "hold"
          evidence = f"row {row} {aliquot} started, no raw file; not re-injected"
          break
        matched[aliquot] = raw
        log(f"recv  {raw}")
      # --8<-- end
    finally:
      toolkit_log.removeHandler(notes)
    if outcome == "completed":
      evidence = f"{len(matched)}/{len(aliquots)} injections matched to a raw file"
    most = max(station.started.values(), default=0)
    log(f"state {station.state()}; starts per aliquot max {most}")
    log(f"done  {outcome}: {evidence}")
  return {"station": STATION, "outcome": outcome, "evidence": evidence, "sim": station,
          "matched": matched}


if __name__ == "__main__":
  asyncio.run(run())
