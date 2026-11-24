"""SIMULATED clock and physical shelves of a passive 24-slot plate hotel.

A passive hotel has no controller and no wire. What can go wrong is physical: a plate is or is
not on a shelf, and a pickup is or is not confirmed. This file holds that physical truth and a
clock the scheduler reads, so nothing sleeps. Messages are plain dicts from the scheduler.
"""

from typing import Any, Callable, Dict, List, Optional

SLOTS = 24


class SimUnknownCommand(Exception):
  """The scheduler sent a command this simulator does not know."""


class SimClock:
  def __init__(self) -> None:
    self.now_s = 0.0

  def advance(self, seconds: float) -> None:
    self.now_s += seconds


class SimHotel:
  """Physical occupancy per shelf (index 0..23) and a count of executed pickups."""

  def __init__(self, fault: Optional[str] = None) -> None:
    self.fault = fault
    self.shelves: List[Optional[str]] = [None] * SLOTS
    self.pickups = 0
    self.log: Optional[Callable[[str], None]] = None
    self.scheduler: Optional[Any] = None  # the scheduler driving this hotel sets itself here

  def apply(self, cmd: Dict[str, object]) -> Optional[Dict[str, object]]:
    """Carry out 1 command; return the confirmation, or None when it is lost."""
    op, slot, plate = cmd.get("op"), cmd.get("slot"), cmd.get("plate")
    if self.log:
      self.log(f"send  {op} slot={slot} plate={plate}")
    if set(cmd) != {"op", "slot", "plate"} or not isinstance(slot, int) or not 0 <= slot < SLOTS:
      raise SimUnknownCommand(f"bad command {cmd}")
    if op == "place":
      if self.shelves[slot] is not None:
        raise SimUnknownCommand(f"shelf {slot} physically full")  # a crash, not a reply
      self.shelves[slot] = str(plate)
    elif op == "pickup":
      if self.shelves[slot] != plate:
        raise SimUnknownCommand(f"shelf {slot} does not hold {plate}")
      self.shelves[slot] = None
      self.pickups += 1
      if self.fault == "lost_reply":
        return None  # the arm took it; the confirmation never arrives
    else:
      raise SimUnknownCommand(f"unknown op {op}")
    ack = {"op": op, "slot": slot, "plate": plate, "ok": True}
    if self.log:
      self.log(f"recv  {op} ok slot={slot}")
    return ack
