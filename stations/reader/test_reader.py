"""Tests for the synthetic reader example. Nothing here is a PHERAstar command."""

import asyncio

import pytest

from pylabrobot.bmg_labtech.protocol.framing import ftdi_wrap_payload

from . import drive
from .sim import SYNTHETIC_HEADER, SyntheticReader, UnknownFrame, wrap


def _run(fault=None):
  lines = []
  return asyncio.run(drive.run(fault=fault, log=lines.append)), lines


def test_completed_state_and_exact_frame():
  result, lines = _run()
  sim = result["sim"]
  assert result["outcome"] == "completed"
  assert sim.plates_read == 3  # capture, replay, draft
  assert not sim.tray_out and sim.plate_on_tray
  assert sim.executed["driver"]["TODO_3"] == 1
  # upstream BMG framing around the made-up ASCII payload "TODO_3"
  assert wrap(b"TODO_3") == bytes.fromhex("02000e3f544f444f5f330002170d")
  assert "send  02 00 0e 3f 54 4f 44 4f 5f 33 00 02 17 0d" in lines
  assert len(lines) < 32 and all(len(x) <= 100 for x in lines)


def test_lost_reply_holds_and_reads_once():
  result, lines = _run("lost_reply")
  assert result["outcome"] == "hold"
  assert result["sim"].executed["driver"]["TODO_3"] == 1
  assert sum(1 for x in lines if x.startswith("send") and "5f 33" in x) == 2  # replay + draft


def test_device_error_keeps_code():
  result, _ = _run("device_error")
  assert result["outcome"] == "error"
  assert "(6, 0, 0, 0, 0)" in result["evidence"]
  assert "TODO_3" not in result["sim"].executed.get("driver", {})


def test_unknown_frame_raises():
  sim = SyntheticReader()
  with pytest.raises(UnknownFrame):
    sim.handle(wrap(b"\x01\x00"))
  with pytest.raises(UnknownFrame):
    sim.handle(b"hello")


def test_bad_checksum_raises():
  frame = bytearray(ftdi_wrap_payload(b"TODO_4", header=SYNTHETIC_HEADER))
  frame[-2] ^= 0xFF
  with pytest.raises(Exception):
    SyntheticReader().handle(bytes(frame))


def test_draft_moves_tray_only_if_needed():
  from .pherastar_draft import PHERAstarDraft
  from .sim import SimTransport

  sim, sent = SyntheticReader(), []
  reader = PHERAstarDraft(SimTransport(sim, lambda tag, data: sent.append((tag, data))))

  async def go():
    await reader.ensure_tray_out()
    await reader.ensure_tray_out()

  asyncio.run(go())
  assert sim.tray_out and sim.executed["capture"]["TODO_1"] == 1


def test_draft_logs_unverified_warning(caplog):
  from .pherastar_draft import PHERAstarDraft
  from .sim import SimTransport

  reader = PHERAstarDraft(SimTransport(SyntheticReader(), lambda tag, data: None))
  with caplog.at_level("WARNING"):
    asyncio.run(reader.setup())
  assert any("UNVERIFIED" in r.getMessage() for r in caplog.records)
