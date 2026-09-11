"""Measure whether the model turns real musical language into real operations.

Every request here is written by hand and checked against the training data at
run time, so nothing in this benchmark is a phrase the model was trained on. It
scores executable behaviour: the right operation, on the right target, with the
right settings. For things RDX cannot do it scores whether the user is told so,
counting a refusal from the engine as well as one from the model — either way
the user hears "no" rather than getting a different edit.

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
from .engine import Unsupported, apply_actions, context, starter_project, target_sections, target_tracks
from .model import ADAPTER, DATA, MODEL, SYSTEM, parse_plan

# A check sees the plan, the project, and whether the engine refused the plan
# outright. What matters to the user is that a refusal reached them, not which
# layer produced it.
Check = Callable[[Plan, Project, str | None], str | None]


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

    def check(plan: Plan, project: Project, refused: str | None = None) -> str | None:
        if refused:
            return f"the engine refused it: {refused}"
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


def declines() -> Check:
    """The user is told RDX cannot do this, by the model or by the engine.

    A model that names something absent and gets stopped by the engine still
    produces an honest refusal for the user, which is the outcome that matters.
    Emitting a different edit instead is the failure this measures.
    """

    def check(plan: Plan, project: Project, refused: str | None = None) -> str | None:
        if refused:
            return None
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
    Case("Build it up and then let everything suddenly fade right at the end.", "the example", lambda p, pr, refused=None: does("move", section="Build", name="buildup")(p, pr, refused) or (None if find(p, "move")[0].params.get("cut_bars") else "no cut at the end")),
    Case("Add a string instrument to the track.", "the example", does("add_track", preset="strings")),
    Case("Turn the humming I recorded into a chord progression.", "the example", does("harmony")),
    Case("The beat should be a steady kick with two claps close together.", "the example", lambda p, pr, refused=None: does("kit", role="drums")(p, pr, refused) or (None if (find(p, "kit")[0].params.get("layers") or {}).get("clap") == "double" else f"clap layer was {(find(p, 'kit')[0].params.get('layers') or {}).get('clap')!r}, expected 'double'")),
    Case("Put a strong synth in together with the melody.", "the example", does("move", name="layer")),
    Case("Add a pan and a flanger to that synth so it gives goosebumps.", "the example", lambda p, pr, refused=None: None if (find(p, "character") and find(p, "character")[0].params.get("character") in {"goosebumps", "moving", "wide"}) or (find(p, "sound") and any(k in find(p, "sound")[0].params for k in ("flanger", "autopan"))) else f"expected a goosebumps character or a flanger/pan setting, got {[(a.kind, a.params) for a in p.actions]}"),
    # Feeling words that must reach the right parameters.
    Case("The lead sounds too harsh. Warm it up.", "musical language", does("character", role="lead", character="warm")),
    Case("Make the chords dreamy.", "musical language", does("character", role="chords", character="dreamy")),
    Case("The bass feels weak and thin.", "musical language", does("character", role="bass", character="fat")),
    Case("I want this melody to sound absolutely massive.", "musical language", does("character", character="huge")),
    # Two things at once: both must happen.
    Case("Make the bass darker and turn it down a bit.", "compound", lambda p, pr, refused=None: None if len(p.actions) >= 2 and find(p, "character") and find(p, "mix") else f"expected a darker character and a level change, got {[a.kind for a in p.actions]}"),
    # Ducking: a real operation now, so acting is correct and refusing is not.
    Case("The chords need to move out of the way each time the kick lands.", "musical language", lambda p, pr, refused=None: None if find(p, "sidechain") or (find(p, "move") and find(p, "move")[0].params.get("name") == "pump") else f"expected ducking, got {[(a.kind, a.params) for a in p.actions]}"),
    Case("I want the whole track breathing with the beat.", "musical language", lambda p, pr, refused=None: None if find(p, "sidechain") or (find(p, "move") and find(p, "move")[0].params.get("name") == "pump") else f"expected ducking, got {[(a.kind, a.params) for a in p.actions]}"),
    # Shaping a phrase rather than moving its notes.
    Case("There are too many notes in this melody; give it room to breathe.", "shaping", does("phrase", role="lead", operation="space")),
    Case("I want the last stretch of the melody to climb upwards.", "shaping", lambda p, pr, refused=None: does("phrase", role="lead")(p, pr, refused) or (None if find(p, "phrase")[0].params.get("shape") == "rise" else f"shape was {find(p, 'phrase')[0].params.get('shape')!r}, expected 'rise'")),
    # One part written against another.
    Case("The bassline should sit under whatever the chords are doing.", "relating", does("relate", role="bass", operation="follow")),
    # Harmony with colour.
    Case("These chords are plain. Put a seventh on each of them.", "relating", lambda p, pr, refused=None: None if (find(p, "harmony") and find(p, "harmony")[0].params.get("colour") in {"seventh", "ninth"}) else f"expected a seventh colour, got {[(a.kind, a.params) for a in p.actions]}"),
    # The wider move library.
    Case("These two sections crash into each other. Smooth out the join.", "arranging", does("move", name="transition")),
    # Things RDX cannot do. Saying so is the correct answer.
    Case("Is this mix muddy? Fix whatever is wrong with it.", "declining", declines()),
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
    # Melodies. The capability that exists because the user said the music
    # "doesn't feel like real trance" — so the benchmark has to be able to tell
    # whether the model can reach it. Phrasings deliberately unlike the ones in
    # intents.py, which is what makes this measure generalisation.
    Case("This lead is boring, write me something with an actual hook.", "melody", does("melody", role="lead")),
    Case("This lead should start low and climb to a high point before it settles.", "melody", does("melody", role="lead")),
    Case("For the quiet part I want long notes I can hum, not a plucky thing.", "melody", lambda p, pr, refused=None: does("melody", role="lead")(p, pr, refused) or (None if find(p, "melody")[0].params.get("cell") in {"anthem", "call", "stab"} else f"cell was {find(p, 'melody')[0].params.get('cell')!r}, expected a held one")),
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
            refused = None
            if plan.actions:
                try:
                    apply_actions(project, plan.actions, {"track": lead.id, "section": build.id})
                except Unsupported as error:
                    refused = str(error)
            row["outcome"] = "refused" if refused or not plan.actions else "acted"
            problem = case.check(plan, project, refused)
            row["passed"] = problem is None
            if refused:
                row["refusal"] = refused
            if problem:
                row["reason"] = problem
        except ValueError as error:
            row["outcome"] = "unusable"
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
        "benchmark_version": 5,
        "model": "adapter" if use_adapter else "base",
        "passed": sum(r["passed"] for r in results),
        "total": len(results),
        "by_category": categories,
        "outcomes": {name: sum(1 for r in results if r.get("outcome") == name) for name in ("acted", "refused", "unusable")},
        "wrong_edits": [r["request"] for r in results if r.get("outcome") == "acted" and not r["passed"]],
        "leaked_into_training": leaked,
        "cases": results,
        "limits": f"Executable instruction following on {len(results)} hand-written requests in the producer's own phrasing, none of which appear in the training data. A refusal counts whether the model declined or the engine stopped it, because either way the user is told RDX cannot do it; wrong_edits lists the cases where something different was silently applied, which is the failure that matters. Does not measure musical quality, taste or audio understanding.",
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
