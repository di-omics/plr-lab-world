"""Tests for the seed station: REAL upstream EL406 driver, SIMULATED instrument."""

from __future__ import annotations

import asyncio

import pytest

from .drive import run
from .sim import SimEL406, UnknownFrame

# PERI_DISPENSE written out by hand from peristaltic_dispenser.py:446-461 and protocol.py:15-25:
# header 01 02 | cmd 8f 00 | 01 | 00 00 | len 18 00 | checksum d2 fb, then the 24 data bytes:
# plate 01 (384 std), 40 uL 28 00, flow High 02, cassette Any 00, x 00, y 00, z 333 4d 01,
# pre-dispense 10 uL 0a 00, 2 pre-dispenses 02, columns 1-24 ff ff ff 00 00 00, rows all 00,
# pump 01, padding 00 00 00 00.
DISPENSE_FRAME = bytes.fromhex(
  "01028f000100001800d2fb" "012800020000004d010a0002ffffff000000000100000000"
)


def _run(fault: str | None = None) -> dict:
  return asyncio.run(run(fault=fault, log=lambda line: None))


def test_completed_seeds_every_well_and_sends_the_exact_frame() -> None:
  r = _run()
  sim = r["sim"]
  assert r["outcome"] == "completed"
  assert sim.serial["baud"] == 38400 and sim.serial["line"] == (8, 2, 0)
  assert sim.plate_type == 1 and sim.dispenser == "peristaltic"
  assert sim.primed_ul == 500
  assert sim.column_ul == {c: 40 for c in range(1, 25)}
  assert sim.steps == [
    "reset", "peristaltic prime 500 uL", "peristaltic dispense 40 uL x 24 columns",
    "home type 4", "end of batch",
  ]
  assert DISPENSE_FRAME in sim.frames
  assert bytes.fromhex("0102730001000000" "0089ff") in sim.frames  # TEST_COMM, no data
  assert not sim.batch_open


def test_lost_reply_holds_and_never_resends() -> None:
  r = _run("lost_reply")
  sim = r["sim"]
  assert r["outcome"] == "hold"
  assert sim.executions[0x8F] == 1
  assert sum(1 for f in sim.frames if f == DISPENSE_FRAME) == 1
  assert sim.column_ul == {c: 40 for c in range(1, 25)}  # the instrument did dispense


def test_device_error_keeps_the_code() -> None:
  r = _run("device_error")
  assert r["outcome"] == "error"
  assert "0x1355" in r["evidence"] and "Peri-pump module is not configured" in r["evidence"]
  assert r["sim"].column_ul == {}


def test_unknown_frame_raises() -> None:
  sim = SimEL406()
  bad_cmd = bytes([0x01, 0x02, 0x34, 0x12, 0x01, 0, 0, 0, 0])
  checksum = (-sum(bad_cmd)) & 0xFFFF
  with pytest.raises(UnknownFrame):
    asyncio.run(sim.write(bad_cmd + checksum.to_bytes(2, "little")))
  with pytest.raises(UnknownFrame):  # known command, broken checksum
    asyncio.run(sim.write(bytes.fromhex("0102730001000000" "00ffff")))
  assert sim.replies == []
