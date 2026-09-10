"""Generate, validate and split the instruction dataset.

Every example is executed against the real edit engine before it is written, so
the dataset cannot teach an operation that would fail. Phrasings are split
across train/valid/test so no way of asking appears in more than one split.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from ..domain import Action
from ..engine import apply_actions, context, starter_project
from ..model import SYSTEM
from ..musical import mixdown
from .intents import MEASURED_BANDS, Intent, Scene, intents

ROOT = Path(__file__).resolve().parent.parent.parent
DESTINATION = ROOT / "data/training"

KEYS = ("A", "C", "D", "F", "G", "E", "B", "F#")
TEMPOS = (108, 118, 124, 128, 132, 136, 138, 140)
ROLES = ("lead", "bass", "chords", "pad")
# Custom names appear as often as defaults so targeting by name is learned.
NAME_SETS = (
    {},
    {"drums": "Beat", "bass": "Sub", "chords": "Keys", "lead": "Melody"},
    {"drums": "Kit", "bass": "Bassline", "chords": "Pads", "lead": "Top Line"},
    {"lead": "Hook", "bass": "Low End"},
)


def synthetic_measurement(project, problem: str) -> dict:
    """A measurement shaped to show exactly one problem, without any audio.

    Mix analysis normally comes from rendered stems. Teaching the model *when*
    to reach for a correction needs only the shape of the reading, not the
    audio behind it, and generating it here keeps the dataset build fast and
    deterministic. The numbers still go through the real finding rules.
    """
    bands = MEASURED_BANDS[problem]
    tracks = [
        mixdown.TrackMix(track_id=track.id, name=track.name, role=track.role, rms_db=-14.0, peak_db=-4.0, crest_db=10.0, correlation=0.9, bands=dict(bands), energy=1.0)
        for track in project.tracks
    ]
    return mixdown.Mix(tracks=tracks, bands=dict(bands), crest_db=10.0, peak_db=-1.0, loudness_lufs=-14.0).as_dict()


def make_scene(rng: random.Random, measured: str | None = None) -> tuple[Scene, object, dict, dict | None]:
    """A project, the selection inside it, and the context the model will see."""
    project = starter_project()
    project.seed = rng.randint(1, 9999)
    project.tempo = rng.choice(TEMPOS)
    project.key = rng.choice(KEYS)
    project.scale = rng.choice(("minor", "minor", "major"))
    names = rng.choice(NAME_SETS)
    for track in project.tracks:
        if track.role in names:
            track.name = names[track.role]
    role = rng.choice(ROLES)
    selected = next((t for t in project.tracks if t.role == role), None)
    if selected is None:  # the starter has no pad track; fall back to the lead
        role = "lead"
        selected = next(t for t in project.tracks if t.role == "lead")
    section = rng.choice([s for s in project.sections if any(c.section_id == s.id for c in selected.clips)] or project.sections)
    project = type(project).model_validate(project.model_dump())
    scene = Scene(
        tempo=project.tempo,
        key=project.key,
        scale=project.scale,
        selected_role=role,
        selected_section=section.id,
        selected_bars=section.bars,
        track_names={t.role: t.name for t in project.tracks},
    )
    reading = synthetic_measurement(project, measured) if measured else None
    return scene, project, context(project, selected.id, section.id, reading), reading


def fill(phrasing: str, scene: Scene) -> str:
    return (
        phrasing.replace("{track}", scene.name(scene.selected_role))
        .replace("{role}", scene.selected_role)
        .replace("{tempo}", str(scene.tempo))
    )


def split_phrasings(intent: Intent, rng: random.Random) -> dict[str, list[str]]:
    """Divide an intent's phrasings so no wording crosses splits."""
    phrasings = list(intent.phrasings)
    rng.shuffle(phrasings)
    if len(phrasings) < 3:
        return {"train": phrasings, "valid": [], "test": []}
    held = max(1, len(phrasings) // 6)
    return {"train": phrasings[: -2 * held], "valid": phrasings[-2 * held : -held], "test": phrasings[-held:]}


def example(request: str, actions: list[dict], note: str, ctx: dict) -> dict:
    target: dict = {"actions": actions}
    if note:
        target["note"] = note
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(ctx, separators=(",", ":")) + "\nRequest: " + request},
            {"role": "assistant", "content": json.dumps(target, separators=(",", ":"))},
        ]
    }


def build() -> dict:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    catalogue = intents()
    rng = random.Random(2026)
    records: dict[str, list[dict]] = {"train": [], "valid": [], "test": []}
    skipped: dict[str, int] = {}
    produced: dict[str, int] = {}

    for intent in catalogue:
        assignment = split_phrasings(intent, random.Random(f"split:{intent.name}"))
        for split, phrasings in assignment.items():
            repeats = intent.scenes if split == "train" else 1
            for phrasing in phrasings:
                for _ in range(repeats):
                    scene, project, ctx, reading = make_scene(rng, intent.measured)
                    try:
                        actions, note = intent.build(scene, rng)
                        if actions:
                            # Refuse to teach anything the engine will not run.
                            apply_actions(project, [Action.model_validate(a) for a in actions], {"track": ctx["selected"]["track"], "section": ctx["selected"]["section"]}, None, reading)
                    except Exception:
                        skipped[intent.name] = skipped.get(intent.name, 0) + 1
                        continue
                    records[split].append(example(fill(phrasing, scene), actions, note, ctx))
                    produced[intent.name] = produced.get(intent.name, 0) + 1

    empty = [i.name for i in catalogue if not produced.get(i.name)]
    if empty:
        raise RuntimeError(f"These intents produced no valid examples: {', '.join(empty)}")

    for split, rows in records.items():
        random.Random(7).shuffle(rows)
        (DESTINATION / f"{split}.jsonl").write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))

    report = {
        "counts": {split: len(rows) for split, rows in records.items()},
        "intents": len(catalogue),
        "skipped": skipped,
        "source": "Synthetic instruction/operation pairs, every one executed against the RDX edit engine before being written. No human musical-quality labels.",
        "split": "By phrasing family: the wordings in valid and test never appear in train, so validation measures new phrasing rather than recall. Musical contexts are randomised independently.",
        "targets": "The assistant returns operations only. Summaries are generated by the engine from the real change, so the model is never trained to describe its own edit.",
    }
    (DESTINATION / "dataset.json").write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
