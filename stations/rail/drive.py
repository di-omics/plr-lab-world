"""Home a UFACTORY linear track if needed, travel to a taught station, confirm the arrival.

PyLabRobot has no linear-track driver at 182f92e, so linear_track.py is written here in the
shape the upstream device-driver guide asks for, on top of the maker's published SDK. The SDK
object is replaced by stations.rail.sim. Simulation only. Positions and speeds are made up.
"""

import asyncio
from typing import Callable, Optional

from stations.rail.linear_track import LinearTrack, LinearTrackError, LinearTrackTimeout
from stations.rail.sim import SimLinearTrack

STATION = "rail"
READER_STATION_MM = 450  # made-up taught position
SPEED_MM_S = 200  # made up


# --8<-- snippet
async def travel(track: LinearTrack) -> int:
  await track.setup()  # enables the track if it was off
  await track.home()  # no-op when already homed
  at = await track.move_to(READER_STATION_MM, speed=SPEED_MM_S)
  await track.stop()  # restores the enable state found at setup
  return at

# track = LinearTrack(ip="192.168.1.220", travel_mm=700)
# --8<-- end


async def run(fault: Optional[str] = None, log: Callable[[str], None] = print,
              watch: Optional[Callable[[object], None]] = None) -> dict:
  """Run the example once, in simulation only. watch(sim) sees the simulator once, first."""
  sim = SimLinearTrack(travel_mm=700, fault=fault)
  if watch is not None:
    watch(sim)
  sim.log = log
  track = LinearTrack(travel_mm=700, arm=sim, reply_timeout=0.2, poll_interval=0)
  out = {"station": STATION, "sim": sim}
  log(f"ask   setup, home, move to {READER_STATION_MM} mm at {SPEED_MM_S} mm/s, stop")
  try:
    at = await travel(track)
  except LinearTrackTimeout as e:
    out.update(outcome="hold", evidence=f"{e}; move sent {sim.pos_moves} time, not "
               "confirmed")
  except LinearTrackError as e:
    out.update(outcome="error", evidence=f"{e} (error register)")
  else:
    out.update(outcome="completed", evidence=f"position report {at} mm == taught "
               f"{READER_STATION_MM} mm, error register {sim.error}")
  finally:
    sim.release_hung()
  sim.log = None
  log(f"state pos {sim.pos} mm, enabled {sim.enabled}, on_zero {sim.on_zero}, "
      f"error {sim.error}, moves {sim.pos_moves}")
  log(f"done  {out['outcome']}: {out['evidence']}")
  return out


if __name__ == "__main__":
  asyncio.run(run())
