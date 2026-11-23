"""Tests for the inc station: REAL legacy upstream LiCONiC backend, SIMULATED STX44 PLC."""

from __future__ import annotations

import asyncio

import pytest

from .drive import run
from .sim import SimSTX44, UnknownCommand


def _run(fault: str | None = None) -> dict:
  return asyncio.run(run(fault=fault, log=lambda line: None))


def test_completed_plate_goes_in_and_comes_back() -> None:
  r = _run()
  sim = r["sim"]
  assert r["outcome"] == "completed"
  assert sim.history == ["shovel", "cassette 1/1", "shovel", "transfer"]
  assert sim.plate == "transfer"
  assert sim.dm["0"] == 1 and sim.dm["5"] == 1 and sim.dm["23"] == 788 and sim.dm["25"] == 22
  assert sim.commands[:3] == ["CR", "ST 1801", "RD 1915"]
  i = sim.commands.index("ST 1904")
  assert sim.commands[i - 4 : i + 3] == [
    "WR DM0 1", "WR DM23 788", "WR DM25 22", "WR DM5 1", "ST 1904", "RD 1915", "ST 1903",
  ]
  assert sim.commands[-1] == "RD DM982"
  assert "37.0 deg C" in r["evidence"]


def test_lost_reply_holds_and_never_resends() -> None:
  r = _run("lost_reply")
  sim = r["sim"]
  assert r["outcome"] == "hold"
  assert sim.executions["ST 1904"] == 1
  assert sim.commands[-1] == "ST 1904"  # nothing was sent after the lost reply
  assert sim.plate == "cassette 1/1"


def test_device_error_keeps_the_code() -> None:
  r = _run("device_error")
  assert r["outcome"] == "error"
  assert "DM200=00103" in r["evidence"]
  assert "LiconicHandlerImportPlateError" in r["evidence"]
  assert r["sim"].plate == "shovel"


def test_unknown_command_raises() -> None:
  sim = SimSTX44()
  asyncio.run(sim.write(b"CR\r"))
  with pytest.raises(UnknownCommand):
    asyncio.run(sim.write(b"ST 1999\r"))
  with pytest.raises(UnknownCommand):
    asyncio.run(sim.write(b"RD 1915"))  # no CR terminator
  assert sim.replies == ["CC"]
