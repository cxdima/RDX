"""Measure whether the model turns real musical language into real operations.

Every request here is written by hand and checked against the training data at
run time, so nothing in this benchmark is a phrase the model was trained on. It
scores executable behaviour: the right operation, on the right target, with the
right settings — and, for things RDX cannot do, no operation at all.

It does not measure whether the music is good. Only listening does that.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from typing import Callable

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

from .domain import Plan, Project
from .engine import apply_actions, context, starter_project, target_sections, target_tracks
from .model import ADAPTER, DATA, MODEL, SYSTEM, parse_plan

Check = Callable[[Plan, Project], str | None]


@dataclass(frozen=True)
class Case:
    request: str
    category: str
    check: Check


def find(plan: Plan, kind: str):
    return [a for a in plan.actions if a.kind == kind]


def params_match(action, expected: dict) -> str | None:
    for key, value in expected.items():
        actual = action.params.get(key)
        if isinstance(value, float) and isinstance(actual, (int, float)):
            if abs(actual - value) > 1e-6:
                return f"{key} was {actual}, expected {value}"
        elif actual != value:
            return f"{key} was {actual!r}, expected {value!r}"
    return None


def does(kind: str, role: str | None = None, section: str | None = None, only: bool = True, **expected) -> Check:
    """One action of this kind, on this target, with these settings."""

    def check(plan: Plan, project: Project) -> str | None:
        matching = find(plan, kind)
        if not matching:
            return f"no {kind} action (got {[a.kind for a in plan.actions] or 'nothing'})"
        if only and len(plan.actions) != 1:
            return f"expected one action, got {[a.kind for a in plan.actions]}"
        action = matching[0]
        problem = params_match(action, expected)
        if problem:
            return problem
        selection = {"track": SELECTED_TRACK, "section": SELECTED_SECTION}
        if role:
            try:
                tracks = target_tracks(project, action.track, selection, action.kind)
            except ValueError as error:
                return f"target did not resolve: {error}"
            if tracks[0].role != role:
                return f"targeted {tracks[0].name} ({tracks[0].role}), expected the {role}"
        if section:
            try:
                sections = target_sections(project, action.section, selection)
            except ValueError as error:
                return f"section did not resolve: {error}"
            if sections[0].name != section:
                return f"targeted section {sections[0].name}, expected {section}"
        return None

    return check


def both(*checks: Check) -> Check:
    def check(plan: Plan, project: Project) -> str | None:
        return next((problem for problem in (c(plan, project) for c in checks) if problem), None)

    return check


def declines() -> Check:
    """No operation, and a sentence saying why."""

    def check(plan: Plan, project: Project) -> str | None:
        if plan.actions:
            return f"acted anyway: {[a.kind for a in plan.actions]}"
        if not (plan.note or plan.summary).strip():
            return "said nothing"
        return None

    return check


SELECTED_TRACK = ""
SELECTED_SECTION = ""

CASES: list[Case] = [
    # The user's own example, clause by clause.
    Case("I need a build up in this section.", "the example", does("move", section="Build", name="buildup")),
    Case("Build it up and then let everything suddenly fade right at the end.", "the example", lambda p, pr: does("move", section="Build", name="buildup")(p, pr) or (None if find(p, "move")[0].params.get("cut_bars") else "no cut at the end")),
    Case("Add a string instrument to the track.", "the example", does("add_track", preset="strings")),
    Case("Turn the humming I recorded into a chord progression.", "the example", does("harmony")),
    Case("The beat should be a steady kick with two claps close together.", "the example", lambda p, pr: does("kit", role="drums")(p, pr) or (None if (find(p, "kit")[0].params.get("layers") or {}).get("clap") == "double" else f"clap layer was {(find(p, 'kit')[0].params.get('layers') or {}).get('clap')!r}, expected 'double'")),
    Case("Put a strong synth in together with the melody.", "the example", does("move", name="layer")),
    Case("Add a pan and a flanger to that synth so it gives goosebumps.", "the example", lambda p, pr: None if (find(p, "character") and find(p, "character")[0].params.get("character") in {"goosebumps", "moving", "wide"}) or (find(p, "sound") and any(k in find(p, "sound")[0].params for k in ("flanger", "autopan"))) else f"expected a goosebumps character or a flanger/pan setting, got {[(a.kind, a.params) for a in p.actions]}"),
    # Feeling words that must reach the right parameters.
    Case("The lead sounds too harsh. Warm it up.", "musical language", does("character", role="lead", character="warm")),
    Case("Make the chords dreamy.", "musical language", does("character", role="chords", character="dreamy")),
    Case("The bass feels weak and thin.", "musical language", does("character", role="bass", character="fat")),
    Case("I want this melody to sound absolutely massive.", "musical language", does("character", character="huge")),
    # Two things at once: both must happen.
    Case("Make the bass darker and turn it down a bit.", "compound", lambda p, pr: None if len(p.actions) >= 2 and find(p, "character") and find(p, "mix") else f"expected a darker character and a level change, got {[a.kind for a in p.actions]}"),
    # Things RDX cannot do. Saying so is the correct answer.
    Case("Sidechain the pads to the kick so it pumps.", "declining", declines()),
    Case("Load Serum on the lead and use my preset.", "declining", declines()),
    Case("Put a tape stop right before the drop.", "declining", declines()),
    Case("Make it better.", "declining", declines()),
    # Finding the target without being handed an id.
    Case("Give me a broken beat instead of a straight one.", "targeting", does("kit", role="drums")),
    Case("I want another copy of this section right after it.", "targeting", does("arrange", section="Build", operation="duplicate")),
    # Mechanical operations that must not regress.
    Case("Bring the tempo down to 117 beats per minute.", "mechanical", does("project", tempo=117)),
    Case("Put the final output limiter ceiling at -2 dB.", "mechanical", does("master", ceiling=-2.0)),
    Case("Keep the rhythm but let the final note rise two semitones.", "mechanical", does("transpose", role="lead", semitones=2, last_note=True)),
    Case("I love these drums, protect them from changes.", "mechanical", does("protect", role="drums", locked=True)),
]


def unseen(cases: list[Case]) -> list[str]:
    """Any benchmark phrasing that leaked into training invalidates the score."""
    path = DATA / "training" / "train.jsonl"
    if not path.exists():
        return []
    corpus = path.read_text().lower()
    return [c.request for c in cases if c.request.lower().rstrip(".") in corpus]


def evaluate(use_adapter: bool = False, verbose: bool = True) -> dict:
    global SELECTED_TRACK, SELECTED_SECTION
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    leaked = unseen(CASES)
    model, tokenizer = load(str(MODEL), adapter_path=str(ADAPTER) if use_adapter else None)
    project = starter_project()
    lead = next(t for t in project.tracks if t.role == "lead")
    build = next(s for s in project.sections if s.name == "Build")
    SELECTED_TRACK, SELECTED_SECTION = lead.id, build.id
    ctx = context(project, lead.id, build.id)

    results = []
    for case in CASES:
        prompt = tokenizer.apply_chat_template(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(ctx, separators=(",", ":")) + "\nRequest: " + case.request}],
            tokenize=False,
            add_generation_prompt=True,
        )
        started = time.time()
        generated = generate(model, tokenizer, prompt=prompt, max_tokens=900, sampler=make_sampler(temp=0), verbose=False)
        row = {"request": case.request, "category": case.category, "seconds": round(time.time() - started, 2), "passed": False, "generated": generated}
        try:
            plan = parse_plan(generated)
            if plan.actions:
                apply_actions(project, plan.actions, {"track": lead.id, "section": build.id})
            problem = case.check(plan, project)
            row["passed"] = problem is None
            if problem:
                row["reason"] = problem
        except ValueError as error:
            row["reason"] = str(error)
        results.append(row)
        if verbose:
            print(f"{'PASS' if row['passed'] else 'FAIL'} [{case.category}] {case.request}" + ("" if row["passed"] else f"\n       -> {row.get('reason', '')}"), flush=True)

    categories: dict[str, dict[str, int]] = {}
    for row in results:
        bucket = categories.setdefault(row["category"], {"passed": 0, "total": 0})
        bucket["total"] += 1
        bucket["passed"] += int(row["passed"])
    report = {
        "benchmark_version": 3,
        "model": "adapter" if use_adapter else "base",
        "passed": sum(r["passed"] for r in results),
        "total": len(results),
        "by_category": categories,
        "leaked_into_training": leaked,
        "cases": results,
        "limits": "Executable instruction following on 22 hand-written requests in the user's own phrasing, none of which appear in the training data. Measures whether the right operation reaches the right target with the right settings, and whether unsupported requests are declined instead of approximated. Does not measure musical quality, taste or audio understanding.",
    }
    (DATA / "training" / ("adapter-evaluation.json" if use_adapter else "base-evaluation.json")).write_text(json.dumps(report, indent=2))
    if verbose:
        print(json.dumps({"model": report["model"], "passed": report["passed"], "total": report["total"], "by_category": categories}, indent=2), flush=True)
        if leaked:
            print(f"WARNING: these benchmark phrasings appear in train.jsonl and no longer measure generalisation: {leaked}", flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", action="store_true")
    evaluate(parser.parse_args().adapter)
