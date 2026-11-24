#!/usr/bin/env python3
"""Build index.html from the station folders. Standard library only.

    .venv/bin/python build_page.py              writes index.html (opens offline)
    .venv/bin/python build_page.py --body FILE  also writes the page without its document wrapper

Nothing on the page is typed twice. The code shown is cut from each station's drive.py, the
transcript is that file's real output, and the pass counts come from pytest, all at build time.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLR = "https://github.com/PyLabRobot/pylabrobot/blob/182f92eab9f81b1f50c43b833420642bf8b0fb02/"
KIT = "https://github.com/di-omics/plr-reverse-engineer/blob/264ca78/"
ORDER = ["culture", "seed", "star", "inc", "rail", "xarm", "hotel", "reader", "lcms"]
STATUS = {
    "in_plr": "Decoded, in PyLabRobot",
    "in_plr_legacy": "Decoded, in PyLabRobot, older interface",
    "vendor_sdk": "Maker's SDK, nothing to decode",
    "not_in_plr": "Not decoded yet",
    "nothing_to_decode": "Nothing to decode",
    "open_choice": "Instrument not chosen yet",
}


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def attr(url: str) -> str:
    return esc(url).replace('"', "%22")


def sh(args: list[str], timeout: int = 240) -> tuple[int, str, str]:
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout.rstrip(), p.stderr.rstrip()


def snippet(key: str) -> str:
    text = (ROOT / "stations" / key / "drive.py").read_text()
    m = re.search(r"^[ \t]*# --8<-- snippet[^\n]*\n(.*?)^[ \t]*# --8<-- end", text, re.S | re.M)
    if not m:
        raise SystemExit(f"{key}: drive.py has no snippet markers")
    return textwrap.dedent(m.group(1)).rstrip()


def transcript(key: str) -> str:
    code, out, err = sh([sys.executable, "-m", f"stations.{key}.drive"])
    if code != 0:
        raise SystemExit(f"{key}: drive exited {code}\n{err}")
    return out


def passed(path: str) -> int:
    code, out, err = sh([sys.executable, "-m", "pytest", path, "-p", "no:cacheprovider"])
    m = re.search(r"(\d+) passed", out)
    if code != 0 or not m or re.search(r"\d+ (failed|error)", out):
        raise SystemExit(f"{path}: tests did not pass\n{out[-1500:]}\n{err[-500:]}")
    return int(m.group(1))


def linked(text: str) -> str:
    """Escape, then turn path:line references into links to the pinned sources."""
    def link(m: re.Match[str]) -> str:
        kit, path, a, b = m.group(1), m.group(2), m.group(3), m.group(4)
        if kit or path.startswith(("plr_re/", "instruments/", "configs/")):
            base = KIT
        elif path.startswith(("pylabrobot/", "docs/")) or path in ("CHANGELOG.md", "CITATION.cff"):
            base = PLR
        else:
            return m.group(0)
        frag = f"#L{a}" + (f"-L{b}" if b else "") if a else ""
        label = path.rsplit("/", 1)[-1] + (f":{a}" + (f"-{b}" if b else "") if a else "")
        return f'<a href="{base}{path}{frag}" target="_blank" rel="noopener">{label}</a>'
    pat = (r"(plr-reverse-engineer/)?((?:pylabrobot|docs|plr_re|instruments|configs|tests)/"
           r"[A-Za-z0-9_/.\-]+?\.(?:py|md|json|ipynb)|[A-Za-z\-]+\.md|CITATION\.cff)"
           r"(?::(\d+)(?:-(\d+))?)?")
    return re.sub(pat, link, esc(text))


def items(values: list[str], tag: str = "ul", cls: str = "") -> str:
    if not values:
        return ""
    c = f' class="{cls}"' if cls else ""
    return f"<{tag}{c}>" + "".join(f"<li>{linked(v)}</li>" for v in values) + f"</{tag}>"


def station_html(s: dict, n: int, total: int) -> str:
    key = s["key"]
    cols = "".join(
        f"<div><h4>{label}</h4>{items(s.get(field, []))}</div>"
        for label, field in (("Real", "real"), ("Simulated", "simulated"),
                             ("Not checked", "not_checked")))
    src = " <span>/</span> ".join(f'<a href="{attr(u)}" target="_blank" rel="noopener">{esc(t)}</a>'
                   for t, u in s.get("sources", []))
    limits = items(s.get("limits", []))
    return f"""
<section class="station" id="{key}">
<p class="eyebrow">Station {n} of {total} <span>/</span> {esc(STATUS[s['status']])}</p>
<h2>{esc(s['name'])}</h2>
<p class="lead">{linked(s['status_line'])}</p>
<dl class="facts">
<dt>How software reaches it</dt><dd>{linked(s['reaches'])}</dd>
<dt>Where the commands came from</dt><dd>{linked(s['decoded_from'])}</dd>
</dl>
<h3>{esc(s['steps_title'])}</h3>
{items(s['steps'], 'ol', 'steps')}
<h3>The example</h3>
<p>{linked(s['scenario'])}</p>
<div class="scroll"><pre class="code"><code>{esc(s['_snippet'])}</code></pre></div>
<details class="ran"><summary>What ran in simulation <span>/</span> {s['_passed']} tests passed</summary>
<div class="scroll"><pre><code>{esc(s['_transcript'])}</code></pre></div></details>
<details class="more"><summary>What is real, what is simulated, and the limits found in the source</summary>
<div class="triple">{cols}</div>
{'<h3>Limits found in the source</h3>' + limits if limits else ''}
{'<p class="sources">Sources <span>/</span> ' + src + '</p>' if src else ''}
</details>
</section>"""


CSS = """
/* Layout: 1 quiet column on pure white. Type only. Code and tables scroll inside their own boxes. */
:root{--paper:#ffffff;--ink:#111111;--soft:#62666b;--hair:#e3e3e1;--wash:#f6f6f4;
--sans:"Helvetica Neue",Helvetica,Arial,sans-serif;
--mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
body{background:var(--paper);color:var(--ink);font-family:var(--sans);font-weight:300;
font-size:17px;line-height:1.55;margin:0;-webkit-font-smoothing:antialiased}
.wrap{max-width:860px;margin:0 auto;padding-block:72px 120px;
padding-left:max(16px,env(safe-area-inset-left,0px));
padding-right:max(16px,env(safe-area-inset-right,0px))}
a{color:var(--ink);text-decoration-color:var(--hair);text-underline-offset:3px}
a:hover{text-decoration-color:var(--ink)}
a:focus-visible,summary:focus-visible{outline:2px solid var(--ink);outline-offset:3px}
h1{font-weight:200;font-size:clamp(36px,7vw,64px);line-height:1.04;letter-spacing:-0.02em;
margin:0 0 20px;text-wrap:balance}
h2{font-weight:200;font-size:clamp(28px,4.6vw,40px);line-height:1.1;letter-spacing:-0.015em;
margin:0 0 10px;text-wrap:balance}
h3{font-weight:400;font-size:13px;letter-spacing:0.09em;text-transform:uppercase;
color:var(--soft);margin:36px 0 10px}
h4{font-weight:400;font-size:12px;letter-spacing:0.09em;text-transform:uppercase;
color:var(--soft);margin:0 0 6px}
p{margin:0 0 14px;max-width:66ch}
.lede{font-size:21px;line-height:1.4;max-width:34em}
.small,.sources{font-size:14px;color:var(--soft);max-width:none}
.eyebrow{font-size:13px;letter-spacing:0.09em;text-transform:uppercase;color:var(--soft);
margin:0 0 12px}
.eyebrow span,.sources span,summary span{color:var(--hair);padding:0 6px}
.lead{font-size:20px;line-height:1.4}
section{padding-top:88px}
.station{border-top:1px solid var(--hair);margin-top:88px}
dl.facts{display:grid;grid-template-columns:minmax(0,13em) minmax(0,1fr);gap:8px 24px;margin:22px 0 0}
dl.facts dt{color:var(--soft)}
dl.facts dd{margin:0;min-width:0}
ol.steps{margin:0;padding-left:1.3em;max-width:66ch}
ol.steps li{margin:0 0 7px;padding-left:4px}
ul{margin:0;padding-left:1.1em}
ul li{margin:0 0 6px}
.scroll{overflow-x:auto;margin:14px 0 0;background:var(--wash)}
pre{margin:0;padding:18px 20px;font-family:var(--mono);font-size:12.5px;line-height:1.6;
font-weight:400;color:var(--ink);white-space:pre}
details.ran{margin-top:14px}
details.more{margin-top:2px}
details.more h3{margin-top:26px}
button.plain{font:inherit;font-size:14px;color:var(--ink);background:none;border:0;padding:0;
cursor:pointer;text-decoration:underline;text-decoration-color:var(--hair);text-underline-offset:3px}
button.plain:hover{text-decoration-color:var(--ink)}
button.plain:focus-visible{outline:2px solid var(--ink);outline-offset:3px}
summary{cursor:pointer;font-size:15px;padding:8px 0;color:var(--ink)}
.triple{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:28px;margin-top:16px;
font-size:15px;line-height:1.45}
.triple div{min-width:0}
.tablebox{overflow-x:auto;margin-top:26px}
table{border-collapse:collapse;width:100%;font-size:15px;line-height:1.4}
th{font-weight:400;font-size:12px;letter-spacing:0.09em;text-transform:uppercase;
color:var(--soft);text-align:left;padding:0 18px 10px 0;white-space:nowrap}
td{vertical-align:top;padding:11px 18px 11px 0;border-top:1px solid var(--hair)}
td:first-child{white-space:nowrap}
td.n{font-variant-numeric:tabular-nums;white-space:nowrap}
ol.method{margin:26px 0 0;padding-left:1.3em;max-width:66ch}
ol.method li{margin:0 0 14px;padding-left:4px}
ol.method b{font-weight:400}
@media (max-width:640px){body{font-size:16px}.triple{grid-template-columns:minmax(0,1fr);gap:20px}
dl.facts{grid-template-columns:minmax(0,1fr);gap:2px}dl.facts dd{margin:0 0 12px}
section{padding-top:64px}.station{margin-top:64px}}
"""


def page(stations: list[dict], walk_out: str, walk_passed: int, harness_passed: int) -> str:
    total = len(stations)
    count = {k: sum(1 for s in stations if s["status"] == k) for k in STATUS}
    decoded = count["in_plr"] + count["in_plr_legacy"]
    tests = sum(s["_passed"] for s in stations) + harness_passed
    rows = "".join(
        f'<tr><td><a href="#{s["key"]}">{esc(s["name"])}</a></td>'
        f'<td>{esc(STATUS[s["status"]])}</td><td>{linked(s["reaches"])}</td>'
        f'<td class="n">{s["_passed"]} passed</td></tr>' for s in stations)
    body = "".join(station_html(s, i + 1, total) for i, s in enumerate(stations))
    return f"""<title>Reverse Engineering the Hall</title>
<style>{CSS}</style>
<div class="wrap">
<header>
<p class="eyebrow">Lab World <span>/</span> instrument integration <span>/</span> Di Hu</p>
<h1>Reverse engineering the hall</h1>
<p class="lede">{total} stations. For each one: is it already decoded, how does software reach it,
and what does a first run look like.</p>
<p class="small">Every run on this page is a simulation. Nothing here ran on a physical instrument.
Built against the public PyLabRobot source at commit
<a href="{PLR}" target="_blank" rel="noopener">182f92e</a> of 23 Nov 2026.</p>
<p class="small"><a href="replay.html">Watch each station run in simulation</a></p>
<p class="small"><button class="plain" id="openall" type="button">Open every detail</button></p>
</header>

<section id="method">
<h2>The method is the same at every station</h2>
<ol class="method">
<li><b>Ask first: is it already decoded?</b> Read the PyLabRobot device registry and source before
touching the instrument. {decoded} of these {total} stations already are.</li>
<li><b>If the maker publishes an interface, use it.</b> An SDK means there is nothing to decode.
Write 1 small class around it.</li>
<li><b>If not, extract, don't guess.</b> Capture the maker's own software doing 1 action at a time.
Get the wire format exact: transport, framing, checksum, handshake.</li>
<li><b>Write 1 plain class.</b> Its public methods state intent and are safe to repeat:
read the state, act only if needed, confirm.</li>
<li><b>Prove it without the instrument.</b> Replay the traffic against the class. Errors keep
their code. An unverified driver says so when it starts.</li>
<li><b>The first live command only reads.</b> Then 1 move with empty labware and a person present.</li>
</ol>
<p class="small">Steps 3 to 5 follow the PyLabRobot
<a href="{PLR}docs/contributor_guide/device-driver-guide.md" target="_blank" rel="noopener">device
driver guide</a>. Steps 3 and 6 follow my
<a href="{KIT}APPROACH.md" target="_blank" rel="noopener">reverse engineering playbook</a>.</p>
<div class="tablebox"><table>
<thead><tr><th>Station</th><th>Where it stands</th><th>How software reaches it</th>
<th>In simulation</th></tr></thead>
<tbody>{rows}</tbody></table></div>
</section>
{body}
<section class="station" id="walk">
<p class="eyebrow">The central harness</p>
<h2>1 plate through all {total}</h2>
<p class="lead">Every station answers the harness the same way: completed, hold, or error.</p>
<p>The first run is clean. In the second run the reader carries out the read and its reply is
lost. The harness holds, sends no second read, and does not ask the next station.</p>
<div class="scroll"><pre><code>{esc(walk_out)}</code></pre></div>
<p class="small" style="margin-top:14px">{walk_passed} harness tests passed: each of the {total}
stations with a lost reply and with an instrument error.</p>
</section>

<section class="station" id="run">
<p class="eyebrow">Run it yourself</p>
<h2>3 commands</h2>
<div class="scroll"><pre><code>uv run pytest                          # all {tests} tests
uv run python -m stations.star.drive   # 1 station, with its wire traffic
uv run python -m harness.walk          # 1 plate through all {total}</code></pre></div>
<p class="small" style="margin-top:14px">To watch the runs step by step, open
<a href="replay.html">replay.html</a>. It plays the trace files that
<code>uv run python -m harness.trace</code> records.</p>
</section>

<section class="station" id="limits">
<p class="eyebrow">Read this before quoting the page</p>
<h2>What this is not</h2>
<ul>
<li>It is not a bench result. No command on this page reached a physical instrument.</li>
<li>Each simulated instrument answers only the commands its example sends.
It is a check of the driver's side of the wire.</li>
<li>Every volume, position, temperature and timing is a made-up round number.</li>
<li>Where a station says not decoded, the payloads in its example are placeholders.
They are not that instrument's commands.</li>
</ul>
</section>
</div>
<script>
(function () {{
  var b = document.getElementById("openall"), on = false;
  if (!b) return;
  b.addEventListener("click", function () {{
    on = !on;
    document.querySelectorAll("details").forEach(function (d) {{ d.open = on; }});
    b.textContent = on ? "Close every detail" : "Open every detail";
  }});
}})();
</script>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--body", help="also write the page without the document wrapper")
    args = ap.parse_args()
    stations = []
    for key in ORDER:
        s = json.loads((ROOT / "stations" / key / "station.json").read_text())
        if s["key"] != key or s["status"] not in STATUS:
            raise SystemExit(f"{key}: bad key or status in station.json")
        s["_snippet"], s["_transcript"] = snippet(key), transcript(key)
        s["_passed"] = passed(f"stations/{key}")
        stations.append(s)
        print(f"{key:8s} {s['status']:18s} {s['_passed']:3d} passed")
    code, walk_out, err = sh([sys.executable, "-m", "harness.walk"])
    if code != 0:
        raise SystemExit(f"harness walk exited {code}\n{err}")
    body = page(stations, walk_out, passed("harness/test_walk.py"), passed("harness"))
    try:
        body.encode("ascii")
    except UnicodeEncodeError as e:
        raise SystemExit(f"non-ASCII text on the page: {body[e.start - 60:e.end + 20]!r}")
    if "&#" in body:
        raise SystemExit("numeric character reference on the page")
    doc = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width, initial-scale=1"></head>\n<body>\n'
           + body + "</body></html>\n")
    (ROOT / "index.html").write_text(doc)
    if args.body:
        Path(args.body).write_text(body)
    print(f"index.html written, {len(doc)} bytes")


if __name__ == "__main__":
    main()
