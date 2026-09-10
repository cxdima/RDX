from __future__ import annotations

import json
import os
import selectors
import subprocess
import threading
from pathlib import Path

from .domain import Plan

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("RDX_DATA_DIR", ROOT / "data")).resolve()
MODEL = ROOT / "data" / "models" / "qwen3-4b"
ADAPTER = ROOT / "data" / "models" / "rdx-v1"

SYSTEM = """You are RDX, a local music co-producer. Return only JSON: {"summary":"a brief musical explanation","actions":[...]}. Each action has kind, optional track, optional section, and params. Use the supplied project context. Track and section targets may be IDs, exact names, or 'all'. Use selected_track and selected_section for requests about the selected part. Preserve protected tracks. Never invent devices or claim to hear audio you have not received. If the request needs clarification or unsupported processing, return actions:[] and explain briefly.
Supported actions and params:
project: name,tempo(40-240),key(C,C#,D,D#,E,F,F#,G,G#,A,A#,B),scale(major/minor).
compose: track,section; params density(0-1),variation(integer). Creates MIDI notes for lead,bass,chords,pad.
drums: track,section; params pattern(four_floor,breakbeat,halftime,minimal),density(0-1),variation(integer).
transpose: track,section; params semitones(integer), optional last_note(bool),start,end(beats).
rhythm: track,section; params grid(0.125,0.25,0.5,1,2),swing(0-0.45),humanize(0-0.08),velocity(1-127).
sound: track; params preset(saw,pluck,sine,pad,fm,drumkit),cutoff(60-20000Hz),resonance(0.1-15),attack(0.001-4s),release(0.01-8s),reverb(0-1),delay(0-0.8),drive(0-0.8),low,mid,high(-24 to 12dB).
mix: track; params volume_db(-60 to 6),delta_db,pan(-1 to 1),mute(bool),solo(bool).
arrange: section; params operation(add,duplicate,remove,move,update),name,bars(1-64),energy(0-1),index(zero-based).
master: params volume_db(-30 to 0),ceiling(-12 to 0),compression(-60 to 0).
add_track: params role(drums,bass,chords,lead,pad,audio),name.
duplicate_track: track; params name. remove_track: track; params {}.
protect: track; params locked(bool).
automation: track,section; params parameter(cutoff,volume_db,pan,reverb),points([[beat,value],...]).
notes: track,section; params operation(replace,add),notes([{pitch:0-127,start:beats,duration:beats,velocity:1-127},...]).
Only change what the user requests. Requests to create a full piece can combine arrangement, composition, drums, sound and mix actions. Keep replies concise."""


def parse_plan(text: str) -> Plan:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char == "{":
            try:
                obj, _ = decoder.raw_decode(text[index:])
                return Plan.model_validate(obj)
            except (ValueError, TypeError):
                continue
    raise ValueError("The local model did not return a valid musical edit. Try a more specific request.")


class LocalModel:
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        self.version = None

    def status(self):
        training = DATA / "training" / "status.json"
        details = json.loads(training.read_text()) if training.exists() else {}
        ready = (MODEL / "rdx-source.json").exists() and (MODEL / "chat_template.jinja").exists() and bool(list(MODEL.glob("*.safetensors")))
        active = (ADAPTER / "approved.json").exists()
        return {"downloaded": ready, "trained": active, "name": "RDX v1" if active else "Qwen3 local base", "training": details, "offline": True}

    def generate(self, project_context: dict, request: str, previous: list[dict]) -> Plan:
        with self.lock:
            status = self.status()
            if not status["downloaded"]:
                raise ValueError("The local model is not installed yet. The studio controls are available.")
            if status["training"].get("state") == "training":
                raise ValueError("The local model is training. The studio controls remain available.")
            version = "adapter" if status["trained"] else "base"
            if not self.process or self.process.poll() is not None or self.version != version:
                self.close()
                (DATA / "logs").mkdir(parents=True, exist_ok=True)
                self.log = (DATA / "logs" / "model.log").open("a")
                self.process = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-m", "rdx.model_worker", version], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True, bufsize=1)
                self.version = version
            self.process.stdin.write(json.dumps({"context": project_context, "request": request, "previous": previous[-4:]}) + "\n")
            self.process.stdin.flush()
            with selectors.DefaultSelector() as selector:
                selector.register(self.process.stdout, selectors.EVENT_READ)
                if not selector.select(timeout=150):
                    self.close()
                    raise ValueError("The local model took too long. No changes were applied; try a shorter request.")
                line = self.process.stdout.readline()
            if not line:
                raise ValueError("The local model stopped. Its diagnostic log has been saved.")
            response = json.loads(line)
            if "error" in response:
                raise ValueError(response["error"])
            return parse_plan(response["text"])

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if hasattr(self, "log"):
            self.log.close()
        self.process = None
