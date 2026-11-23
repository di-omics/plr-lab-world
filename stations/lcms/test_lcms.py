"""Tests for the LC-MS bench example (simulation and toolkit dry run only)."""

import asyncio
import os
import tempfile

import pytest

from . import drive
from .sim import SimulatedWorkstation, UnknownSignal

START_NOTE = "[dry-run] would pulse START on BCM27 for 0.25s"


def _run(fault=None):
  lines = []
  return asyncio.run(drive.run(fault=fault, log=lines.append)), lines


def test_completed_matches_every_injection():
  result, lines = _run()
  sim = result["sim"]
  assert result["outcome"] == "completed"
  assert sim.next_row == 8 and len(sim.files) == 8
  assert set(sim.started.values()) == {1}
  assert result["matched"]["PLATE01-A1"] == "001_PLATE01-A1.raw.stub"
  assert lines.count(f"send  {START_NOTE}") == 8  # exact signal the toolkit emits in dry run
  assert len(lines) < 32 and all(len(x) <= 100 for x in lines)


def test_lost_reply_holds_without_second_injection():
  result, _ = _run("lost_reply")
  sim = result["sim"]
  assert result["outcome"] == "hold"
  assert sim.started["PLATE01-D1"] == 1
  assert sim.next_row == 4 and len(sim.files) == 3


def test_device_error_keeps_fault_text():
  result, _ = _run("device_error")
  assert result["outcome"] == "error"
  assert "pump pressure fault" in result["evidence"]
  assert "PLATE01-D1" not in result["sim"].started


def test_unknown_signal_raises():
  with tempfile.TemporaryDirectory() as tmp:
    sim = SimulatedWorkstation(tmp, ready_pin=17, start_pin=27, stop_pin=22)
    sim.load_sequence(["X"])
    with pytest.raises(UnknownSignal):
      sim.on_note("[dry-run] would pulse START on BCM5 for 0.25s")
    with pytest.raises(UnknownSignal):
      sim.on_note("hello")
    with pytest.raises(UnknownSignal):
      sim.read_line(5, False)
    assert os.listdir(tmp) == []


def test_sequence_csv_has_8_rows():
  with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "s.csv")
    ids = drive.write_sequence(path)
    assert len(ids) == 8 and len(open(path).read().splitlines()) == 9
