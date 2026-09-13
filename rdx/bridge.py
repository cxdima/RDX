from __future__ import annotations

import secrets
import threading
import time

from .domain import Project, uid

# The build of bridge/live.js this studio expects. Max does not reliably reload
# that file, so a device can be connected and running an older script; when
# these disagree the device needs dragging out of Live and back in.
DEVICE_VERSION = 5


class Bridge:
    def __init__(self):
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.RLock()
        self.last_seen = 0
        self.live = {}
        self.pending = None
        self.result = None

    def status(self):
        with self.lock:
            if self.pending and time.time() - self.pending["created"] > 180:
                self.result = {"id": self.pending["id"], "ok": False, "message": "Transfer confirmation timed out. Check Live before sending again; a partial transfer may exist."}
                self.pending = None
            return {"connected": time.time() - self.last_seen < 10, "live": self.live, "pending": self.pending is not None, "result": self.result, "device_version": self.live.get("device_version"), "device_current": DEVICE_VERSION}

    def poll(self, state):
        with self.lock:
            self.last_seen, self.live = time.time(), state
            if self.pending and not self.pending.get("delivered"):
                self.pending["delivered"] = True
                return self.pending
            return None

    def acknowledge(self, result):
        with self.lock:
            if not self.pending or result.get("id") != self.pending["id"]:
                raise ValueError("Unexpected bridge acknowledgement")
            self.result, self.pending = result, None

    def send(self, project: Project, stems: dict[str, str]):
        with self.lock:
            if time.time() - self.last_seen >= 10:
                raise ValueError("Ableton is not connected")
            if self.pending:
                raise ValueError("Wait for the current Ableton transfer to finish")
            if self.live.get("has_content") and abs(float(self.live.get("tempo", 0)) - project.tempo) > 0.01:
                raise ValueError(f"The open Live Set has music at {self.live.get('tempo')} BPM; RDX is at {project.tempo:g}. Match the tempo or use an empty Set before transferring.")
            self.pending = {"id": uid(), "kind": "append_project", "project": project.model_dump(), "stems": stems, "created": time.time()}
            self.result = None
            return self.pending["id"]

    def probe(self, track: int, device: str):
        """Queue a one-shot: place a native device on a track and scan it."""
        with self.lock:
            if time.time() - self.last_seen >= 10:
                raise ValueError("Ableton is not connected")
            if self.pending:
                raise ValueError("Wait for the current Ableton command to finish")
            self.pending = {"id": uid(), "kind": "insert_device", "track": int(track), "device": str(device), "created": time.time()}
            self.result = None
            return self.pending["id"]
