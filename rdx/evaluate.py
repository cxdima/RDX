"""Check generated operations against unfamiliar instructions and real engine validation."""
import argparse
import gc
import json
import os
import time

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

from .domain import Action
from .engine import apply_actions, context, starter_project, target_sections, target_tracks
from .model import ADAPTER, DATA, MODEL, SYSTEM, parse_plan


CASES = [
    ("Bring the tempo down to 117 beats per minute.", "project", {"tempo": 117}),
    ("The bass is overpowering everything. Turn it down by 3 dB.", "mix", {"delta_db": -3}),
    ("Move the lead melody one octave higher, keeping its timing.", "transpose", {"semitones": 12}),
    ("Let the ending note of this melody go up two semitones. Keep all the other notes.", "transpose", {"semitones": 2, "last_note": True}),
    ("Give me a breakbeat drum pattern in the main section.", "drums", {"pattern": "breakbeat"}),
    ("I want an extra copy of the main section immediately after it.", "arrange", {"operation": "duplicate"}),
    ("I love these drums. Protect them from changes.", "protect", {"locked": True}),
    ("Switch the lead instrument to an FM sound.", "sound", {"preset": "fm"}),
    ("Make the lead reverb completely dry, at zero.", "sound", {"reverb": 0}),
    ("Put the final output limiter ceiling at -2 dB.", "master", {"ceiling": -2}),
    ("Add a new pad instrument track named Atmosphere.", "add_track", {"role": "pad", "name": "Atmosphere"}),
    ("Write a bass line for the main section.", "compose", {}),
]
TARGETS = [None, "bass", "lead", "lead", "drums", None, "drums", "lead", "lead", None, None, "bass"]


def evaluate(use_adapter=False):
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    model, tokenizer = load(str(MODEL), adapter_path=str(ADAPTER) if use_adapter else None)
    project = starter_project()
    lead = next(t for t in project.tracks if t.role == "lead")
    ctx = context(project, lead.id, project.sections[2].id)
    results = []
    for (request, kind, expected), target in zip(CASES, TARGETS):
        prompt = tokenizer.apply_chat_template([{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(ctx, separators=(",", ":")) + "\nRequest: " + request}], tokenize=False, add_generation_prompt=True)
        started = time.time()
        generated = generate(model, tokenizer, prompt=prompt, max_tokens=900, sampler=make_sampler(temp=0), verbose=False)
        row = {"request": request, "generated": generated, "seconds": round(time.time() - started, 2), "passed": False}
        try:
            plan = parse_plan(generated)
            apply_actions(project, plan.actions)
            if len(plan.actions) != 1:
                raise ValueError("Expected exactly the requested edit, without additional actions")
            action = plan.actions[0]
            expected_params = dict(expected)
            if kind == "mix" and "delta_db" in expected and "volume_db" in action.params and "delta_db" not in action.params:
                expected_params = {"volume_db": next(t.volume_db for t in project.tracks if t.role == target) + expected["delta_db"]}
            correct = action.kind == kind and all(action.params.get(k) == v for k, v in expected_params.items())
            if target:
                tracks = target_tracks(project, action.track)
                correct = correct and len(tracks) == 1 and tracks[0].role == target
            if kind in {"compose", "drums", "arrange", "transpose"}:
                sections = target_sections(project, action.section)
                correct = correct and len(sections) == 1 and sections[0].id == project.sections[2].id
            allowed = set(expected_params) | ({"variation", "density"} if kind in {"compose", "drums"} else set())
            if kind == "transpose" and "last_note" not in expected and action.params.get("last_note") is False:
                allowed.add("last_note")
            row["passed"] = correct and not (set(action.params) - allowed)
        except ValueError as error:
            row["error"] = str(error)
        results.append(row)
        print(f"{'PASS' if row['passed'] else 'FAIL'} {request} ({row['seconds']}s)", flush=True)
    report = {"benchmark_version": 2, "max_tokens": 900, "model": "adapter" if use_adapter else "base", "passed": sum(r["passed"] for r in results), "total": len(results), "cases": results, "limits": "Measures executable instruction following on 12 authored requests; accepts equivalent absolute/relative gain and no-op last_note flags. Does not establish musical quality, audio understanding, or expert production ability."}
    (DATA / "training" / ("adapter-evaluation.json" if use_adapter else "base-evaluation.json")).write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in ("model", "passed", "total")}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", action="store_true")
    args = parser.parse_args()
    evaluate(args.adapter)
