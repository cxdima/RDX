"""What a producer might say, and the operation it should become.

Phrasings are deliberately varied in form — direct instructions, complaints
about how something sounds, and requests with no target named at all — because
that is how the user actually talks. The split in build.py keeps whole phrasing
forms out of training so the benchmark measures new wording, not recall.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

from ..musical.character import CHARACTERS

Actions = list[dict]
Build = Callable[["Scene", random.Random], tuple[Actions, str]]


@dataclass(frozen=True)
class Scene:
    """One musical situation a request arrives in."""

    tempo: int
    key: str
    scale: str
    selected_role: str
    selected_section: str
    selected_bars: int
    track_names: dict[str, str]

    def name(self, role: str) -> str:
        return self.track_names.get(role, role)


@dataclass(frozen=True)
class Intent:
    name: str
    phrasings: tuple[str, ...]
    build: Build
    scenes: int = 3
    # A mix problem the scene should already have been measured as having.
    # Without this, `mix_fix` would appear in no example at all and the adapter
    # would learn never to reach for it, whatever the prompt says.
    measured: str | None = None


# Band shares that produce exactly one named problem in rdx/musical/mixdown.py,
# so a training scene can carry a measurement without rendering any audio.
MEASURED_BANDS: dict[str, dict[str, float]] = {
    "muddy": {"sub": 0.05, "low": 0.12, "mud": 0.35, "mid": 0.28, "high": 0.15, "air": 0.05},
    "harsh": {"sub": 0.06, "low": 0.16, "mud": 0.15, "mid": 0.25, "high": 0.34, "air": 0.04},
    "thin": {"sub": 0.02, "low": 0.08, "mud": 0.18, "mid": 0.42, "high": 0.24, "air": 0.06},
    "boomy": {"sub": 0.18, "low": 0.30, "mud": 0.20, "mid": 0.18, "high": 0.10, "air": 0.04},
}


def act(kind: str, params: dict | None = None, track: str | None = None, section: str | None = None) -> dict:
    action: dict = {"kind": kind, "params": params or {}}
    if track is not None:
        action["track"] = track
    if section is not None:
        action["section"] = section
    return action


# --- sound character -------------------------------------------------------

# Direct ways of asking, and complaints that mean the opposite of a word.
DIRECT = (
    "make the {track} {word}",
    "{word} up the {track}",
    "give the {track} a {word}er sound",
    "can you make the {track} sound {word}",
    "the {track} needs to be {word}er",
    "a bit more {word} on the {track}",
    "{word} the {track} a little",
    "make it {word}",
    "{word}er please",
    "I want the {track} {word}er than that",
    "push the {track} {word}er",
    "that {track} should feel {word}",
)
COMPLAINT = (
    "the {track} is too {opposite}",
    "the {track} sounds too {opposite}",
    "there is too much {opposite} in the {track}",
    "this {track} is way too {opposite}",
    "too {opposite}, fix the {track}",
    "I don't like how {opposite} the {track} is",
)

# Hand-written phrasings for the words the user reaches for most.
EXTRA: dict[str, tuple[str, ...]] = {
    "warm": ("the lead is harsh, warm it up", "take the edge off the {track}", "round off the top of the {track}", "the {track} is piercing my ears"),
    "bright": ("open the {track} up", "let the {track} cut through", "the {track} is buried, bring it forward tonally"),
    "huge": ("make the {track} enormous", "I want the {track} to feel massive", "make this sound like a stadium"),
    "goosebumps": ("add a pan and a flanger to the {track} so it gives goosebumps", "I want the {track} to cause goosebumps", "make the {track} give me chills", "do the thing that makes the hair stand up on the {track}"),
    "wide": ("spread the {track} out", "the {track} feels stuck in the middle", "open up the stereo on the {track}"),
    "dreamy": ("make the {track} float", "I want the {track} to feel like a dream", "give the {track} that faraway feeling"),
    "punchy": ("the {track} needs more punch", "make the {track} hit harder", "give the {track} some attack"),
    "moving": ("give the {track} some movement", "the {track} is static, make it move"),
    "tight": ("tighten the {track} up", "the {track} is washing out, pull it in"),
    "plucky": ("make the {track} pluck instead of hold", "shorten the notes on the {track}", "the {track} should stab rather than sustain"),
    "sustained": ("let the {track} hold out", "the notes on the {track} die too quickly", "make the {track} hold through the whole note"),
    "snappy": ("give the {track} a snap on each note", "the {track} has no front edge to it"),
    "stacked": ("thicken the {track} up with more voices", "the {track} sounds like one thin synth"),
    "deep": ("put something under the {track}", "the {track} needs an octave below it"),
    "crushed": ("dirty the {track} up", "I want the {track} to sound broken and lo-fi"),
}


def character_intent(word: str) -> Intent:
    entry = CHARACTERS[word]
    phrasings = [p.replace("{word}", word) for p in DIRECT]
    if entry.opposite:
        phrasings += [p.replace("{opposite}", entry.opposite) for p in COMPLAINT]
    phrasings += list(EXTRA.get(word, ()))

    def build(scene: Scene, rng: random.Random) -> tuple[Actions, str]:
        target = None if rng.random() < 0.3 else scene.name(scene.selected_role)
        params: dict = {"character": word}
        if rng.random() < 0.4:
            params["intensity"] = rng.choice([0.3, 0.45, 0.8, 1.0])
        return [act("character", params, track=target)], ""

    return Intent(f"character_{word}", tuple(dict.fromkeys(phrasings)), build)


# --- drums -----------------------------------------------------------------


def kit_layers(layers: dict[str, str]) -> Build:
    def build(scene: Scene, rng: random.Random) -> tuple[Actions, str]:
        params: dict = {"layers": dict(layers)}
        if rng.random() < 0.3:
            params["density"] = rng.choice([0.4, 0.6, 0.85])
        return [act("kit", params, track="drums", section=rng.choice(["selected", scene.selected_section]))], ""

    return build


def named_kit(kit: str) -> Build:
    def build(scene: Scene, rng: random.Random) -> tuple[Actions, str]:
        return [act("kit", {"kit": kit}, track="drums", section="selected")], ""

    return build


# --- production moves ------------------------------------------------------


def buildup_build(cut: bool) -> Build:
    def build(scene: Scene, rng: random.Random) -> tuple[Actions, str]:
        params: dict = {"name": "buildup"}
        if rng.random() < 0.5:
            params["intensity"] = rng.choice([0.6, 0.8, 1.0])
        if cut:
            params["cut_bars"] = rng.choice([0.5, 1, 2])
        return [act("move", params, section="selected")], ""

    return build


def move_build(name: str, extra: dict | None = None) -> Build:
    def build(scene: Scene, rng: random.Random) -> tuple[Actions, str]:
        return [act("move", {"name": name, **(extra or {})}, section="selected")], ""

    return build


def layer_build(preset: str, octave: int = 0) -> Build:
    def build(scene: Scene, rng: random.Random) -> tuple[Actions, str]:
        params: dict = {"name": "layer", "track": scene.name("lead"), "preset": preset}
        if octave:
            params["octave"] = octave
        return [act("move", params)], ""

    return build


# --- refusals and questions ------------------------------------------------


def refuse(note: str) -> Build:
    def build(scene: Scene, rng: random.Random) -> tuple[Actions, str]:
        return [], note

    return build


CHARACTER_WORDS = ("warm", "bright", "dark", "soft", "hard", "punchy", "fat", "thin", "wide", "narrow", "dry", "wet", "dreamy", "lush", "gritty", "clean", "sharp", "smooth", "huge", "tight", "airy", "clear", "moving", "swirling", "metallic", "goosebumps", "plucky", "sustained", "snappy", "stacked", "deep", "crushed")


def intents() -> list[Intent]:
    items: list[Intent] = [character_intent(word) for word in CHARACTER_WORDS]

    items += [
        Intent("kit_double_clap", (
            "give me a kick pattern with a double clap",
            "kick and a double clap",
            "I want a double clap over the kick",
            "put a doubled clap on the backbeat with a four to the floor kick",
            "four on the floor with a double clap",
            "add the double clap thing over the kick",
        ), kit_layers({"kick": "four_floor", "clap": "double"})),
        Intent("kit_clap_backbeat", (
            "put a clap on two and four",
            "add a clap on the backbeat",
            "I want claps on the offbeats of the bar",
            "give me a simple clap",
            "clap on the backbeat please",
        ), kit_layers({"clap": "backbeat"})),
        Intent("kit_sixteenth_hats", (
            "put the hats on sixteenths",
            "I want sixteenth note hi-hats",
            "make the hats twice as fast",
            "busier hats please",
            "run the hats at sixteenths",
        ), kit_layers({"hat": "sixteenth"})),
        Intent("kit_offbeat_open", (
            "offbeat open hats",
            "give me open hats on the offbeat",
            "put the open hat between the kicks",
            "I want that offbeat open hat sound",
        ), kit_layers({"open": "offbeat"})),
        Intent("kit_no_hats", (
            "take the hats out",
            "lose the hi-hats",
            "no hats in this one",
            "drop the hats",
        ), kit_layers({"hat": "none"})),
        Intent("kit_ride", (
            "put a ride on it",
            "swap to a ride cymbal",
            "add a ride running through this",
        ), kit_layers({"ride": "eighth"})),
        Intent("kit_mainstage", (
            "give me a mainstage kit",
            "big festival drums",
            "full mainstage drum pattern",
            "make the drums sound like a main stage",
        ), named_kit("mainstage")),
        Intent("kit_four_floor", (
            "four on the floor",
            "straight four to the floor kick",
            "standard club beat",
            "give me a four on the floor pattern",
        ), named_kit("four_floor")),
        Intent("kit_halftime", (
            "make the drums half time",
            "half time feel on the drums",
            "halve the drum tempo feel",
        ), named_kit("halftime")),
        Intent("kit_breakbeat", (
            "give me a breakbeat",
            "broken beat for the drums",
            "make the drums broken instead of straight",
        ), named_kit("breakbeat")),
        Intent("buildup", (
            "build this section up",
            "I need a buildup here",
            "make this rise into the drop",
            "give me a build",
            "this section should build tension",
            "take this up towards the drop",
            "I want a build up in this part",
        ), buildup_build(False)),
        Intent("buildup_cut", (
            "build it up and then cut everything at the end",
            "build up and let everything suddenly fade",
            "rise and then everything drops away",
            "build this and kill it right before the drop",
            "I want it to rise and then everything suddenly fades",
        ), buildup_build(True)),
        Intent("drop", (
            "this is the drop",
            "drop here",
            "everything back in now",
            "full power in this section",
            "hit the drop",
        ), move_build("drop")),
        Intent("breakdown", (
            "strip it back here",
            "breakdown in this section",
            "take the drums and bass out and leave the pads",
            "I want a breakdown",
            "pull everything back to just atmosphere",
        ), move_build("breakdown")),
        Intent("fade_all", (
            "fade everything out",
            "bring it all down together",
            "everything fades here",
            "fade the whole thing out over this section",
        ), move_build("fade", {"beats": 8})),
        Intent("layer_supersaw", (
            "layer a big synth with the melody",
            "put a strong synth in with the lead",
            "double the lead with a supersaw",
            "I want a big synth going in together with the melody",
            "add a wide synth on top of the melody",
        ), layer_build("supersaw")),
        Intent("layer_octave", (
            "double the lead an octave up",
            "add the melody an octave higher on another sound",
            "layer the lead up an octave",
        ), layer_build("bell", 1)),
        Intent("transition", (
            "I need a transition between these two parts",
            "the change between sections is too abrupt",
            "smooth the join into the next section",
            "put a transition at the end of this part",
            "it jumps straight in, give me something at the seam",
        ), move_build("transition")),
        Intent("stutter", (
            "stutter the end of this into the drop",
            "retrigger the last bit of this section",
            "I want a stutter right before the drop",
            "chop the ending up so it repeats faster",
        ), move_build("stutter")),
        Intent("riser_alone", (
            "put a riser over this",
            "I want a riser sweeping up here",
            "add a rising sweep to this section",
            "give me a riser into the next part",
        ), move_build("riser")),
        Intent("double_time", (
            "make the drums double time",
            "play this twice as fast without changing the tempo",
            "double time feel here",
            "the drums should be double speed",
        ), move_build("double_time", {"roles": ["drums"]})),
        Intent("half_time_feel", (
            "half time feel in this section",
            "make it feel half speed",
            "slow the feel down but keep the tempo",
        ), move_build("double_time", {"factor": 0.5})),
        Intent("harmony_from_hum", (
            "turn that hum into chords",
            "make my humming into a chord progression",
            "build a chord progression from what I just sang",
            "take that melody I hummed and give me the chords",
            "the chord progression should follow my humming",
            "use my hum as the chord progression",
        ), lambda scene, rng: ([act("harmony", {"span": rng.choice([2, 4, 8])}, track="selected", section="selected")], "")),
        Intent("add_strings", (
            "add a string instrument",
            "I want strings in this",
            "put a strings track in",
            "give me a string section",
            "add strings please",
        ), lambda scene, rng: ([act("add_track", {"role": "chords", "name": "Strings", "preset": "strings"})], "")),
        Intent("preset_change", (
            "switch the {track} to a supersaw",
            "use a supersaw on the {track}",
            "make the {track} a supersaw sound",
            "change the {track} instrument to supersaw",
        ), lambda scene, rng: ([act("sound", {"preset": "supersaw"}, track=scene.name(scene.selected_role))], "")),
        Intent("preset_sub", (
            "make the bass a sub",
            "I want a sub bass",
            "switch the bass to a pure sub",
        ), lambda scene, rng: ([act("sound", {"preset": "sub"}, track="bass")], "")),
        Intent("compose_part", (
            "write a {role} part here",
            "give me a {role} line in this section",
            "I need a {role} in this part",
            "compose a {role} for this section",
        ), lambda scene, rng: ([act("compose", {"density": rng.choice([0.4, 0.6, 0.85]), "variation": rng.randint(0, 5)}, track=scene.selected_role, section="selected")], "")),
        Intent("transpose_up", (
            "move the {track} up an octave",
            "take the {track} an octave higher",
            "the {track} is too low, raise it twelve semitones",
        ), lambda scene, rng: ([act("transpose", {"semitones": 12}, track=scene.name(scene.selected_role), section="selected")], "")),
        Intent("transpose_last", (
            "keep the rhythm but raise the last note two semitones",
            "let the ending of the melody go up a tone",
            "same timing, but lift the final note",
            "the last note should rise, leave the rest",
        ), lambda scene, rng: ([act("transpose", {"semitones": 2, "last_note": True}, track=scene.name(scene.selected_role), section="selected")], "")),
        Intent("quantize", (
            "quantize the {track} to sixteenths",
            "tighten the {track} timing to the grid",
            "snap the {track} to sixteenth notes",
        ), lambda scene, rng: ([act("rhythm", {"grid": 0.25}, track=scene.name(scene.selected_role), section="selected")], "")),
        Intent("swing", (
            "give the drums some swing",
            "add a bit of shuffle to the drums",
            "swing the drums slightly",
        ), lambda scene, rng: ([act("rhythm", {"grid": 0.5, "swing": 0.18}, track="drums", section="selected")], "")),
        Intent("quieter", (
            "turn the {track} down",
            "the {track} is too loud",
            "bring the {track} down a few dB",
            "the {track} is overpowering everything",
        ), lambda scene, rng: ([act("mix", {"delta_db": -rng.choice([2, 3, 4])}, track=scene.name(scene.selected_role))], "")),
        Intent("louder", (
            "bring the {track} up",
            "I can barely hear the {track}",
            "push the {track} louder",
        ), lambda scene, rng: ([act("mix", {"delta_db": rng.choice([2, 3])}, track=scene.name(scene.selected_role))], "")),
        Intent("duplicate_section", (
            "repeat this section once",
            "I want another copy of this part right after it",
            "double the length of this section by repeating it",
            "copy this section",
        ), lambda scene, rng: ([act("arrange", {"operation": "duplicate"}, section="selected")], "")),
        Intent("add_section", (
            "add an eight bar breakdown section",
            "put a new sixteen bar section in",
            "I need another section for the outro",
        ), lambda scene, rng: ([act("arrange", {"operation": "add", "name": rng.choice(["Breakdown", "Section", "Outro 2"]), "bars": rng.choice([8, 16]), "energy": 0.35})], "")),
        Intent("tempo", (
            "set the tempo to {tempo}",
            "take it to {tempo} BPM",
            "this should run at {tempo} beats per minute",
            "slow it down to {tempo}",
        ), lambda scene, rng: ([act("project", {"tempo": scene.tempo})], "")),
        Intent("protect", (
            "keep the drums exactly as they are",
            "lock the drums, I like them",
            "protect the drums from changes",
            "don't touch the drums from now on",
        ), lambda scene, rng: ([act("protect", {"locked": True}, track="drums")], "")),
        Intent("filter_sweep", (
            "open the filter across this section on the {track}",
            "sweep the {track} filter up through this part",
            "I want the {track} to open up over the section",
        ), lambda scene, rng: ([act("automation", {"parameter": "cutoff", "points": [[0, 600], [scene.selected_bars * 4, 14000]]}, track=scene.name(scene.selected_role), section="selected")], "")),
        Intent("master_ceiling", (
            "set the limiter ceiling to minus two",
            "put the output ceiling at -2 dB",
            "cap the master at minus two dB",
        ), lambda scene, rng: ([act("master", {"ceiling": -2})], "")),
        # Two things asked for at once — the model must do both, not one.
        Intent("compound_dark_quiet", (
            "make the bass darker and quieter",
            "the bass should be duller and turned down",
            "darken the bass and pull it back",
        ), lambda scene, rng: ([act("character", {"character": "dark"}, track="bass"), act("mix", {"delta_db": -3}, track="bass")], "")),
        Intent("compound_bright_wide", (
            "brighten the {track} and spread it out",
            "the {track} should be brighter and wider",
            "open the {track} up and make it wide",
        ), lambda scene, rng: ([act("character", {"character": "bright"}, track=scene.name(scene.selected_role)), act("character", {"character": "wide"}, track=scene.name(scene.selected_role))], "")),
        Intent("compound_strings_harmony", (
            "add strings and build the chords from my hum",
            "put in a string track and turn my humming into its chord progression",
            "I want strings playing the progression I sang",
        ), lambda scene, rng: ([act("add_track", {"role": "chords", "name": "Strings", "preset": "strings"}), act("harmony", {"from_track": scene.name(scene.selected_role)}, track="Strings", section="selected")], "")),
    ]

    # Correcting a measured mix. The context carries the reading, so these
    # teach the model to act on a measurement rather than on a hunch — and the
    # refusal below teaches the other half: no measurement, no correction.
    items += [
        Intent("mix_fix_muddy", (
            "the mix is muddy",
            "it sounds cloudy and thick",
            "there's too much build-up in the low mids",
            "clean up the mud in this mix",
            "the whole thing sounds congested",
        ), lambda scene, rng: ([act("mix_fix", {"problem": "muddy"})], ""), measured="muddy"),
        Intent("mix_fix_harsh", (
            "the mix is harsh",
            "the top end is hurting my ears",
            "it's too bright and fatiguing",
            "take the harshness out of the mix",
        ), lambda scene, rng: ([act("mix_fix", {"problem": "harsh"})], ""), measured="harsh"),
        Intent("mix_fix_thin", (
            "the mix has no weight",
            "it sounds thin overall",
            "there's nothing underneath the mix",
        ), lambda scene, rng: ([act("mix_fix", {"problem": "thin"})], ""), measured="thin"),
        Intent("mix_fix_all", (
            "fix whatever is wrong with the mix",
            "sort the mix out",
            "correct everything you measured",
        ), lambda scene, rng: ([act("mix_fix", {})], ""), measured="boomy"),
        Intent("mix_needs_measuring", (
            "is the mix muddy",
            "what's wrong with my mix",
            "tell me what needs fixing in the mix",
            "how does the mix look",
        ), refuse("I have not measured this mix yet. Analyse it in the mixer and I will tell you what is actually in it.")),
    ]

    # Drum sound design: what the kit sounds like, not what it plays.
    items += [
        Intent("drums_909", (
            "make the drums a 909",
            "I want 909 drums",
            "give me that classic house drum sound",
            "punchy short drum sounds please",
        ), lambda scene, rng: ([act("kit_sound", {"machine": "909"}, track="drums")], "")),
        Intent("drums_808", (
            "make the kick an 808",
            "I want 808 drums",
            "give me a long booming kick",
            "that deep 808 sound on the drums",
        ), lambda scene, rng: ([act("kit_sound", {"machine": "808"}, track="drums")], "")),
        Intent("drums_hard", (
            "make the drums harder",
            "the drums need to hit harder and shorter",
            "tighter, clickier drums",
        ), lambda scene, rng: ([act("kit_sound", {"machine": "hard"}, track="drums")], "")),
        Intent("kick_longer", (
            "the kick is too short",
            "let the kick ring out longer",
            "give the kick a longer tail",
        ), lambda scene, rng: ([act("kit_sound", {"kick_decay": rng.choice([0.55, 0.7, 0.9])}, track="drums")], "")),
        Intent("kick_tune", (
            "tune the kick down",
            "the kick is pitched too high",
            "drop the pitch of the kick",
        ), lambda scene, rng: ([act("kit_sound", {"kick_tune": rng.choice([-2, -4, -5])}, track="drums")], "")),
        Intent("hats_darker", (
            "the hats are too bright",
            "darken the hi-hats",
            "the hats are piercing, tone them down",
        ), lambda scene, rng: ([act("kit_sound", {"hat_tone": rng.choice([5500, 6500, 7000])}, track="drums")], "")),
        Intent("clap_wider", (
            "make the clap wider",
            "the clap sounds like one person, I want a crowd",
            "spread the clap out more",
        ), lambda scene, rng: ([act("kit_sound", {"clap_spread": rng.choice([1.8, 2.2, 2.6])}, track="drums")], "")),
    ]

    # Sound design: a named patch is a different request from an adjective.
    items += [
        Intent("patch_reese", (
            "give me a reese bass",
            "I want a reese on the bass",
            "make the bass a reese",
            "that detuned drum and bass sound on the low end",
        ), lambda scene, rng: ([act("sound", {"patch": "reese"}, track="bass")], "")),
        Intent("patch_acid", (
            "make the bass acid",
            "I want a 303 line",
            "give me an acid bassline sound",
            "that squelchy resonant bass",
        ), lambda scene, rng: ([act("sound", {"patch": "acid"}, track="bass")], "")),
        Intent("patch_supersaw", (
            "give the lead a big supersaw",
            "I want the classic trance lead sound",
            "make the melody a wide supersaw",
        ), lambda scene, rng: ([act("sound", {"patch": "supersaw_lead"}, track="lead")], "")),
        Intent("patch_pluck", (
            "make the {track} a pluck stab",
            "I want short stabs on the {track}",
            "give the {track} that offbeat stab sound",
        ), lambda scene, rng: ([act("sound", {"patch": "pluck_stab"}, track=scene.name("lead"))], "")),
        Intent("patch_pad", (
            "give the chords a warm pad",
            "I want a soft pad underneath",
            "make the chords a proper pad sound",
        ), lambda scene, rng: ([act("sound", {"patch": rng.choice(["warm_pad", "glass_pad"])}, track="chords")], "")),
        Intent("patch_sub", (
            "make the bass a clean sub",
            "I just want a sub under this",
            "pure sub bass please",
        ), lambda scene, rng: ([act("sound", {"patch": "sub_bass"}, track="bass")], "")),
        Intent("patch_wobble", (
            "give me a wobble bass",
            "I want the bass wobbling",
            "put an lfo on the bass filter",
        ), lambda scene, rng: ([act("sound", {"patch": "wobble"}, track="bass")], "")),
        Intent("synth_shorter_decay", (
            "shorten the decay on the {track}",
            "the {track} rings on too long",
            "make the notes on the {track} die away faster",
        ), lambda scene, rng: ([act("sound", {"decay": rng.choice([0.08, 0.12, 0.18])}, track=scene.name(scene.selected_role))], "")),
        Intent("synth_filter_envelope", (
            "give the {track} a filter envelope",
            "I want the filter to snap on each note of the {track}",
            "the {track} needs an envelope on the filter",
        ), lambda scene, rng: ([act("character", {"character": "snappy"}, track=scene.name(scene.selected_role))], "")),
        Intent("synth_detune", (
            "detune the {track} more",
            "stack more voices on the {track}",
            "the {track} needs to be thicker and more detuned",
        ), lambda scene, rng: ([act("character", {"character": "stacked"}, track=scene.name(scene.selected_role))], "")),
        Intent("synth_sub_oscillator", (
            "add a sub oscillator to the bass",
            "the bass needs something an octave below",
            "put a sub under the bass",
        ), lambda scene, rng: ([act("character", {"character": "deep"}, track="bass")], "")),
        Intent("synth_square", (
            "make the {track} a square wave",
            "switch the {track} to square",
            "I want a hollow square on the {track}",
        ), lambda scene, rng: ([act("sound", {"wave": "square"}, track=scene.name(scene.selected_role))], "")),
        Intent("synth_crush", (
            "bit crush the {track}",
            "make the {track} sound crushed and dirty",
            "add some bit reduction to the {track}",
        ), lambda scene, rng: ([act("character", {"character": "crushed"}, track=scene.name(scene.selected_role))], "")),
        Intent("synth_vibrato", (
            "put some vibrato on the {track}",
            "I want the {track} to sing a bit",
            "add pitch movement to the held notes on the {track}",
        ), lambda scene, rng: ([act("character", {"character": "singing"}, track=scene.name(scene.selected_role))], "")),
    ]

    items += [
        Intent("relate_bass_follows_chords", (
            "the bass should follow the chords",
            "make the bass play the chord roots",
            "the bass and the chords don't line up",
            "put the bass under the chord progression",
            "the bassline should follow the harmony",
        ), lambda scene, rng: ([act("relate", {"operation": "follow", "from_track": "chords"}, track="bass", section="selected")], "")),
        Intent("relate_counter_kick", (
            "give the {track} a counter-rhythm to the kick",
            "the {track} should play in between the kicks",
            "put the {track} in the gaps the kick leaves",
            "I want the {track} answering the kick",
        ), lambda scene, rng: ([act("relate", {"operation": "counter", "from_track": "drums", "against": "kick"}, track=scene.name(scene.selected_role), section="selected")], "")),
        Intent("relate_harmonise", (
            "add a harmony line to the melody",
            "harmonise the lead a third above",
            "put a second line over the {track}",
            "I want two notes moving together on the melody",
        ), lambda scene, rng: ([act("add_track", {"role": "lead", "name": "Harmony", "preset": "pluck"}), act("relate", {"operation": "harmonise", "from_track": scene.name("lead"), "degrees": 2}, track="Harmony", section="selected")], "")),
        Intent("harmony_sevenths", (
            "put sevenths on those chords",
            "add a seventh to each chord",
            "the chords should be seventh chords",
            "make the harmony richer with sevenths",
        ), lambda scene, rng: ([act("harmony", {"colour": "seventh"}, track="chords", section="selected")], "")),
        Intent("harmony_suspended", (
            "make the chords suspended",
            "I want sus chords in there",
            "suspend the chords, take the third out",
        ), lambda scene, rng: ([act("harmony", {"colour": rng.choice(["sus4", "sus2"])}, track="chords", section="selected")], "")),
    ]

    items += [
        Intent("phrase_space", (
            "more space between the notes on the {track}",
            "the {track} is too busy",
            "there's too much going on in the {track}",
            "thin the {track} out a bit",
            "give the {track} some room to breathe",
            "fewer notes in the {track} please",
        ), lambda scene, rng: ([act("phrase", {"operation": "space", "amount": rng.choice([0.3, 0.4, 0.5])}, track=scene.name(scene.selected_role), section="selected")], "")),
        Intent("phrase_fill", (
            "the {track} needs more movement",
            "add some notes in between on the {track}",
            "the {track} feels empty, fill it in",
            "busier {track} please",
        ), lambda scene, rng: ([act("phrase", {"operation": "fill", "amount": rng.choice([0.4, 0.6, 0.8])}, track=scene.name(scene.selected_role), section="selected")], "")),
        Intent("phrase_rise", (
            "the melody should rise at the end",
            "let the {track} climb towards the end",
            "the end of the phrase should go up",
            "make the {track} lift into the next part",
        ), lambda scene, rng: ([act("phrase", {"operation": "shape", "shape": "rise", "degrees": rng.choice([2, 3])}, track=scene.name(scene.selected_role), section="selected")], "")),
        Intent("phrase_fall", (
            "the melody should come down at the end",
            "let the {track} settle downwards",
            "the phrase should fall away at the end",
        ), lambda scene, rng: ([act("phrase", {"operation": "shape", "shape": "fall", "degrees": 2}, track=scene.name(scene.selected_role), section="selected")], "")),
        Intent("phrase_arch", (
            "the {track} should lift in the middle and come back",
            "give the melody an arch",
            "let the phrase peak halfway through",
        ), lambda scene, rng: ([act("phrase", {"operation": "shape", "shape": "arch", "degrees": 3}, track=scene.name(scene.selected_role), section="selected")], "")),
        Intent("phrase_vary", (
            "the {track} is too repetitive",
            "it keeps repeating, change it up",
            "the {track} is playing the same thing over and over",
            "vary the {track} so it doesn't loop",
        ), lambda scene, rng: ([act("phrase", {"operation": "vary", "amount": rng.choice([0.4, 0.6])}, track=scene.name(scene.selected_role), section="selected")], "")),
    ]

    items += [
        Intent("sidechain_track", (
            "sidechain the {track} to the kick",
            "duck the {track} under the kick",
            "put the {track} under the kick",
            "the {track} should get out of the way of the kick",
            "add sidechain compression to the {track} from the drums",
            "the kick and the {track} are fighting, duck the {track}",
        ), lambda scene, rng: ([act("sidechain", {"source": "drums", "shape": rng.choice(["pump", "tight", "gentle"])}, track=scene.name(scene.selected_role))], "")),
        Intent("sidechain_everything", (
            "I want that pumping sidechain effect",
            "make the whole thing pump",
            "sidechain everything to the kick",
            "give me that pumping trance feel",
            "everything should breathe with the kick",
        ), lambda scene, rng: ([act("move", {"name": "pump"})], "")),
        Intent("sidechain_amount", (
            "more pump on the {track}",
            "duck the {track} harder",
            "the sidechain on the {track} is too subtle",
            "I want the {track} to disappear under every kick",
        ), lambda scene, rng: ([act("sidechain", {"shape": "extreme"}, track=scene.name(scene.selected_role))], "")),
        Intent("sidechain_gentler", (
            "less pumping on the {track}",
            "the sidechain is too strong, back it off",
            "make the ducking on the {track} gentler",
        ), lambda scene, rng: ([act("sidechain", {"shape": "gentle"}, track=scene.name(scene.selected_role))], "")),
        Intent("sidechain_remove", (
            "take the sidechain off the {track}",
            "stop the {track} pumping",
            "remove the ducking from the {track}",
            "I don't want the {track} sidechained any more",
        ), lambda scene, rng: ([act("sidechain", {"operation": "remove"}, track=scene.name(scene.selected_role))], "")),
        Intent("sidechain_long", (
            "a long slow pump on the {track}",
            "let the {track} swell back in slowly after each kick",
            "give the {track} that breathing sidechain",
        ), lambda scene, rng: ([act("sidechain", {"shape": "breathing"}, track=scene.name(scene.selected_role))], "")),
    ]

    # Things RDX genuinely cannot do. It must say so rather than substitute.
    items += [
        Intent("refuse_vocoder", (
            "put a vocoder on this",
            "run the lead through a vocoder",
            "I want vocoded vocals",
        ), refuse("There is no vocoder in RDX. The closest instruments are choir and FM.")),
        Intent("refuse_tapestop", (
            "add a tape stop at the end",
            "do a tape stop into the drop",
            "I want that slowing down tape effect",
        ), refuse("RDX cannot do a tape stop. A fade or a filter sweep into the drop is what I have.")),
        Intent("refuse_sample", (
            "sample this vocal and chop it up",
            "load this sample and slice it",
            "chop up the audio into stutters",
        ), refuse("RDX cannot slice or chop audio yet. It can import a recording as a track and transcribe a hummed line into notes.")),
        Intent("refuse_plugin", (
            "load Serum on the lead",
            "use my Sylenth preset",
            "open a plugin for this sound",
        ), refuse("RDX cannot host plugins. Its own instruments are supersaw, saw, pluck, sine, sub, pad, strings, choir, bell, fm and noise.")),
        Intent("refuse_real_instrument", (
            "record a real violin for this",
            "I want an actual orchestra here",
            "use live drums instead",
        ), refuse("RDX only plays its own synthesized instruments. Strings and choir are the closest, or you can import a recording as an audio track.")),
    ]

    # Requests with no target. Asking is the correct answer, not guessing.
    items += [
        Intent("ask_what_changed", (
            "make it better",
            "something is off",
            "change this",
            "improve it",
            "this isn't working",
            "do something with this",
        ), refuse("Which part should change, and what do you hear that is wrong?")),
        Intent("ask_which_track", (
            "make that one warmer",
            "turn it down",
            "add more of that",
        ), refuse("Which track do you mean?")),
    ]
    return items
