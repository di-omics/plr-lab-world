"""The decoding METHOD on a SYNTHETIC reader (sim.py), in 3 steps, then the draft class.

Nothing here is a PHERAstar command. The frames are upstream's BMG framing around made-up ASCII
payloads "TODO_1".."TODO_4". It shows how one would decode the real reader, not what it speaks.
"""

import json
import os
import tempfile
from collections import Counter
from types import SimpleNamespace

from plr_re import capture
from plr_re.decode import diff_frames, load_serial_log, scan_modbus_stream
from plr_re.guards import Guards
from plr_re.protocolmap import Command, ProtocolMap, Transport
from plr_re.replay import GuardedReplayer
from pylabrobot.bmg_labtech.protocol.framing import ftdi_extract_payload, ftdi_validate_frame

from .pherastar_draft import PHERAstarDraft, ReaderDeviceError, ReplyLost
from .sim import SimByteConn, SimTransport, SyntheticReader, VendorStandIn

STATION = "reader"
ACTIONS = ["tray_out", "tray_in", "read_plate"]


def hexs(data: bytes, keep: int = 24) -> str:
  s = " ".join(f"{b:02x}" for b in data[:keep])
  return s + (f" ... ({len(data)} bytes)" if len(data) > keep else "")


def split_frames(stream: bytes) -> list:
  """Not in plr_re (decode.py has diff, Modbus and HAR only): test the sibling framing by
  cutting the stream at each size field and checking it with upstream's validator."""
  frames, i = [], 0
  while i < len(stream):
    size = int.from_bytes(stream[i + 1 : i + 3], "big")
    frame = stream[i : i + size]
    ftdi_validate_frame(frame, header=frame[3])  # STX, size, CR, 24-bit sum
    frames.append(frame)
    i += size
  return frames


async def run(fault: str | None = None, log=print) -> dict:
  """Run the example once, in simulation only."""
  sim, tick = SyntheticReader(), iter(range(1, 10_000))
  tap = lambda tag, data: log(f"{tag:<6}{hexs(data)}")  # noqa: E731
  with tempfile.TemporaryDirectory() as tmp:
    host, rdr = os.path.join(tmp, "host.jsonl"), os.path.join(tmp, "reader.jsonl")
    log("ask   (a) capture: vendor stand-in does 3 actions, 1 at a time, each marked")
    real_time, capture.time = capture.time, SimpleNamespace(time=lambda: next(tick))
    try:
      marks = capture.Marks(os.path.join(tmp, "marks.jsonl"))
      vendor = VendorStandIn(sim, host, rdr, clock=lambda: next(tick))
      for action in ACTIONS:
        used = vendor.do(action)
        marks.mark(action)
        log(f"state captured {action}: {' + '.join(used)}; {sim.state()}")
    finally:
      capture.time = real_time
    log("ask   (b) decode: framing, then group frames by action mark")
    stream = load_serial_log(host)
    frames = split_frames(stream)
    log(f"state {len(frames)} host frames fit STX|size|hdr|payload|sum24|CR, header "
        f"0x{frames[0][3]:02x}; Modbus RTU frames found: {len(scan_modbus_stream(stream))}")
    chunks = [json.loads(line) for line in open(host, encoding="utf-8")]
    groups, last = {}, 0
    for m in marks.marks:
      groups[m.label] = [bytes.fromhex(c["hex"]) for c in chunks if last < c["t"] <= m.t]
      last = m.t
    seen = Counter(f for fs in groups.values() for f in fs)
    status = [f for f, n in seen.items() if n == len(ACTIONS)][0]
    log(f"state in every window (status candidate): {ftdi_extract_payload(status)!r}")
    action_frame = {a: [f for f in fs if f != status][0] for a, fs in groups.items()}
    d = diff_frames(action_frame["tray_out"], action_frame["tray_in"])
    log(f"state tray_out vs tray_in differ at offsets {[x.offset for x in d]}")
    pm = ProtocolMap(device="SYNTHETIC reader, not a PHERAstar", transport=Transport.SERIAL)
    for name, frame in [("TODO_4", status)] + [(f"TODO_{i + 1}", action_frame[a])
                                               for i, a in enumerate(ACTIONS)]:
      pm.commands[name] = Command(name=name, frame_template=frame.hex(), decoded=True,
                                  actuating=name != "TODO_4", notes="meaning = its mark only")
    log(f"state protocol map coverage {pm.coverage()['decoded']}/{pm.coverage()['total']}")
    log("ask   (c) replay TODO_3 (read) behind plr_re guards: armed, actuation allowed (sim)")
    sim.phase, conn = "replay", SimByteConn(sim, tap)
    replayer = GuardedReplayer(pm, Guards(armed=True, allow_actuation=True), conn=conn)
    replayer.setup()
    frame = replayer.send("TODO_3")
    while len(frame) < int.from_bytes(frame[1:3], "big"):  # replay.py:102 reads once, 512 max
      frame += conn.read()
    ftdi_validate_frame(frame, header=frame[3])
    log(f"state replay: {(len(ftdi_extract_payload(frame)) - 4) // 2} values back; {sim.state()}")
    log("ask   (d) the same read through the draft driver class")
    sim.phase, sim.fault = "driver", fault
    transport = SimTransport(sim, tap)
    # --8<-- snippet
    reader = PHERAstarDraft(transport=transport)  # unverified, commands are TODO_n
    await reader.setup()  # logs a loud "unverified" warning
    try:
      await reader.ensure_tray_in()  # reads state, moves only if needed, confirms
      values = await reader.read_plate()  # 1 read command, never re-sent
      outcome = "completed"
      evidence = f"{len(values)} made-up values, well A1 = {values[0]}"
    except ReplyLost as e:  # read sent, no reply: stop here, a human checks
      outcome, evidence = "hold", str(e)
    except ReaderDeviceError as e:  # error bit set in the reply
      outcome, evidence = "error", f"device error codes {e.codes} (synthetic code)"
    finally:
      await reader.stop()
    # --8<-- end
  log(f"state {sim.state()}; executed in (d): {dict(sim.executed.get('driver', {}))}")
  log(f"done  {outcome}: {evidence}")
  return {"station": STATION, "outcome": outcome, "evidence": evidence, "sim": sim}


if __name__ == "__main__":
  import asyncio

  asyncio.run(run())
