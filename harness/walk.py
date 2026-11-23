"""1 plate through all 9 stations, in simulation, with 1 run record.

    python -m harness.walk

Every station module exposes the same call: run(fault=None, log=print) -> dict with an outcome of
"completed", "hold" or "error". The harness writes a request line before each call and an outcome
line after it. On anything but "completed" it stops: a later station is never asked while an
earlier outcome is unknown.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path

ORDER = ["culture", "seed", "star", "inc", "rail", "xarm", "hotel", "reader", "lcms"]
SUBJECT = {"culture": "Batch B01", "lcms": "Aliquot A01"}


async def walk(run_id: str = "SIM-001", fault_at: str | None = None,
               fault: str = "lost_reply") -> list[dict]:
    """Return the run record: 2 lines per station asked (request, then outcome)."""
    record: list[dict] = []

    def line(station: str, phase: str, **more: object) -> None:
        record.append({"seq": len(record) + 1, "run": run_id, "station": station,
                       "subject": SUBJECT.get(station, "Plate P01"), "phase": phase,
                       "simulated": True, **more})

    for key in ORDER:
        drive = importlib.import_module(f"stations.{key}.drive")
        line(key, "request")
        result = await drive.run(fault=fault if key == fault_at else None, log=lambda _text: None)
        line(key, "outcome", outcome=result["outcome"], evidence=str(result["evidence"]))
        if result["outcome"] != "completed":
            break
    return record


def table(record: list[dict]) -> list[str]:
    done = {r["station"]: r for r in record if r["phase"] == "outcome"}
    stopped = next((k for k in ORDER if k in done and done[k]["outcome"] != "completed"), None)
    out = []
    for n, key in enumerate(ORDER, 1):
        if key in done:
            text = f"{n} {key:8s} {done[key]['outcome']:10s} {done[key]['evidence']}"
        else:
            text = f"{n} {key:8s} {'not asked':10s} waiting behind {stopped}"
        out.append("  " + (text if len(text) <= 98 else text[:95] + "..."))
    return out


def main() -> None:
    runs = Path(__file__).resolve().parent / "runs"
    runs.mkdir(exist_ok=True)
    cases = [("SIM-001", None, "clean"), ("SIM-002", "reader", "the reader's reply is lost")]
    for run_id, fault_at, label in cases:
        record = asyncio.run(walk(run_id, fault_at))
        (runs / f"{run_id}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in record))
        print(f"run {run_id}, {label}: {len(record)} record lines in harness/runs/{run_id}.jsonl")
        print("\n".join(table(record)))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
