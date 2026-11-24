"""A SIMULATED LC-MS acquisition workstation, reached the way the playbook's example reaches one:
a Ready line it raises when it can take an injection, a Start line that starts the next row of the
sequence loaded in the vendor software, and a data folder where each injection's raw file lands.

Everything here is made up: pin numbers come from the toolkit's example pin map, file names, the
fault text and the timing are invented, and a raw file is a small text stub, not instrument data.
"""

import logging
import os
import re
from collections import Counter
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# The dry-run note the toolkit logs instead of pulsing
# (plr-reverse-engineer/plr_re/instruments/agilent6530.py:100-102 with
# plr-reverse-engineer/plr_re/guards.py:59-60). The simulator parses it; any other note raises.
NOTE = re.compile(r"^\[dry-run\] would pulse (START|STOP) on BCM(\d+) for ([0-9.]+)s$")


class UnknownSignal(Exception):
  """The workstation got a signal it does not know. It never answers OK to one."""


class SimulatedWorkstation:
  """State: ready or not, the loaded sequence, the next row, and raw files written."""

  def __init__(self, raw_dir: str, ready_pin: int, start_pin: int, stop_pin: int) -> None:
    self.raw_dir = raw_dir
    self.ready_pin, self.start_pin, self.stop_pin = ready_pin, start_pin, stop_pin
    self.sequence: List[str] = []
    self.next_row = 0
    self.ready = True
    self.fault: Optional[str] = None  # "lost_reply" | "device_error"
    self.fault_at = 4  # made up: the fault hits the 4th injection
    self.fault_text = ""
    self.started: Counter = Counter()  # Start pulses acted on, per aliquot
    self.files: List[str] = []
    self.raw: Dict[str, str] = {}  # aliquot -> raw file name written for it

  def load_sequence(self, aliquots: List[str]) -> None:
    """The operator loads the sequence in the vendor software (simulated)."""
    self.sequence, self.next_row = list(aliquots), 0

  # ContactClosureIO shape (plr-reverse-engineer/plr_re/transports.py:188-191), so the toolkit
  # reads Ready from here.
  def read_line(self, bcm_pin: int, active_low: bool) -> bool:
    if bcm_pin != self.ready_pin:
      raise UnknownSignal(f"BCM{bcm_pin} is not wired to Ready")
    if self.fault == "device_error" and self.next_row + 1 >= self.fault_at:
      self.ready, self.fault_text = False, "not ready: simulated pump pressure fault"
    return self.ready

  def pulse(self, bcm_pin: int, seconds: float, active_low: bool) -> None:
    raise UnknownSignal("this example runs the toolkit in dry run; nothing is pulsed")

  def close(self) -> None:
    pass

  def on_note(self, note: str) -> None:
    """Act on the toolkit's dry-run Start note, as if the Start contact had closed."""
    m = NOTE.match(note)
    if m is None:
      raise UnknownSignal(f"unknown note: {note!r}")
    line, pin = m.group(1), int(m.group(2))
    if line != "START" or pin != self.start_pin:
      raise UnknownSignal(f"{line} on BCM{pin} is not wired here")
    if not self.ready or self.next_row >= len(self.sequence):
      logger.info("Start ignored: not ready or sequence finished")
      return
    aliquot = self.sequence[self.next_row]
    self.next_row += 1
    self.started[aliquot] += 1
    if self.fault == "lost_reply" and self.next_row == self.fault_at:
      logger.info("injection %d started, raw file never written (fault)", self.next_row)
      return
    name = f"{self.next_row:03d}_{aliquot}.raw.stub"
    with open(os.path.join(self.raw_dir, name), "w", encoding="ascii") as fh:
      fh.write(f"SIMULATED raw-file stub\nrow {self.next_row}\naliquot {aliquot}\n")
    self.files.append(name)
    self.raw[aliquot] = name

  def snapshot(self) -> dict:
    """Workstation state for a replay: Ready, and per sequence row its starts and raw file."""
    return {"ready": self.ready,
            "rows": [{"aliquot": a, "started": self.started[a], "raw": self.raw.get(a)}
                     for a in self.sequence]}

  def state(self) -> str:
    return (
      f"ready {self.ready}, rows started {self.next_row}/{len(self.sequence)}, "
      f"raw files {len(self.files)}"
    )
