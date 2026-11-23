"""The same 3 outcomes at every station, checked through the 1 call the harness uses."""
import asyncio

import pytest

from harness.walk import ORDER, walk


def test_clean_walk_completes_all_9() -> None:
    record = asyncio.run(walk())
    outcomes = [r for r in record if r["phase"] == "outcome"]
    assert [r["station"] for r in outcomes] == ORDER
    assert all(r["outcome"] == "completed" and r["evidence"] for r in outcomes)
    assert [r["seq"] for r in record] == list(range(1, 19))


@pytest.mark.parametrize("fault,expected", [("lost_reply", "hold"), ("device_error", "error")])
@pytest.mark.parametrize("station", ORDER)
def test_fault_stops_the_walk_at_that_station(station: str, fault: str, expected: str) -> None:
    record = asyncio.run(walk(fault_at=station, fault=fault))
    assert record[-1]["station"] == station
    assert record[-1]["phase"] == "outcome" and record[-1]["outcome"] == expected
    assert record[-1]["evidence"]
    asked = [r["station"] for r in record if r["phase"] == "request"]
    assert asked == ORDER[: ORDER.index(station) + 1]
