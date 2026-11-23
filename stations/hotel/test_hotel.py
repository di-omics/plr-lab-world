import asyncio

import pytest

from pylabrobot.resources.greiner import Greiner_384_wellplate_28ul_Fb

from stations.hotel import drive
from stations.hotel.sim import SimHotel, SimUnknownCommand


def _quiet(_: str) -> None:
  pass


def test_completed_frees_slot() -> None:
  lines: list = []
  r = asyncio.run(drive.run(None, log=lines.append))
  assert r["outcome"] == "completed"
  assert r["sim"].shelves[5] is None and r["hotel"][5].resource is None
  assert r["scheduler"].slots == {} and r["sim"].pickups == 1
  assert "send  pickup slot=5 plate=assay_plate_1" in lines
  assert len(r["hotel"].sites) == 24


def test_lost_reply_holds_slot_and_picks_once() -> None:
  r = asyncio.run(drive.run("lost_reply", log=_quiet))
  assert r["outcome"] == "hold" and r["sim"].pickups == 1
  assert r["scheduler"].slots[5]["state"] == "pickup_sent"
  assert r["hotel"][5].resource.name == "assay_plate_1"  # model not changed without proof
  assert r["hotel"][5].resource.num_items == 384


def test_device_error_is_upstream_value_error() -> None:
  r = asyncio.run(drive.run("device_error", log=_quiet))
  assert r["outcome"] == "error" and "spot 5 already has a resource" in r["evidence"]
  assert r["sim"].shelves[5] == "earlier_plate"  # nothing was moved


def test_unknown_command_raises() -> None:
  with pytest.raises(SimUnknownCommand):
    SimHotel().apply({"op": "shake", "slot": 1, "plate": "p"})


def test_holder_assign_does_not_refuse_second_plate() -> None:
  hotel = drive.build_hotel()
  hotel[3] = Greiner_384_wellplate_28ul_Fb("a")
  hotel[3].assign_child_resource(Greiner_384_wellplate_28ul_Fb("b"))  # reassign=True default
  assert [c.name for c in hotel[3].children] == ["a", "b"]
