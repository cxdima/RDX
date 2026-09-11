"""Whole records, by genre.

Everything else in `rdx/musical/` answers a request about one part. This
answers "make me a trance record", which is a different kind of question: it
needs a tempo, a key, a structure, a kit, a bassline that does the right thing
against that kit, sounds on every track, ducking, and the arrangement moves
that give a track its shape — all agreeing with each other.

The reason it lives here rather than in a prompt is the same reason everything
else does. A model asked to invent a trance record will produce something
plausible at 128 with a bass on the downbeat, and there is no way to tell it it
is wrong. Written down, every choice is arguable: if the psytrance bass should
be sixteenths rather than three-after-the-kick, that is one line to change and
a test that will tell you what moved.

A genre expands into ordinary actions. Nothing here can do anything the user
could not do by hand, and every step shows up in the history.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain import Action, Project


@dataclass(frozen=True)
class Genre:
    """One kind of record, as every decision that makes it that kind."""

    meaning: str
    tempo: int
    scale: str
    progression: str
    structure: str
    # Drums: the pattern, then the voices that pattern is played on.
    kit: str
    machine: str
    layers: dict[str, str] = field(default_factory=dict)
    # The bassline rhythm. This is the single most genre-defining choice here.
    bass: str = "offbeat"
    # Sounds, by role.
    patches: dict[str, str] = field(default_factory=dict)
    # How hard everything ducks under the kick.
    duck: str = "pump"
    # Which parts play at all. A psytrance record with big pad chords under it
    # is not a psytrance record.
    chords: bool = True
    lead: bool = True


GENRES: dict[str, Genre] = {
    "trance": Genre(
        "uplifting trance: offbeat bass between every kick, supersaw chords, a long breakdown and a build that takes its time",
        tempo=138,
        scale="minor",
        progression="trance",
        structure="club",
        kit="mainstage",
        machine="909",
        layers={"kick": "four_floor", "clap": "double", "hat": "sixteenth", "open": "offbeat"},
        bass="offbeat",
        patches={"bass": "sub_bass", "chords": "supersaw_lead", "lead": "supersaw_lead", "pad": "warm_pad"},
        duck="pump",
    ),
    "psytrance": Genre(
        "psytrance: three sixteenths of bass after every kick and never on it, an acid line on top, and almost nothing else",
        tempo=145,
        scale="phrygian",
        progression="driving",
        structure="anthem",
        kit="minimal",
        machine="hard",
        layers={"kick": "four_floor", "hat": "offbeat", "open": "offbeat", "clap": "none", "snare": "none"},
        bass="rolling",
        patches={"bass": "sub_bass", "lead": "acid", "pad": "glass_pad"},
        duck="tight",
        chords=False,
    ),
    "techno": Genre(
        "techno: driving eighths, a hard kit and no melody to speak of",
        tempo=132,
        scale="minor",
        progression="driving",
        structure="short",
        kit="rolling",
        machine="hard",
        layers={"kick": "four_floor", "hat": "sixteenth", "open": "offbeat", "clap": "backbeat"},
        bass="driving",
        patches={"bass": "gritty_bass", "lead": "donk", "pad": "glass_pad"},
        duck="tight",
        chords=False,
    ),
    "house": Genre(
        "house: offbeat bass, offbeat open hats, and chords doing the work",
        tempo=124,
        scale="minor",
        progression="pop",
        structure="radio",
        kit="four_floor",
        machine="909",
        layers={"kick": "four_floor", "clap": "backbeat", "hat": "eighth", "open": "offbeat"},
        bass="offbeat",
        patches={"bass": "sub_bass", "chords": "organ", "lead": "pluck_stab", "pad": "warm_pad"},
        duck="gentle",
    ),
    "hardstyle": Genre(
        "hardstyle: halftime bass under a four-floor kick, everything driven",
        tempo=150,
        scale="minor",
        progression="epic",
        structure="short",
        kit="mainstage",
        machine="hard",
        layers={"kick": "four_floor", "clap": "backbeat", "hat": "eighth"},
        bass="halftime",
        patches={"bass": "gritty_bass", "chords": "supersaw_lead", "lead": "hoover", "pad": "warm_pad"},
        duck="extreme",
    ),
}

# Sections whose names mean something to the arrangement. A section called
# "Drop" should sound like one whatever structure it arrived in.
ENERGETIC = ("drop", "main")
QUIET = ("breakdown", "intro", "outro")


def roles_for(genre: Genre) -> set[str]:
    roles = {"drums", "bass"}
    if genre.chords:
        roles.add("chords")
    if genre.lead:
        roles.add("lead")
    return roles


def describe(name: str) -> str:
    genre = GENRES[name]
    return f"{name} at {genre.tempo} BPM in {genre.scale}: {genre.meaning}"


def record(project: Project, name: str, *, bars: int | None = None, key: str | None = None) -> list[Action]:
    """A whole record, as ordinary actions.

    Written against the sections the structure creates, so each part is
    generated with the density its section's energy calls for: a breakdown gets
    the harmony and nothing underneath it, a drop gets everything.
    """
    if name not in GENRES:
        raise ValueError(f"There is no '{name}' genre. RDX knows: {', '.join(GENRES)}.")
    genre = GENRES[name]
    roles = roles_for(genre)
    present = {t.role for t in project.tracks}
    actions: list[Action] = [Action(kind="project", params={"tempo": float(genre.tempo), "scale": genre.scale, **({"key": key} if key else {})})]

    # Anything the genre needs and the project does not have.
    for role in sorted(roles - present):
        actions.append(Action(kind="add_track", params={"role": role, "name": role.title()}))

    # The sounds, before anything is written, so a part is auditioned on the
    # instrument it belongs on rather than on whatever was there.
    actions.append(Action(kind="kit_sound", track="drums", params={"machine": genre.machine}))
    for role, patch in genre.patches.items():
        if role in roles or role in present:
            actions.append(Action(kind="sound", track=role, params={"patch": patch}))

    actions.append(Action(kind="move", params={"name": "structure", "structure": genre.structure, **({"bars": bars} if bars else {})}))
    return actions


def parts_for(project: Project, name: str, section_names: list[str]) -> list[Action]:
    """Fill each section of a record, judged by what that section is for."""
    genre = GENRES[name]
    roles = roles_for(genre)
    actions: list[Action] = []
    for section in project.sections:
        if section.name not in section_names:
            continue
        low = section.name.split()[0].lower() in QUIET
        energy = section.energy
        actions.append(Action(kind="kit", track="drums", section=section.id, params={
            "kit": genre.kit,
            "layers": dict(genre.layers) if not low else {**genre.layers, "hat": "eighth", "open": "none"},
            "density": round(min(1.0, 0.35 + energy * 0.65), 3),
            "crash": energy >= 0.9,
            # The pickup kick before the bar line collides with a bass that
            # already fills that gap, which is exactly what rolling bass does.
            "pickup": genre.bass not in {"rolling", "sixteenth"},
        }))
        if "chords" in roles:
            actions.append(Action(kind="harmony", track="chords", section=section.id, params={"progression": genre.progression, "span": 4}))
        if "bass" in roles and not low:
            actions.append(Action(kind="bassline", track="bass", section=section.id, params={"pattern": genre.bass, "progression": genre.progression}))
        if "lead" in roles and energy >= 0.55:
            actions.append(Action(kind="compose", track="lead", section=section.id, params={"density": round(min(1.0, energy), 3), "variation": 1}))
    return actions


def shape_for(project: Project, name: str, section_names: list[str]) -> list[Action]:
    """The arrangement moves, once the parts they shape exist.

    A section called Build gets a buildup, a Drop gets a drop, a Breakdown gets
    stripped back. The ducking goes on last so it covers every track the record
    created rather than only the ones that were there to begin with.
    """
    genre = GENRES[name]
    actions: list[Action] = []
    for section in project.sections:
        if section.name not in section_names:
            continue
        word = section.name.split()[0].lower()
        if word == "build":
            actions.append(Action(kind="move", section=section.id, params={"name": "buildup", "intensity": 0.9, "cut_bars": 1}))
        elif word == "drop":
            actions.append(Action(kind="move", section=section.id, params={
                "name": "drop",
                "kit": genre.kit,
                "layers": dict(genre.layers),
                "pickup": genre.bass not in {"rolling", "sixteenth"},
            }))
        elif word == "breakdown":
            actions.append(Action(kind="move", section=section.id, params={"name": "breakdown"}))
    actions.append(Action(kind="move", params={"name": "pump", "shape": genre.duck}))
    return actions
