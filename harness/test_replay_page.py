"""The replay page: it builds, it is self-contained, and its replay logic does what it says."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc"
ORDER = ["culture", "seed", "star", "inc", "rail", "xarm", "hotel", "reader", "lcms"]
CASES = ["clean", "lost_reply", "device_error"]


def build(tmp: Path, *extra: str) -> tuple[str, str]:
    out, body = tmp / "replay.html", tmp / "body.html"
    p = subprocess.run([sys.executable, "build_replay.py", "--out", str(out), "--body", str(body),
                        *extra], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stdout + p.stderr
    return out.read_text(), body.read_text()


def embedded(page: str) -> dict:
    m = re.search(r'<script type="application/json" id="r-data">(.*?)</script>', page, re.S)
    assert m
    return json.loads(m.group(1))


def check_page(page: str, body: str) -> None:
    page.encode("ascii")
    body.encode("ascii")
    for tag in re.findall(r"<(?:script|link)\b[^>]*>", page, re.I):
        assert not re.search(r"https?:", tag, re.I), tag
    for block in re.findall(r"<script\b[^>]*>(.*?)</script>", page, re.S | re.I):
        assert not re.search(r"https?://", block), "URL inside a script"
    assert "<link" not in page.lower()
    data = embedded(page)
    assert sum(len(v) for v in data["traces"].values()) == 27
    assert [s["key"] for s in data["stations"]] == ORDER
    for k in ORDER:
        for c in CASES:
            assert data["traces"][k][c]["station"] == k and data["traces"][k][c]["case"] == c
    assert page.startswith("<!doctype html>")
    assert body.startswith("<title>Lab Hall Replay</title>\n<style>")
    for tag in ("doctype", "html", "head", "body"):
        assert not re.search(r"<!?" + tag + r"[\s>]", body, re.I), tag
    assert "padding-left:max(16px,env(safe-area-inset-left,0px))" in body
    assert "padding-right:max(16px,env(safe-area-inset-right,0px))" in body
    assert re.search(r"body\{background:#ffffff", body)
    assert "localStorage" not in page and "sessionStorage" not in page


def test_builds_from_fixtures(tmp_path: Path) -> None:
    page, body = build(tmp_path, "--fixtures")
    check_page(page, body)
    assert embedded(page)["fixtures"] is True


def test_builds_from_real_traces(tmp_path: Path) -> None:
    folder = ROOT / "traces"
    if not all((folder / f"{k}.{c}.json").is_file() for k in ORDER for c in CASES):
        pytest.skip("traces/ does not hold all 27 trace files yet")
    page, body = build(tmp_path)
    check_page(page, body)
    assert embedded(page)["fixtures"] is False


def test_missing_trace_is_named(tmp_path: Path) -> None:
    folder = tmp_path / "traces"
    shutil.copytree(ROOT / "replay_src" / "fixtures", folder)
    (folder / "hotel.lost_reply.json").unlink()
    p = subprocess.run([sys.executable, "build_replay.py", "--traces", str(folder),
                        "--out", str(tmp_path / "x.html")],
                       cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert p.returncode != 0
    assert "hotel.lost_reply.json" in p.stdout + p.stderr
    assert not (tmp_path / "x.html").exists()


JS_TESTS = r"""
var out = typeof console !== "undefined" && console.log ? function (s) { console.log(s); } : print;
var R = ReplayCore, fails = 0, runs = 0;
function ok(c, what) { runs++; if (!c) { fails++; out("FAIL " + what); } }
function eq(a, b, what) { ok(JSON.stringify(a) === JSON.stringify(b), what + ": " +
  JSON.stringify(a) + " != " + JSON.stringify(b)); }

var T = DATA.traces;
var tr = {station: "rail", steps: [
  {i: 0, tag: "ask", text: "a", state: null},
  {i: 1, tag: "state", text: "b", state: {pos_mm: 0, moves: 0, list: [1, 2, 3]}},
  {i: 2, tag: "send", text: "c", state: null},
  {i: 3, tag: "state", text: "d", state: {pos_mm: 5, moves: 0, list: [1, 9, 3]}}]};
eq(R.stateAt(tr, 0), null, "no state before the first one");
eq(R.stateAt(tr, 2).pos_mm, 0, "null resolves to the previous state");
eq(R.stateAt(tr, 3).pos_mm, 5, "a new state wins");
eq(R.stateAt(tr, 99).pos_mm, 5, "past the end clamps");
eq(R.firstState(tr).pos_mm, 0, "first state");
eq(R.changes(R.stateAt(tr, 2), R.stateAt(tr, 3)), {pos_mm: true, list: [1]}, "changes");
eq(R.changes(null, R.stateAt(tr, 3)), {}, "no changes without a previous state");

eq(R.parseHash("#star"), "star", "hash station");
eq(R.parseHash("#all"), "all", "hash all");
eq(R.parseHash("#nope"), null, "hash unknown");
eq(R.parseHash(""), null, "hash empty");
eq(R.outcomeWord("hold"), "Hold", "outcome word");
eq(R.shade(0, 0, 10), "#ffffff", "shade low");
eq(R.shade(10, 0, 10), "#111111", "shade high");
eq(R.esc("<a&\"b>"), "&lt;a&amp;&quot;b&gt;", "escape");

var clean = R.buildAll(T, "clean");
eq(clean.segments.map(function (s) { return s.key; }), R.ORDER, "all 9 clean plays 9");
ok(clean.segments.every(function (s) { return s.trace.case === "clean"; }), "all clean traces");
eq(clean.notAsked, [], "nothing skipped when clean");
var n = R.total(clean), st = R.rowStatus(clean, n - 1);
ok(R.ORDER.every(function (k) { return st[k] === T[k].clean.outcome; }), "all rows end with outcome");
var st0 = R.rowStatus(clean, 0);
eq(st0.culture, T.culture.clean.steps.length === 1 ? T.culture.clean.outcome : "running", "row 1 runs");
eq(st0.lcms, "waiting", "row 9 waits");

["lost_reply", "device_error"].forEach(function (c) {
  var q = R.buildAll(T, c), last = q.segments[q.segments.length - 1];
  eq(last.key, "reader", c + ": stops at the reader");
  eq(last.trace.case, c, c + ": reader plays the chosen case");
  eq(q.notAsked, ["lcms"], c + ": lcms not asked");
  var m = R.total(q), s = R.rowStatus(q, m - 1);
  eq(s.lcms, "not asked", c + ": lcms row at the end");
  eq(s.reader, T.reader[c].outcome, c + ": reader row outcome");
  eq(R.rowStatus(q, 0).lcms, "waiting", c + ": lcms waits at rest");
  var at = R.locate(q, m - 1);
  ok(at.seg === q.segments.length - 1 && at.last, c + ": last step located");
});

var q1 = R.single(T, "star", "clean"), len = T.star.clean.steps.length;
eq(R.total(q1), len, "single total");
eq(R.locate(q1, 0), {seg: 0, i: 0, last: len === 1}, "locate start");
eq(R.locate(q1, len - 1).last, true, "locate end");
var a2 = R.locate(clean, T.culture.clean.steps.length);
eq([a2.seg, a2.i], [1, 0], "locate crosses a segment");

R.ORDER.forEach(function (k) { R.CASES.forEach(function (c) {
  var t = T[k][c];
  ok(R.stateAt(t, 0) !== null || R.firstState(t) !== null, k + "." + c + ": a state to draw at rest");
  for (var i = 0; i < t.steps.length; i++) {
    var h;
    try { h = R.drawAt(t, i); } catch (e) { ok(false, k + "." + c + " step " + i + ": " + e); continue; }
    ok(typeof h === "string" && h.length > 0 && !/undefined|NaN/.test(h), k + "." + c + " step " + i);
  }
}); });

out("ran " + runs + " checks, " + fails + " failed");
if (fails) throw new Error(fails + " failed");
out("ALL PASSED");
"""


def js_engine() -> list[str] | None:
    node = shutil.which("node")
    if node:
        return [node]
    if Path(JSC).is_file():
        return [JSC]
    return None


@pytest.mark.parametrize("source", ["fixtures", "traces"])
def test_replay_logic_in_js(tmp_path: Path, source: str) -> None:
    engine = js_engine()
    if engine is None:
        pytest.skip("neither node nor jsc found")
    page, _ = build(tmp_path, "--fixtures") if source == "fixtures" else (None, None)
    if source == "traces":
        folder = ROOT / "traces"
        if not all((folder / f"{k}.{c}.json").is_file() for k in ORDER for c in CASES):
            pytest.skip("traces/ does not hold all 27 trace files yet")
        page, _ = build(tmp_path)
    data = embedded(page)
    js = (ROOT / "replay_src" / "replay.js").read_text()
    script = tmp_path / "run.js"
    script.write_text(js + "\nvar DATA = " + json.dumps(data) + ";\n" + JS_TESTS)
    p = subprocess.run(engine + [str(script)], capture_output=True, text=True, timeout=60)
    print(Path(engine[0]).name, p.stdout.strip())
    assert p.returncode == 0 and "ALL PASSED" in p.stdout, p.stdout + p.stderr
