"""A passive 24-slot plate hotel: a PyLabRobot resource plus a scheduler that owns the slots.

The hotel is built from upstream PlateCarrier + PlateHolder (pylabrobot/resources/carrier.py).
Reservations and dwell timers are not in PyLabRobot; the scheduler below keeps them, with an
injected clock. Simulation only; sizes, pitch and dwell are made up.
"""

import asyncio
from typing import Callable, Dict, Optional

from pylabrobot.resources import Coordinate
from pylabrobot.resources.carrier import PlateCarrier, PlateHolder, create_homogeneous_resources
from pylabrobot.resources.greiner import Greiner_384_wellplate_28ul_Fb

from stations.hotel.sim import SLOTS, SimClock, SimHotel

STATION = "hotel"
DWELL_S = 600  # made up


def build_hotel() -> PlateCarrier:
  shelves = create_homogeneous_resources(  # 24 shelves, 20 mm pitch, all made up
    PlateHolder, [Coordinate(0, 0, 20 * i) for i in range(SLOTS)], 128, 86, 18,
    name_prefix="shelf", pedestal_size_z=0)
  return PlateCarrier("hotel", size_x=140, size_y=100, size_z=500, sites=shelves)


class Scheduler:
  """Slot reservations and dwell timers. The resource model is checked before any move."""

  def __init__(self, hotel: PlateCarrier, sim: SimHotel, clock: SimClock) -> None:
    self.hotel, self.sim, self.clock = hotel, sim, clock
    self.slots: Dict[int, dict] = {}  # slot -> {"plate", "state", "placed_at"}
    sim.scheduler = self  # so a replay can read the reservations next to the shelves

  def reserve(self, slot: int, plate: str) -> None:
    if slot in self.slots:
      raise RuntimeError(f"slot {slot} already reserved")
    self.slots[slot] = {"plate": plate, "state": "reserved", "placed_at": None}

  def place(self, slot: int, plate) -> None:
    self.hotel[slot] = plate  # upstream raises ValueError if the spot is taken
    self.sim.apply({"op": "place", "slot": slot, "plate": plate.name})
    self.slots[slot].update(state="occupied", placed_at=self.clock.now_s)

  def dwell_done(self, slot: int) -> bool:
    return self.clock.now_s - self.slots[slot]["placed_at"] >= DWELL_S

  def pick_up(self, slot: int) -> bool:
    entry = self.slots[slot]
    entry["state"] = "pickup_sent"
    ack = self.sim.apply({"op": "pickup", "slot": slot, "plate": entry["plate"]})
    if not ack:
      return False  # not confirmed: the slot stays reserved, never resend
    self.hotel[slot] = None  # upstream unassigns the plate from the shelf
    del self.slots[slot]
    return True


class HotelState:
  """What a replay watches: the shelves (sim), the clock and the scheduler's reservations."""

  def __init__(self, sim: SimHotel, clock: SimClock) -> None:
    self.sim, self.clock = sim, clock

  def snapshot(self) -> dict:
    sched = self.sim.scheduler
    return {"slots": SLOTS, "occupied": [i for i, p in enumerate(self.sim.shelves) if p],
            "reserved": sorted(sched.slots) if sched else [],
            "clock_s": round(float(self.clock.now_s), 1), "dwell_s": round(float(DWELL_S), 1),
            "pickups": self.sim.pickups}


async def run(fault: Optional[str] = None, log: Callable[[str], None] = print,
              watch: Optional[Callable[[object], None]] = None) -> dict:
  """Run the example once, in simulation only. watch(state) sees the hotel state once, first."""
  clock, sim, hotel = SimClock(), SimHotel(fault), build_hotel()
  if watch is not None:
    watch(HotelState(sim, clock))
  sim.log = log
  out = {"station": STATION, "sim": sim, "hotel": hotel}
  if fault == "device_error":  # a plate already recorded on shelf 5, outside the scheduler
    hotel[5] = Greiner_384_wellplate_28ul_Fb("earlier_plate")
    sim.shelves[5] = "earlier_plate"
# --8<-- snippet
  hotel_sched = Scheduler(hotel, sim, clock)
  plate = Greiner_384_wellplate_28ul_Fb("assay_plate_1")
  log("ask   reserve slot 5, place, dwell 600 s, pick up")
  hotel_sched.reserve(5, plate.name)
  try:
    hotel_sched.place(5, plate)  # hotel[5] = plate
  except ValueError as e:  # "spot 5 already has a resource" (carrier.py:86)
    out.update(outcome="error", evidence=f"ValueError: {e}")
  else:
    clock.advance(DWELL_S)
    log(f"state t={clock.now_s:g} s, dwell done: {hotel_sched.dwell_done(5)}")
    if hotel_sched.pick_up(5):
      out.update(outcome="completed", evidence="pickup confirmed, slot 5 free")
    else:
      out.update(outcome="hold", evidence=f"pickup sent {sim.pickups} time, no "
                 "confirmation; slot 5 stays reserved")
# --8<-- end
  log(f"state model slot 5: {hotel[5].resource.name if hotel[5].resource else None}; "
      f"shelf 5: {sim.shelves[5]}; reserved: {sorted(hotel_sched.slots)}")
  log(f"done  {out['outcome']}: {out['evidence']}")
  out["scheduler"] = hotel_sched
  return out


if __name__ == "__main__":
  asyncio.run(run())
