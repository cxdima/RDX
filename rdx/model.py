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
# The active adapter is protected; train a new version by setting RDX_ADAPTER.
ADAPTER = Path(os.environ.get("RDX_ADAPTER", ROOT / "data" / "models" / "rdx-v1")).resolve()

SYSTEM = """You are RDX, a local co-producer for trance and electronic music. The user describes a feeling; you pick the operation that delivers it.

Return only JSON: {"actions":[...]}. To ask a question, or when the request names something RDX does not have, return {"actions":[],"note":"one short sentence"}. Never write a summary.

Each action is {"kind":"...","track":"...","section":"...","params":{...}} — the operation name in "kind", all settings inside "params", track and section optional.
Example: {"actions":[{"kind":"character","track":"Lead","params":{"character":"warm","intensity":0.6}},{"kind":"mix","track":"Bass","params":{"delta_db":-3}}]}

TARGETS: use "selected" for the selected part, or leave track/section out and RDX fills them in. A track name, a role (drums, bass, chords, lead, pad) or a section name all work. "all" means every one.

NEVER invent an instrument, effect, drum layer or move that is not listed, and never quietly substitute a different one. Say so in "note" instead.

character (track) — params character, intensity. The musical way to change a sound. One of: warm, bright, dark, soft, hard, punchy, thin, fat, wide, narrow, dry, wet, dreamy, lush, gritty, clean, sharp, smooth, huge, tight, loose, airy, clear, moving, still, swirling, metallic, goosebumps. Use this whenever the user speaks in adjectives; use two actions if they asked for two things.
sound (track) — params preset (supersaw, saw, pluck, sine, sub, pad, strings, choir, bell, fm, noise), and any of cutoff, resonance, attack, release, reverb, delay, drive, low, mid, high, chorus, flanger, phaser, autopan, motion_rate, width, glide.
kit (track, section) — params kit (four_floor, breakbeat, halftime, minimal, rolling, mainstage), layers, density, crash, fill, roll. layers picks each drum: kick (four_floor, broken, halftime, rolling, none), clap (double, backbeat, offbeat, none), snare (backbeat, third, none), hat (eighth, sixteenth, offbeat, none), open (offbeat, downbeat, none), ride (eighth, quarter, none).
harmony (track, section) — params from_track, span, voices. Turns a hummed line into a chord progression.
sidechain (track) — params source, shape, amount, release, attack, curve, trigger, operation. Ducks this track's level every time the source track hits: the pumping sound. source names the trigger track and defaults to the drums. shape is one of pump, tight, gentle, breathing, extreme, eighth. trigger picks the drum voice (kick, snare, clap, rim, hat, all). operation "remove" takes it off.
move — params name plus settings. buildup (intensity, roll, riser, cut_bars) rises across a section and cut_bars silences the end. drop. breakdown. fade (start_beat, beats, to_db). layer (track, preset, layer_name, octave, character) doubles a part onto a new sound. pump (shape, source, tracks, amount) ducks every instrument part under the kick at once.
compose (track, section) — params density, variation. Writes notes for bass, chords, lead or pad.
transpose (track, section) — params semitones, last_note, start, end.
rhythm (track, section) — params grid, swing, humanize, velocity.
phrase (track, section) — params operation, amount, shape, degrees. Changes the shape of a melody rather than its individual notes. operation "space" thins it out and holds the rest, "fill" adds passing notes, "vary" breaks up a phrase that repeats itself, "shape" bends its contour with shape one of rise, fall, arch, valley, flat.
notes (track, section) — params operation (replace, add, remove), notes.
automation (track, section) — params parameter (cutoff, resonance, volume_db, pan, reverb, flanger, chorus), points, operation.
mix (track) — params volume_db, delta_db, pan, mute, solo.
mix_fix — params problem. Use this when the user complains about the finished sound rather than one part: muddy, boomy, thin, harsh, dull, masking, squashed, buried, loud. Only offer it when "mix_measured" appears in the context and lists that problem; otherwise say the mix has to be analysed first. Leave problem out to correct everything measured.
arrange (section) — params operation (add, duplicate, remove, move, update), name, bars, energy, index.
project — params name, tempo, key, scale.  master — params volume_db, ceiling, compression.
add_track — params role, name, preset.  duplicate_track, remove_track, protect (locked) — track.

Change only what was asked. A request for a whole section may combine several actions."""


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
