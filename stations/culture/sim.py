"""SIMULATED tissue-culture station behind a STAND-IN interface.

The hall leaves the supplier and interface open, so there is no real protocol. The message
format here (1 JSON object per line) is made up for the example and stands in for whatever the
chosen supplier offers (TODO_1). The simulator parses every message, keeps the batches it knows
and which ones were released, and raises on any message it does not understand.
"""

import json
from typing import Callable, Dict, List, Optional


class SimUnknownMessage(Exception):
  """The adapter sent a message this simulator does not understand."""


class SimCultureStation:
  def __init__(self, batches: List[str], fault: Optional[str] = None) -> None:
    self.known = set(batches)
    self.released: Dict[str, str] = {}  # batch id -> worklist id
    self.releases_executed = 0
    self.fault = fault
    self.log: Optional[Callable[[str], None]] = None

  def snapshot(self) -> dict:
    """Station state for a replay: releases carried out and the batches it knows."""
    return {"released": dict(self.released), "executed": self.releases_executed,
            "known_batches": sorted(self.known)}

  def handle(self, line: str) -> Optional[str]:
    """Take 1 message; return the reply line, or None when the reply is lost."""
    if self.log:
      self.log(f"send  {line}")
    try:
      msg = json.loads(line)
    except json.JSONDecodeError as e:
      raise SimUnknownMessage(f"not JSON: {line!r}") from e
    if not isinstance(msg, dict) or msg.get("op") != "release" or \
        set(msg) != {"op", "batch", "worklist"}:
      raise SimUnknownMessage(f"unknown message {line!r}")
    batch = msg["batch"]
    if batch not in self.known or self.fault == "device_error":
      reply = json.dumps({"ok": False, "error": "unknown_batch", "batch": batch})
    elif batch in self.released:
      reply = json.dumps({"ok": True, "batch": batch, "already": True})
    else:
      self.released[batch] = msg["worklist"]
      self.releases_executed += 1
      if self.fault == "lost_reply":
        return None
      reply = json.dumps({"ok": True, "batch": batch})
    if self.log:
      self.log(f"recv  {reply}")
    return reply
