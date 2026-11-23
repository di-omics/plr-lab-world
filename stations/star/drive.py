"""Drive the REAL upstream STARDriver against a SIMULATED STARlet at the USB boundary.

Only the transport is replaced: `STARDriver(io=...)` gets the simulator where it would otherwise
open `pylabrobot.io.usb.USB`. Every frame logged below is what the driver itself assembled.
Volumes (50 uL asked, 100 uL in each source well) and the deck layout are made up and round.
Nothing here ran on a physical STAR.
"""

import time
from typing import Optional
from unittest import mock

from pylabrobot.hamilton.protocol.text import router
from pylabrobot.hamilton.star import STARDriver, STARlet
from pylabrobot.resources import cor_96_wellplate_360uL_Fb
from pylabrobot.resources.hamilton import (
  STARLetDeck,
  hamilton_96_tiprack_300uL,
  hamilton_plate_carrier_L5_ac,
  hamilton_tip_carrier_L5,
)

from stations.star.sim import SimulatedSTARlet

STATION = "star"
SHOWN = ("C0RM", "C0VI", "C0DI", "C0TP", "C0AS", "C0DS", "C0TR")  # frames worth printing


# --8<-- snippet
def build(link):
  deck = STARLetDeck()
  tip_car = hamilton_tip_carrier_L5(name="tip_carrier")
  tip_car[0] = tips = hamilton_96_tiprack_300uL(name="tips")
  deck.assign_child_resource(tip_car, track=1)
  plt_car = hamilton_plate_carrier_L5_ac(name="plate_carrier")
  plt_car[0] = source = cor_96_wellplate_360uL_Fb(name="source")
  plt_car[1] = dest = cor_96_wellplate_360uL_Fb(name="destination")
  deck.assign_child_resource(plt_car, track=8)
  # On hardware: STARDriver() with no io opens the USB device itself.
  star = STARlet(deck=deck, driver=STARDriver(io=link))
  return star, tips, source, dest


async def sample_prep(star, tips, source, dest):
  await star.setup()
  await star.pipettes.pick_up_tips(tips["A1:H1"])
  await star.pipettes.aspirate(source["A1:H1"], [50.0] * 8)
  await star.pipettes.dispense(dest["A1:H1"], [50.0] * 8)
  await star.pipettes.return_tips()
# --8<-- end


def _point(resource, deck) -> tuple:
  """Where the driver aims a channel at a resource: its centre, on the deck, in 0.1 mm."""
  c = resource.get_location_wrt(deck) + resource.get_anchor("c", "c", "b")
  return round(c.x * 10), round(c.y * 10)


class _SimClock:
  """The reply router's clock, pushed forward when the simulator loses a reply (no real wait)."""

  def __init__(self, sim: SimulatedSTARlet):
    self.sim = sim

  def time(self) -> float:
    return time.time() + self.sim.clock_offset


async def run(fault: Optional[str] = None, log=print) -> dict:
  """Run the example once, in simulation only."""
  def tap(tag: str, text: str) -> None:
    if tag == "state " or text[:4] in SHOWN or text.startswith("(nothing"):
      log(tag + (text if len(text) <= 94 else text[:91] + "..."))

  sim = SimulatedSTARlet(fault=fault, tap=tap)
  star, tips, source, dest = build(sim)
  sim.load(
    wells={f"{p.name}:{w.get_identifier()}": _point(w, star.deck) for p in (source, dest)
           for w in p.children},
    tip_spots={s.get_identifier(): _point(s, star.deck) for s in tips.children},
    volumes={f"source:{r}1": 100.0 for r in "ABCDEFGH"},
  )
  log("ask   set up; 8 tips; 50 uL from source col 1 to destination col 1; return tips")
  outcome, evidence = "completed", ""
  with mock.patch.object(router, "time", _SimClock(sim)):
    try:
      await sample_prep(star, tips, source, dest)
      got = sorted({sim.volume[f"destination:{r}1"] for r in "ABCDEFGH"})
      evidence = (f"destination col 1: {got} uL each (50 uL asked + liquid class); "
                  f"{len(sim.tips_in_rack)} tips in rack")
    except TimeoutError:
      outcome = "hold"
      evidence = (f"no reply to C0AS after {sim.executed.get('C0AS', 0)} send; liquid may have "
                  "moved, not resent; check by hand")
    except Exception as error:  # the firmware error the driver decoded from the reply
      outcome = "error"
      evidence = f"{type(error).__name__}: {getattr(error, 'raw_response', error)}"
    finally:
      if star.driver.connected:
        await star.stop()
  log(f"done  {outcome}: {evidence}"[:100])
  return {"station": STATION, "outcome": outcome, "evidence": evidence, "sim": sim}


if __name__ == "__main__":
  import asyncio

  asyncio.run(run())
