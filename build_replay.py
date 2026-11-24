#!/usr/bin/env python3
"""Build replay.html from the recorded traces. Standard library only.

    .venv/bin/python build_replay.py               reads traces/<key>.<case>.json (27 files)
    .venv/bin/python build_replay.py --fixtures    reads replay_src/fixtures/ instead
    .venv/bin/python build_replay.py --body FILE   also writes the page without its document wrapper
    .venv/bin/python build_replay.py --out FILE    writes the full page somewhere else
    .venv/bin/python build_replay.py --traces DIR  reads the trace files from another folder

The page opens offline: the traces, the style and the script are all inside the 1 file.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "replay_src"
ORDER = ["culture", "seed", "star", "inc", "rail", "xarm", "hotel", "reader", "lcms"]
CASES = ["clean", "lost_reply", "device_error"]
TAGS = {"ask", "send", "recv", "state", "done"}
OUTCOMES = {"completed", "hold", "error"}
STATUS = {
    "in_plr": "Decoded, in PyLabRobot",
    "in_plr_legacy": "Decoded, in PyLabRobot, older interface",
    "vendor_sdk": "Maker's SDK, nothing to decode",
    "not_in_plr": "Not decoded yet",
    "nothing_to_decode": "Nothing to decode",
    "open_choice": "Instrument not chosen yet",
}


def fail(msg: str) -> None:
    raise SystemExit(f"build_replay: {msg}")


def check_trace(t: object, key: str, case: str, where: str) -> dict:
    if not isinstance(t, dict):
        fail(f"{where}: not a JSON object")
    for field in ("station", "name", "case", "outcome", "evidence", "simulated", "steps"):
        if field not in t:
            fail(f"{where}: missing field {field!r}")
    if t["station"] != key or t["case"] != case:
        fail(f"{where}: says station {t['station']!r} case {t['case']!r}")
    if t["outcome"] not in OUTCOMES:
        fail(f"{where}: outcome {t['outcome']!r} is not completed, hold or error")
    if t["simulated"] is not True:
        fail(f"{where}: simulated must be true")
    steps = t["steps"]
    if not isinstance(steps, list) or not steps:
        fail(f"{where}: steps must be a non-empty list")
    for n, s in enumerate(steps):
        if not isinstance(s, dict) or s.get("tag") not in TAGS or not isinstance(s.get("text"), str):
            fail(f"{where}: step {n} needs a tag in {sorted(TAGS)} and a text")
        if s.get("i") != n:
            fail(f"{where}: step {n} has i={s.get('i')!r}")
        if "state" not in s or not (s["state"] is None or isinstance(s["state"], dict)):
            fail(f"{where}: step {n} state must be an object or null")
    return t


def load_traces(folder: Path) -> dict:
    missing = [f"{k}.{c}.json" for k in ORDER for c in CASES if not (folder / f"{k}.{c}.json").is_file()]
    if missing:
        fail(f"{len(missing)} of 27 trace files missing in {folder.name}/: " + ", ".join(missing))
    out: dict = {}
    for k in ORDER:
        out[k] = {}
        for c in CASES:
            path = folder / f"{k}.{c}.json"
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError as e:
                fail(f"{folder.name}/{path.name}: not valid JSON ({e})")
            out[k][c] = check_trace(data, k, c, f"{folder.name}/{path.name}")
    return out


def load_stations() -> list[dict]:
    rows = []
    for k in ORDER:
        s = json.loads((ROOT / "stations" / k / "station.json").read_text())
        if s.get("key") != k or s.get("status") not in STATUS:
            fail(f"stations/{k}/station.json: bad key or status")
        rows.append({"key": k, "name": s["name"], "status": s["status"],
                     "status_words": STATUS[s["status"]], "status_line": s["status_line"]})
    return rows


def body(data: dict, fixtures: bool) -> str:
    css = (SRC / "replay.css").read_text()
    js = (SRC / "replay.js").read_text()
    blob = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
    blob = blob.replace("</", "<\\/").replace("<!--", "<\\!--")
    note = ('<p class="fixture">These runs are hand-written fixtures for building the page, '
            "not recordings of the simulations.</p>\n" if fixtures else "")
    return f"""<title>Lab Hall Replay</title>
<style>{css}</style>
<div class="wrap">
<header>
<p class="eyebrow">Lab World <span>/</span> instrument integration <span>/</span> Di Hu</p>
<h1>The hall, running in simulation</h1>
<p class="small">Each run is a recording of a simulation. Where a driver exists, the frames shown
are the ones it wrote. Nothing here ran on a physical instrument.</p>
<p class="small"><a href="index.html">How each station is reached</a></p>
{note}</header>

<div class="pick">
<h2 id="r-stations-label">Station</h2>
<ul class="row" id="r-stations" aria-labelledby="r-stations-label"></ul>
<p class="about" id="r-about"></p>
</div>
<div class="pick">
<h2 id="r-cases-label">Run</h2>
<ul class="row" id="r-cases" aria-labelledby="r-cases-label"></ul>
</div>

<div class="controls" role="group" aria-label="Playback">
<button class="c" type="button" id="r-run" aria-pressed="false">Run</button>
<button class="c" type="button" id="r-step">Step</button>
<button class="c" type="button" id="r-reset">Reset</button>
<span class="gap"></span>
<span id="r-speeds" role="group" aria-label="Speed" class="controls" style="margin:0"></span>
<span class="pos" id="r-pos" aria-live="polite"></span>
</div>
<p class="small" style="margin-top:10px">Space runs or pauses. The right arrow steps.</p>

<div class="stage">
<div>
<h2>On the wire</h2>
<ol class="all" id="r-all" hidden></ol>
<div class="wire" id="r-wire"></div>
</div>
<div>
<h2>The simulated instrument</h2>
<div class="inst" id="r-inst"></div>
</div>
</div>
<div class="outcome" id="r-outcome" aria-live="polite"></div>
</div>
<script type="application/json" id="r-data">{blob}</script>
<script>
{js}</script>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", action="store_true", help="read replay_src/fixtures/")
    ap.add_argument("--body", help="also write the page without the document wrapper")
    ap.add_argument("--traces", default=str(ROOT / "traces"), help="folder of trace files")
    ap.add_argument("--out", default=str(ROOT / "replay.html"), help="where to write the page")
    args = ap.parse_args()
    folder = SRC / "fixtures" if args.fixtures else Path(args.traces)
    if not folder.is_dir():
        fail(f"no {folder.name}/ folder; run the trace export first, or pass --fixtures")
    data = {"fixtures": args.fixtures, "stations": load_stations(), "traces": load_traces(folder)}
    page = body(data, args.fixtures)
    try:
        page.encode("ascii")
    except UnicodeEncodeError as e:
        fail(f"non-ASCII text on the page: {page[max(0, e.start - 60):e.end + 20]!r}")
    for tag in re.findall(r"<(?:script|link)\b[^>]*>", page, re.I):
        if re.search(r"\b(?:src|href)\s*=", tag, re.I):
            fail(f"external reference on the page: {html.escape(tag)}")
    head, rest = page.split("</style>\n", 1)
    doc = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
           '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
           + head + "</style>\n</head>\n<body>\n" + rest + "</body></html>\n")
    out = Path(args.out)
    out.write_text(doc)
    if args.body:
        Path(args.body).write_text(page)
    n = sum(len(v) for v in data["traces"].values())
    print(f"{out.name} written from {folder.name}/, {n} traces, {len(doc)} bytes")


if __name__ == "__main__":
    main()
