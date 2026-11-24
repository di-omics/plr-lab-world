/* Replay of recorded simulation traces.
   Part 1 is pure functions with no DOM access (tested from harness/test_replay_page.py).
   Part 2 is a thin DOM layer that runs only in a browser. */
var ReplayCore = (function () {
  "use strict";

  var ORDER = ["culture", "seed", "star", "inc", "rail", "xarm", "hotel", "reader", "lcms"];
  var CASES = ["clean", "lost_reply", "device_error"];
  var SPEEDS = { slow: 1100, normal: 520, fast: 160 };

  /* The state at step i: a null state means "same as the previous step". */
  function stateAt(trace, i) {
    var steps = trace.steps;
    for (var k = Math.min(i, steps.length - 1); k >= 0; k--) {
      if (steps[k].state !== null && steps[k].state !== undefined) return steps[k].state;
    }
    return null;
  }

  /* Before the first recorded state, show that first state: it is the state at rest. */
  function firstState(trace) {
    for (var k = 0; k < trace.steps.length; k++) {
      if (trace.steps[k].state !== null && trace.steps[k].state !== undefined) return trace.steps[k].state;
    }
    return null;
  }

  function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

  /* Top-level fields whose value differs between 2 states. Arrays give the changed indexes. */
  function changes(prev, cur) {
    var out = {};
    if (!prev || !cur) return out;
    for (var k in cur) {
      if (!Object.prototype.hasOwnProperty.call(cur, k)) continue;
      if (same(prev[k], cur[k])) continue;
      if (Array.isArray(cur[k]) && Array.isArray(prev[k]) && prev[k].length === cur[k].length) {
        var idx = [];
        for (var j = 0; j < cur[k].length; j++) if (!same(prev[k][j], cur[k][j])) idx.push(j);
        out[k] = idx;
      } else {
        out[k] = true;
      }
    }
    return out;
  }

  /* 1 station: a sequence of 1 segment. */
  function single(traces, key, caseName) {
    return { segments: [{ key: key, trace: traces[key][caseName] }], notAsked: [] };
  }

  /* All 9: every clean trace in walk order, except the reader, which plays the chosen case.
     The walk stops after the first trace that does not complete; the rest are not asked. */
  function buildAll(traces, caseName) {
    var segs = [], notAsked = [], stopped = false;
    for (var n = 0; n < ORDER.length; n++) {
      var key = ORDER[n];
      if (stopped) { notAsked.push(key); continue; }
      var tr = traces[key][key === "reader" ? caseName : "clean"];
      segs.push({ key: key, trace: tr });
      if (tr.outcome !== "completed") stopped = true;
    }
    return { segments: segs, notAsked: notAsked };
  }

  function total(seq) {
    var t = 0;
    for (var n = 0; n < seq.segments.length; n++) t += seq.segments[n].trace.steps.length;
    return t;
  }

  /* Global step g -> which segment, and which step inside it. */
  function locate(seq, g) {
    var rest = Math.max(0, Math.min(g, total(seq) - 1));
    for (var n = 0; n < seq.segments.length; n++) {
      var len = seq.segments[n].trace.steps.length;
      if (rest < len) return { seg: n, i: rest, last: rest === len - 1 };
      rest -= len;
    }
    return { seg: 0, i: 0, last: false };
  }

  function outcomeWord(o) {
    return o === "completed" ? "Completed" : o === "hold" ? "Hold" : o === "error" ? "Error" : o;
  }

  /* Row labels for the All 9 list at global step g. */
  function rowStatus(seq, g) {
    var at = locate(seq, g), end = g >= total(seq) - 1, out = {};
    for (var n = 0; n < seq.segments.length; n++) {
      var s = seq.segments[n];
      if (n < at.seg || (n === at.seg && at.last)) out[s.key] = s.trace.outcome;
      else if (n === at.seg) out[s.key] = "running";
      else out[s.key] = "waiting";
    }
    for (var m = 0; m < seq.notAsked.length; m++) out[seq.notAsked[m]] = end ? "not asked" : "waiting";
    return out;
  }

  function parseHash(hash) {
    var h = String(hash || "").replace(/^#/, "").toLowerCase();
    if (h === "all") return "all";
    return ORDER.indexOf(h) >= 0 ? h : null;
  }

  /* White at lo, black at hi. */
  function shade(v, lo, hi) {
    var f = hi > lo ? (v - lo) / (hi - lo) : 0;
    f = Math.max(0, Math.min(1, f));
    var c = Math.round(255 - f * (255 - 17));
    var h = (c < 16 ? "0" : "") + c.toString(16);
    return "#" + h + h + h;
  }

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function num(v) {
    if (v === null || v === undefined) return "-";
    if (typeof v === "number") return String(Math.round(v * 100) / 100);
    return String(v);
  }

  function yes(b) { return b ? "yes" : "no"; }

  function kv(rows) {
    var h = '<dl class="kv">';
    for (var n = 0; n < rows.length; n++) {
      h += "<dt>" + esc(rows[n][0]) + "</dt><dd" + (rows[n][2] ? ' class="chg"' : "") + ">" +
        esc(rows[n][1]) + "</dd>";
    }
    return h + "</dl>";
  }

  function has(ch, k, j) {
    if (!ch[k]) return false;
    if (j === undefined || ch[k] === true) return true;
    return ch[k].indexOf(j) >= 0;
  }

  var INK = "#111111", LIGHT = "#cfd0ce", SOFT = "#62666b", WHITE = "#ffffff";

  function rect(x, y, w, h, fill, stroke, sw) {
    return '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" fill="' + fill +
      '" stroke="' + stroke + '" stroke-width="' + (sw || 1) + '"/>';
  }

  function text(x, y, s, anchor, size) {
    return '<text x="' + x + '" y="' + y + '" font-family="Helvetica Neue, Helvetica, Arial, sans-serif"' +
      ' font-size="' + (size || 10) + '" fill="' + SOFT + '" text-anchor="' + (anchor || "start") + '">' +
      esc(s) + "</text>";
  }

  function svg(w, h, body, label) {
    return '<svg viewBox="0 0 ' + w + " " + h + '" width="' + w + '" role="img" aria-label="' +
      esc(label) + '">' + body + "</svg>";
  }

  /* A 16 by 24 plate grid. fillOf(row, col) gives the fill; outlineCols marks changed columns. */
  function plateGrid(fillOf, outlineCols, outlineAll, label) {
    var c = 10, g = 2, p = c + g, b = "";
    for (var r = 0; r < 16; r++) {
      for (var k = 0; k < 24; k++) {
        var f = fillOf(r, k);
        b += rect(2 + k * p, 2 + r * p, c, c, f, f === WHITE ? LIGHT : f, 1);
      }
    }
    for (var n = 0; n < outlineCols.length; n++) {
      b += rect(1 + outlineCols[n] * p - 1, 0, c + 3, 16 * p + 1, "none", INK, 2);
    }
    if (outlineAll) b += rect(0, 0, 24 * p + 2, 16 * p + 2, "none", INK, 2);
    return svg(24 * p + 4, 16 * p + 4, b, label);
  }

  function boxes3(names, here, changed) {
    var h = '<div class="box3">';
    for (var n = 0; n < 3; n++) {
      var cls = (n === here ? "here" : "") + (n === here && changed ? " chg" : "");
      h += '<div class="' + cls + '">' + esc(names[n]) +
        (n === here ? '<span class="plate" aria-label="plate"></span>' : "") + "</div>";
    }
    return h + "</div>";
  }

  var DRAW = {
    culture: function (s, ch, prev) {
      var batches = (s.known_batches || []).slice();
      for (var b in s.released) if (batches.indexOf(b) < 0) batches.push(b);
      var h = '<div class="tablebox"><table class="t"><thead><tr><th>Batch</th><th>Worklist</th>' +
        "<th>Released</th></tr></thead><tbody>";
      for (var n = 0; n < batches.length; n++) {
        var id = batches[n], w = s.released[id];
        var c = prev && !same((prev.released || {})[id], w);
        h += "<tr" + (c ? ' class="chg"' : "") + "><td>" + esc(id) + "</td><td>" +
          esc(w === undefined ? "-" : w) + "</td><td>" + (w === undefined ? "no" : "yes") +
          "</td></tr>";
      }
      h += "</tbody></table></div>";
      return h + kv([["Releases executed", num(s.executed), has(ch, "executed")]]);
    },
    seed: function (s, ch) {
      var cols = s.columns_uL || [], filled = 0, vols = [];
      for (var k = 0; k < cols.length; k++) {
        if (cols[k] > 0) { filled++; if (vols.indexOf(cols[k]) < 0) vols.push(cols[k]); }
      }
      /* 1 changed column gets its own outline; more than 1 outline the whole plate. */
      var cc = ch.columns_uL === true ? [0, 1] : (ch.columns_uL || []);
      var grid = plateGrid(function (r, k) { return cols[k] > 0 ? INK : WHITE; },
        cc.length > 1 ? [] : cc, cc.length > 1,
        "384-well plate, " + filled + " of 24 columns dispensed");
      return grid + kv([
        ["Plate", s.plate === null ? "none" : s.plate, has(ch, "plate")],
        ["Batch", s.batch_open ? "open" : "closed", has(ch, "batch_open")],
        ["Pump", s.pump === null ? "-" : s.pump, has(ch, "pump")],
        ["Prime", num(s.prime_uL) + " uL", has(ch, "prime_uL")],
        ["Per well", vols.length ? vols.map(num).join(", ") + " uL" : "0 uL", has(ch, "columns_uL")],
        ["Columns filled", filled + " of 24", has(ch, "columns_uL")],
        ["Error", s.error === "" ? "none" : s.error, has(ch, "error")]
      ]);
    },
    star: function (s, ch) {
      var b = "", maxv = 1, k;
      var src = s.source_uL || [], dst = s.dest_uL || [], tip = s.tip_uL || [];
      for (k = 0; k < 8; k++) maxv = Math.max(maxv, src[k] || 0, dst[k] || 0);
      b += text(0, 10, "Channels", "start", 11);
      for (k = 0; k < 8; k++) {
        var x = 2 + k * 36, on = (s.tips_on_channel || [])[k];
        var c = has(ch, "tips_on_channel", k) || has(ch, "tip_uL", k);
        b += rect(x, 18, 16, 16, on ? INK : WHITE, c ? INK : (on ? INK : LIGHT), c ? 2.5 : 1);
        b += text(x + 8, 46, num(tip[k]), "middle", 10);
      }
      b += text(2, 72, "Source", "start", 11) + text(152, 72, "Destination", "start", 11);
      for (k = 0; k < 8; k++) {
        var y = 80 + k * 18, cs = has(ch, "source_uL", k), cd = has(ch, "dest_uL", k);
        b += rect(2, y, 12, 12, shade(src[k] || 0, 0, maxv), cs ? INK : LIGHT, cs ? 2.5 : 1);
        b += text(22, y + 10, num(src[k]) + " uL", "start", 11);
        b += rect(152, y, 12, 12, shade(dst[k] || 0, 0, maxv), cd ? INK : LIGHT, cd ? 2.5 : 1);
        b += text(172, y + 10, num(dst[k]) + " uL", "start", 11);
      }
      var ontips = (s.tips_on_channel || []).filter(function (t) { return t; }).length;
      return svg(290, 228, b, "8 channels, " + ontips + " with a tip; source and destination wells") +
        kv([["Initialized", yes(s.initialized), has(ch, "initialized")],
            ["Tips on channels", ontips + " of 8", has(ch, "tips_on_channel")],
            ["Tips in the rack", num(s.tips_in_rack), has(ch, "tips_in_rack")]]);
    },
    inc: function (s, ch) {
      var here = { transfer: 0, shovel: 1, cassette: 2 }[s.plate_at];
      var slot = "Cassette" + (s.cassette !== null && s.cassette !== undefined ?
        " " + s.cassette + " / position " + num(s.position) : "");
      return boxes3(["Transfer station", "Shovel", slot], here, has(ch, "plate_at")) + kv([
        ["Plate at", s.plate_at, has(ch, "plate_at")],
        ["Temperature", num(s.temp_c) + " deg C", has(ch, "temp_c")],
        ["Ready", yes(s.ready), has(ch, "ready")],
        ["Error", s.error === "" ? "none" : s.error, has(ch, "error")]
      ]);
    },
    rail: function (s, ch) {
      var w = 300, x0 = 10, x1 = 290, t = s.travel_mm || 1;
      var X = function (mm) { return x0 + (x1 - x0) * Math.max(0, Math.min(1, mm / t)); };
      var b = '<line x1="' + x0 + '" y1="30" x2="' + x1 + '" y2="30" stroke="' + INK + '" stroke-width="1"/>';
      b += '<line x1="' + x0 + '" y1="24" x2="' + x0 + '" y2="36" stroke="' + INK + '"/>';
      b += '<line x1="' + x1 + '" y1="24" x2="' + x1 + '" y2="36" stroke="' + INK + '"/>';
      b += text(x0, 54, "0", "middle", 11) + text(x1, 54, num(t) + " mm", "end", 11);
      if (s.target_mm !== null && s.target_mm !== undefined) {
        var tx = X(s.target_mm);
        b += '<line x1="' + tx + '" y1="8" x2="' + tx + '" y2="40" stroke="' + SOFT + '" stroke-width="' +
          (has(ch, "target_mm") ? 2.5 : 1) + '"/>' + text(tx, 6, "target", "middle", 10);
      }
      var px = X(s.pos_mm || 0), c = has(ch, "pos_mm");
      b += rect(px - 6, 24, 12, 12, INK, INK, 1);
      if (c) b += rect(px - 9, 21, 18, 18, "none", INK, 2);
      return svg(w, 60, b, "rail at " + num(s.pos_mm) + " mm") + kv([
        ["Position", num(s.pos_mm) + " mm", c],
        ["Target", s.target_mm === null ? "-" : num(s.target_mm) + " mm", has(ch, "target_mm")],
        ["Travel", num(s.travel_mm) + " mm", has(ch, "travel_mm")],
        ["Enabled", yes(s.enabled), has(ch, "enabled")],
        ["Homed", yes(s.homed), has(ch, "homed")],
        ["Error", num(s.error), has(ch, "error")],
        ["Moves", num(s.moves), has(ch, "moves")]
      ]);
    },
    xarm: function (s, ch) {
      var here = { hotel: 0, gripper: 1, reader: 2 }[s.plate_at];
      var p = s.pose || [], f = s.jaw_max ? Math.max(0, Math.min(1, s.jaw_units / s.jaw_max)) : 0;
      return boxes3(["Hotel nest", "Gripper", "Reader nest"], here, has(ch, "plate_at")) + kv([
        ["Pose x, y, z", num(p[0]) + ", " + num(p[1]) + ", " + num(p[2]) + " mm", has(ch, "pose")],
        ["Jaw opening", num(s.jaw_units) + " of " + num(s.jaw_max) + " units", has(ch, "jaw_units")],
        ["Error code", num(s.error_code), has(ch, "error_code")]
      ]) + '<div class="bar' + (has(ch, "jaw_units") ? " chg" : "") + '" style="margin-top:8px">' +
        '<i style="width:' + Math.round(f * 100) + '%"></i></div>';
    },
    hotel: function (s, ch, prev) {
      var n = s.slots || 24, per = 12, b = "", occ = s.occupied || [], res = s.reserved || [];
      var po = prev ? prev.occupied || [] : occ, pr = prev ? prev.reserved || [] : res;
      for (var k = 1; k <= n; k++) {
        var x = 2 + ((k - 1) % per) * 24, y = 14 + Math.floor((k - 1) / per) * 40;
        var o = occ.indexOf(k) >= 0, r = res.indexOf(k) >= 0;
        var c = prev && ((po.indexOf(k) >= 0) !== o || (pr.indexOf(k) >= 0) !== r);
        b += rect(x, y, 18, 18, o ? INK : WHITE, r ? INK : (o ? INK : LIGHT), r ? 2 : 1);
        if (c) b += rect(x - 3, y - 3, 24, 24, "none", INK, 1.5);
        if (k % per === 1 || k % per === 0) b += text(x + 9, y + 30, String(k), "middle", 10);
      }
      var done = s.clock_s >= s.dwell_s;
      return svg(per * 24 + 4, 96, b, occ.length + " of " + n + " slots occupied") + kv([
        ["Occupied", occ.length ? occ.join(", ") : "none", has(ch, "occupied")],
        ["Reserved", res.length ? res.join(", ") : "none", has(ch, "reserved")],
        ["Clock", num(s.clock_s) + " s", has(ch, "clock_s")],
        ["Dwell", num(s.dwell_s) + " s" + (done ? ", done" : ""), has(ch, "dwell_s")],
        ["Pickups", num(s.pickups), has(ch, "pickups")]
      ]);
    },
    reader: function (s, ch) {
      var v = s.values, lo = Infinity, hi = -Infinity;
      if (v) for (var k = 0; k < v.length; k++) { lo = Math.min(lo, v[k]); hi = Math.max(hi, v[k]); }
      var grid = plateGrid(function (r, c) { return v ? shade(v[r * 24 + c], lo, hi) : WHITE; },
        [], has(ch, "values"), v ? "384 values, white is the lowest, black the highest" : "no values yet");
      return grid + kv([
        ["Phase", s.phase, has(ch, "phase")],
        ["Tray", s.tray, has(ch, "tray")],
        ["Busy", yes(s.busy), has(ch, "busy")],
        ["Plates read", num(s.plates_read), has(ch, "plates_read")],
        ["Values", v ? v.length + ", from " + num(lo) + " to " + num(hi) : "none", has(ch, "values")]
      ]);
    },
    lcms: function (s, ch) {
      var rows = s.rows || [];
      var h = kv([["Ready", yes(s.ready), has(ch, "ready")]]) +
        '<div class="tablebox" style="margin-top:12px"><table class="t"><thead><tr><th>Aliquot</th>' +
        "<th>Started</th><th>Raw file</th></tr></thead><tbody>";
      for (var k = 0; k < rows.length; k++) {
        var r = rows[k];
        h += "<tr" + (has(ch, "rows", k) ? ' class="chg"' : "") + "><td>" + esc(r.aliquot) +
          "</td><td>" + num(r.started) + '</td><td class="mono">' + esc(r.raw === null ? "-" : r.raw) +
          "</td></tr>";
      }
      return h + "</tbody></table></div>";
    }
  };

  /* The drawing of the simulated instrument at step i, as an HTML string. */
  function drawAt(trace, i) {
    var cur = stateAt(trace, i) || firstState(trace);
    if (!cur) return '<p class="none">No state recorded.</p>';
    var prev = i > 0 ? stateAt(trace, i - 1) : null;
    var fresh = i > 0 && trace.steps[i].state !== null && trace.steps[i].state !== undefined;
    var ch = fresh ? changes(prev, cur) : {};
    return DRAW[trace.station](cur, ch, fresh ? prev : null);
  }

  return { ORDER: ORDER, CASES: CASES, SPEEDS: SPEEDS, stateAt: stateAt, firstState: firstState, changes: changes,
    single: single, buildAll: buildAll, total: total, locate: locate, outcomeWord: outcomeWord,
    rowStatus: rowStatus, parseHash: parseHash, shade: shade, esc: esc, drawAt: drawAt };
})();

/* Part 2: the page. */
(function () {
  "use strict";
  if (typeof document === "undefined") return;
  var R = ReplayCore;
  var DATA = JSON.parse(document.getElementById("r-data").textContent);
  var ST = {}, k;
  for (k = 0; k < DATA.stations.length; k++) ST[DATA.stations[k].key] = DATA.stations[k];
  var CASE_LABEL = { clean: "Clean run", lost_reply: "Reply lost", device_error: "Instrument error" };
  var ui = { view: "culture", kase: "clean", g: 0, playing: false, speed: "normal", timer: null };
  var $ = function (id) { return document.getElementById(id); };

  function seq() {
    return ui.view === "all" ? R.buildAll(DATA.traces, ui.kase) : R.single(DATA.traces, ui.view, ui.kase);
  }

  var pressed = [];

  /* Buttons are built once, so focus stays where it is; render only updates aria-pressed. */
  function button(cls, label, isOn, on) {
    var b = document.createElement("button");
    b.type = "button"; b.className = cls; b.innerHTML = label;
    b.addEventListener("click", on);
    pressed.push([b, isOn]);
    return b;
  }

  function pickers() {
    var sp = $("r-stations"), cp = $("r-cases"), sd = $("r-speeds");
    R.ORDER.concat(["all"]).forEach(function (key, n) {
      var li = document.createElement("li");
      var label = key === "all" ? "All 9" :
        '<span class="n">' + (n + 1) + "</span>" + R.esc(ST[key].name);
      li.appendChild(button("t", label, function () { return ui.view === key; },
        function () { go(key); }));
      sp.appendChild(li);
    });
    R.CASES.forEach(function (c) {
      var li = document.createElement("li");
      li.appendChild(button("t", CASE_LABEL[c], function () { return ui.kase === c; }, function () {
        ui.kase = c; stop(); ui.g = 0; render();
      }));
      cp.appendChild(li);
    });
    ["slow", "normal", "fast"].forEach(function (s) {
      sd.appendChild(button("c", s.charAt(0).toUpperCase() + s.slice(1),
        function () { return ui.speed === s; }, function () {
          ui.speed = s; if (ui.playing) { stop(); play(); } render();
        }));
    });
  }

  function go(view) {
    select(view);
    try { if (location.hash !== "#" + view) location.hash = view; } catch (e) { /* no address */ }
  }

  function select(view) {
    ui.view = view; stop(); ui.g = 0; render();
  }

  function about() {
    if (ui.view === "all") {
      return "The 9 stations in walk order. Each plays its clean run; the reader plays the run " +
        "chosen below. The walk stops at the first station that does not complete.";
    }
    var s = ST[ui.view];
    return "<b>" + R.esc(s.status_words) + ".</b> " + R.esc(s.status_line);
  }

  function render() {
    for (var p = 0; p < pressed.length; p++) {
      pressed[p][0].setAttribute("aria-pressed", pressed[p][1]() ? "true" : "false");
    }
    var q = seq(), n = R.total(q), at = R.locate(q, ui.g), seg = q.segments[at.seg];
    var tr = seg.trace, st = ST[seg.key];
    $("r-about").innerHTML = about();
    $("r-run").textContent = ui.playing ? "Pause" : "Run";
    $("r-run").setAttribute("aria-pressed", ui.playing ? "true" : "false");
    $("r-pos").textContent = "Step " + (ui.g + 1) + " of " + n;
    var list = $("r-all");
    list.hidden = ui.view !== "all";
    if (ui.view === "all") {
      var rs = R.rowStatus(q, ui.g), h = "";
      R.ORDER.forEach(function (key, m) {
        var v = rs[key], bad = v === "hold" || v === "error";
        h += "<li" + (key === seg.key ? ' class="on"' : "") + '><span class="n">' + (m + 1) +
          "</span><span>" + R.esc(ST[key].name) + '</span><span class="st' + (bad ? " bad" : "") +
          '">' + R.esc(v === "completed" ? "completed" : v === "hold" || v === "error" ?
          R.outcomeWord(v) : v) + "</span></li>";
      });
      list.innerHTML = h;
    }
    var w = '<p class="head">' + (ui.view === "all" ? "Station " + (R.ORDER.indexOf(seg.key) + 1) +
      " of 9 / " : "") + R.esc(st.name) + " / " + R.esc(CASE_LABEL[tr.case] || tr.case) + "</p><ol>";
    for (var i = 0; i <= at.i; i++) {
      var s = tr.steps[i];
      w += "<li" + (i === at.i ? ' class="now"' : "") + '><span class="tag">' + R.esc(s.tag) +
        "</span><code>" + R.esc(s.text) + "</code></li>";
    }
    var box = $("r-wire");
    box.innerHTML = w + "</ol>";
    box.scrollTop = box.scrollHeight;
    $("r-inst").innerHTML = '<p class="title">' + R.esc(st.name) + "</p>" + R.drawAt(tr, at.i);
    var out = $("r-outcome");
    if (at.last) {
      var bad = tr.outcome !== "completed";
      out.innerHTML = '<span class="word' + (bad ? " bad" : "") + '">' + R.esc(R.outcomeWord(tr.outcome)) +
        '</span><span class="ev">' + (ui.view === "all" ? R.esc(st.name) + ": " : "") +
        R.esc(tr.evidence) + "</span>";
    } else {
      out.innerHTML = "";
    }
  }

  function step() {
    var n = R.total(seq());
    if (ui.g < n - 1) ui.g++;
    if (ui.g >= n - 1) stop();
    render();
  }

  function play() {
    if (ui.g >= R.total(seq()) - 1) ui.g = 0;
    ui.playing = true;
    ui.timer = setInterval(step, R.SPEEDS[ui.speed]);
  }

  function stop() {
    ui.playing = false;
    if (ui.timer) { clearInterval(ui.timer); ui.timer = null; }
  }

  function toggle() { if (ui.playing) stop(); else play(); render(); }

  $("r-run").addEventListener("click", toggle);
  $("r-step").addEventListener("click", function () { stop(); step(); });
  $("r-reset").addEventListener("click", function () { stop(); ui.g = 0; render(); });
  document.addEventListener("keydown", function (e) {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    var t = e.target && e.target.tagName;
    if (e.key === " " || e.key === "Spacebar") {
      if (t === "BUTTON" || t === "A") return;
      e.preventDefault(); toggle();
    } else if (e.key === "ArrowRight") {
      e.preventDefault(); stop(); step();
    }
  });
  window.addEventListener("hashchange", function () {
    var v = R.parseHash(location.hash);
    if (v && v !== ui.view) select(v);
  });
  ui.view = R.parseHash(location.hash) || "culture";
  pickers();
  render();
})();
