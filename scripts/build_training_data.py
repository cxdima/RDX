"""Generate executable instruction examples; these are synthetic, not producer judgments."""
import json
import random
from pathlib import Path

from rdx.domain import Action
from rdx.engine import apply_actions, context, starter_project
from rdx.model import SYSTEM

ROOT = Path(__file__).resolve().parent.parent
DESTINATION = ROOT / "data/training"


def example(request, summary, actions, ctx):
    return {"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(ctx, separators=(",", ":")) + "\nRequest: " + request}, {"role": "assistant", "content": json.dumps({"summary": summary, "actions": actions}, separators=(",", ":"))}]}


def build():
    DESTINATION.mkdir(parents=True, exist_ok=True)
    counts = {}
    # Seeded contexts differ by split; request templates deliberately overlap.
    for split, family_seeds in {"train": range(24), "valid": range(100, 103), "test": range(200, 203)}.items():
        records = []
        for seed in family_seeds:
            rng = random.Random(seed)
            project = starter_project()
            project.seed = seed
            project.tempo = rng.choice([108, 118, 124, 128, 132, 138])
            section = project.sections[2]
            lead = next(t for t in project.tracks if t.role == "lead")
            ctx = context(project, lead.id, section.id)

            def add(request, summary, kind, params, track=None, selected_section=None):
                action = {"kind": kind, "params": params}
                if track is not None:
                    action["track"] = track
                if selected_section is not None:
                    action["section"] = selected_section
                apply_actions(project, [Action.model_validate(action)])
                records.append(example(request, summary, [action], ctx))

            for role in ("lead", "bass", "chords", "pad"):
                if role == "pad":
                    add("Add a pad track", "Added a pad track.", "add_track", {"role": "pad", "name": "Pad"})
                    continue
                density = rng.choice([0.35, 0.6, 0.85])
                add(f"Write a {'sparse' if density < 0.5 else 'busy' if density > 0.8 else 'balanced'} {role} part in the main section", f"A new {role} phrase for the main section.", "compose", {"density": density, "variation": seed}, role, section.id)
            for pattern, name in (("four_floor", "four on the floor"), ("breakbeat", "broken beat"), ("halftime", "half time"), ("minimal", "minimal")):
                add(f"Make the drums {name} in this section", f"Changed the drum pattern to {name}.", "drums", {"pattern": pattern, "density": 0.6}, "drums", section.id)
            semitones = rng.choice([2, 5, 7, 12, -2, -5, -12])
            add(f"Transpose the selected part by {semitones} semitones", "Transposed the selected phrase with its rhythm preserved.", "transpose", {"semitones": semitones}, lead.id, section.id)
            add("Keep the rhythm but raise the final note two semitones", "Raised only the final note.", "transpose", {"semitones": 2, "last_note": True}, lead.id, section.id)
            add("Quantize the lead to sixteenth notes", "Aligned the lead to sixteenth notes.", "rhythm", {"grid": 0.25}, "lead", section.id)
            add("Give the drums a little swing", "Added a light swing to the drums.", "rhythm", {"grid": 0.5, "swing": 0.18}, "drums", section.id)
            add("Humanize this phrase slightly", "Added subtle timing variation.", "rhythm", {"grid": 0.25, "humanize": 0.025}, lead.id, section.id)
            for setting, value, request in [("cutoff", 1800, "Darken the lead"), ("cutoff", 12000, "Brighten the lead"), ("release", 0.12, "Shorten the lead release"), ("release", 1.2, "Give the lead a longer tail"), ("reverb", 0.4, "Add more space to the lead"), ("reverb", 0, "Make the lead completely dry"), ("delay", 0.3, "Add an echo to the lead"), ("drive", 0.2, "Add some grit to the lead"), ("attack", 0.5, "Soften the start of the lead"), ("high", -4, "Reduce the lead's high frequencies")]:
                add(request, "Adjusted the lead sound for auditioning.", "sound", {setting: value}, "lead")
            for preset in ("saw", "pluck", "sine", "pad", "fm"):
                add(f"Use the {preset} sound on the lead", f"Selected the {preset} sound.", "sound", {"preset": preset}, "lead")
            amount = rng.choice([1, 2, 3, 4, 6])
            add(f"Lower the bass by {amount} dB", f"Lowered the bass by {amount} dB.", "mix", {"delta_db": -amount}, "bass")
            add(f"Raise the chords by {amount} dB", f"Raised the chords by {amount} dB.", "mix", {"delta_db": amount}, "chords")
            add("Pan the chords a little left", "Moved the chords slightly left.", "mix", {"pan": -0.25}, "chords")
            add("Mute the drums", "Muted the drums.", "mix", {"mute": True}, "drums")
            add("Bring the drums back", "Unmuted the drums.", "mix", {"mute": False}, "drums")
            add("Solo the bass", "Soloed the bass.", "mix", {"solo": True}, "bass")
            add("Keep the drums exactly as they are", "Protected the drum track.", "protect", {"locked": True}, "drums")
            add("Unlock the drums", "Removed protection from the drums.", "protect", {"locked": False}, "drums")
            add("Repeat the main section once", "Added a copy of the main section.", "arrange", {"operation": "duplicate"}, selected_section=section.id)
            add("Add an eight-bar breakdown", "Added an eight-bar breakdown.", "arrange", {"operation": "add", "name": "Breakdown", "bars": 8, "energy": 0.3})
            add("Set the master ceiling to minus one dB", "Set the limiter ceiling to -1 dB.", "master", {"ceiling": -1})
            add("Leave more headroom on the master", "Reduced the master output by setting it to -6 dB.", "master", {"volume_db": -6})
            tempo = rng.choice([110, 120, 126, 128, 136, 140])
            add(f"Set the tempo to {tempo} BPM", f"Set the tempo to {tempo} BPM.", "project", {"tempo": tempo})
            add("Open the lead filter through the main section", "Added a filter rise across the main section.", "automation", {"parameter": "cutoff", "points": [[0, 800], [section.bars * 4, 12000]]}, "lead", section.id)
            add("Duplicate the lead track", "Created a separate copy of the lead.", "duplicate_track", {"name": "Lead 2"}, "lead")
            combined = [{"kind": "compose", "track": role, "section": "all", "params": {"density": 0.6, "variation": seed}} for role in ("bass", "chords", "lead")]
            combined.insert(0, {"kind": "drums", "track": "drums", "section": "all", "params": {"pattern": "four_floor", "density": 0.7}})
            apply_actions(project, [Action.model_validate(a) for a in combined])
            records.append(example("Create drums, bass, chords and a melody across the whole arrangement", "Created an editable arrangement across all four parts.", combined, ctx))
            records.append(example("Load a plugin that is not installed", "That plugin is unavailable. Which installed instrument should I use?", [], ctx))
            records.append(example("Make it sound better", "Which part should change, and what feels wrong when you listen?", [], ctx))
        rng = random.Random(2026)
        rng.shuffle(records)
        (DESTINATION / f"{split}.jsonl").write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records))
        counts[split] = len(records)
    (DESTINATION / "dataset.json").write_text(json.dumps({"counts": counts, "source": "Synthetic instruction/edit pairs validated by the RDX edit engine. No human musical-quality labels.", "split": "Independent seeded musical contexts; request templates are shared across splits. This does not measure novel phrasing or musical expertise."}, indent=2))
    print(json.dumps(counts))


if __name__ == "__main__":
    build()
