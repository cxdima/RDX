"""Mix judgement: "it sounds muddy" turned into a number, then into a fix.

This is the module that most needed to exist. Every other kind of request RDX
handles is an instruction — *make it warmer*, *add a clap* — and the answer is
a table lookup. A mix complaint is different: *"the mix is muddy"*, *"the kick
and bass are fighting"*, *"the lead doesn't cut through"* are claims about the
finished sound, and a model guessing at them is exactly the failure this
project is built around.

So RDX measures instead. The studio renders every track as a stem, the server
decodes them, and this module reports what is actually in the audio: energy per
band, how much two parts collide, dynamic range, stereo correlation, and
loudness by the ITU-R BS.1770-4 method that streaming services use.

Then it names problems. Every threshold here is a claim about what a good mix
looks like, written where a producer can read it and disagree — the same
property that makes `character.py` arguable. A finding always carries the
measurement that triggered it, so "muddy" arrives as "31% of the energy sits
between 200 and 400 Hz" rather than as an opinion.

The bands are chosen to line up with the controls RDX actually has. There is no
point naming a problem in a region nothing can reach: `mud` is the bottom of
the three-band EQ's low shelf, `mid` and `high` are its other two, so every
finding maps onto a real edit.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import signal

from ..domain import Project

# (name, low Hz, high Hz). "mud" is the region a busy arrangement clogs first.
BANDS: tuple[tuple[str, float, float], ...] = (
    ("sub", 20.0, 60.0),
    ("low", 60.0, 200.0),
    ("mud", 200.0, 400.0),
    ("mid", 400.0, 2500.0),
    ("high", 2500.0, 8000.0),
    ("air", 8000.0, 20000.0),
)

BAND_WORDS = {
    "sub": "the very bottom",
    "low": "the bass region",
    "mud": "the low mids",
    "mid": "the midrange",
    "high": "the presence range",
    "air": "the top end",
}

# What a mix usually looks like when nothing is wrong. These are the arguable
# numbers: change one and RDX's opinion changes with it, visibly.
LIMITS = {
    "mud_share": 0.22,  # above this the low mids are crowding everything
    "low_share": 0.62,  # sub + low + mud together; above this it is boomy
    "bottom_thin": 0.14,  # sub + low together; below this there is no weight
    "high_share": 0.30,  # presence; above this it fatigues
    "air_thin": 0.012,  # below this the mix is closed in
    "collision": 0.34,  # two parts sharing this much of a band fight
    "crest": 7.0,  # dB of peak over RMS; below this it is squashed
    "buried": 20.0,  # dB below the loudest part before it disappears
    "loudness": -8.0,  # LUFS; above this a limiter is doing the arranging
}


def db(value: float) -> float:
    return 20 * math.log10(max(float(value), 1e-9))


@dataclass
class TrackMix:
    """What one track's audio actually contains."""

    track_id: str
    name: str
    role: str
    rms_db: float
    peak_db: float
    crest_db: float
    correlation: float
    bands: dict[str, float]  # share of this track's own energy, sums to 1
    energy: float  # absolute, for comparing tracks with each other

    def as_dict(self) -> dict:
        return {"track_id": self.track_id, "name": self.name, "role": self.role, "rms_db": round(self.rms_db, 1), "peak_db": round(self.peak_db, 1), "crest_db": round(self.crest_db, 1), "correlation": round(self.correlation, 3), "bands": {k: round(v, 4) for k, v in self.bands.items()}, "energy": float(f"{self.energy:.6g}")}

    @classmethod
    def from_dict(cls, data: dict) -> "TrackMix":
        return cls(track_id=data["track_id"], name=data["name"], role=data["role"], rms_db=data["rms_db"], peak_db=data["peak_db"], crest_db=data["crest_db"], correlation=data["correlation"], bands={name: float(data["bands"].get(name, 0.0)) for name, _, _ in BANDS}, energy=data["energy"])


@dataclass
class Collision:
    """Two parts competing for the same region of the spectrum."""

    a: str
    b: str
    band: str
    score: float  # 0 to 1: how much of that band they share

    def as_dict(self) -> dict:
        return {"a": self.a, "b": self.b, "band": self.band, "score": round(self.score, 3)}


@dataclass
class Mix:
    tracks: list[TrackMix]
    bands: dict[str, float]
    crest_db: float
    peak_db: float
    loudness_lufs: float
    collisions: list[Collision] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"tracks": [t.as_dict() for t in self.tracks], "bands": {k: round(v, 4) for k, v in self.bands.items()}, "crest_db": round(self.crest_db, 1), "peak_db": round(self.peak_db, 1), "loudness_lufs": round(self.loudness_lufs, 1), "collisions": [c.as_dict() for c in self.collisions]}

    @classmethod
    def from_dict(cls, data: dict) -> "Mix":
        """Rebuild a stored measurement so its findings can be recomputed.

        Findings are never stored: they are derived from the measurement and
        the project together, so a fix always proposes a change from where the
        settings are now rather than from where they were when it was measured.
        """
        return cls(
            tracks=[TrackMix.from_dict(t) for t in data["tracks"]],
            bands={name: float(data["bands"].get(name, 0.0)) for name, _, _ in BANDS},
            crest_db=data["crest_db"],
            peak_db=data["peak_db"],
            loudness_lufs=data["loudness_lufs"],
            collisions=[Collision(c["a"], c["b"], c["band"], c["score"]) for c in data.get("collisions", [])],
        )


def band_energy(samples: np.ndarray, rate: int) -> tuple[dict[str, float], float]:
    """Energy in each band, and the total, from the power spectrum.

    Welch's method rather than a single transform: an arrangement is not
    stationary, and averaging over windows is what stops one crash cymbal
    deciding the whole reading.
    """
    mono = samples.mean(axis=1) if samples.ndim > 1 else samples
    if not len(mono) or not np.any(mono):
        return {name: 0.0 for name, _, _ in BANDS}, 0.0
    window = min(8192, len(mono))
    frequencies, power = signal.welch(mono, fs=rate, nperseg=window, noverlap=window // 2)
    spacing = frequencies[1] - frequencies[0] if len(frequencies) > 1 else 1.0
    energies = {}
    for name, low, high in BANDS:
        inside = (frequencies >= low) & (frequencies < min(high, rate / 2))
        energies[name] = float(power[inside].sum() * spacing)
    return energies, float(sum(energies.values()))


def shares(energies: dict[str, float], total: float) -> dict[str, float]:
    return {name: (value / total if total > 0 else 0.0) for name, value in energies.items()}


def correlation(samples: np.ndarray) -> float:
    """1.0 is mono, 0 is uncorrelated, below 0 means the sides fight."""
    if samples.ndim < 2 or samples.shape[1] < 2:
        return 1.0
    left, right = samples[:, 0], samples[:, 1]
    denominator = math.sqrt(float(np.sum(left**2)) * float(np.sum(right**2)))
    return float(np.sum(left * right) / denominator) if denominator > 1e-12 else 1.0


def k_weight(samples: np.ndarray, rate: int) -> np.ndarray:
    """The ITU-R BS.1770 K-weighting: a head shelf then a high-pass.

    Coefficients are the standard's own, defined at 48 kHz and re-derived here
    for whatever rate the render used, so the loudness figure is the same one a
    streaming service would compute.
    """
    shelf_f, shelf_q, shelf_gain = 1681.974450955533, 0.7071752369554196, 3.999843853973347
    a = 10 ** (shelf_gain / 40)
    w = 2 * math.pi * shelf_f / rate
    alpha = math.sin(w) / (2 * shelf_q)
    cos_w = math.cos(w)
    b_shelf = np.array([a * ((a + 1) + (a - 1) * cos_w + 2 * math.sqrt(a) * alpha), -2 * a * ((a - 1) + (a + 1) * cos_w), a * ((a + 1) + (a - 1) * cos_w - 2 * math.sqrt(a) * alpha)])
    a_shelf = np.array([(a + 1) - (a - 1) * cos_w + 2 * math.sqrt(a) * alpha, 2 * ((a - 1) - (a + 1) * cos_w), (a + 1) - (a - 1) * cos_w - 2 * math.sqrt(a) * alpha])

    pass_f, pass_q = 38.13547087602444, 0.5003270373238773
    w = 2 * math.pi * pass_f / rate
    alpha = math.sin(w) / (2 * pass_q)
    cos_w = math.cos(w)
    b_pass = np.array([1.0, -2.0, 1.0]) * ((1 + cos_w) / 2)
    a_pass = np.array([1 + alpha, -2 * cos_w, 1 - alpha])

    filtered = signal.lfilter(b_shelf / a_shelf[0], a_shelf / a_shelf[0], samples, axis=0)
    return signal.lfilter(b_pass / a_pass[0], a_pass / a_pass[0], filtered, axis=0)


def loudness(samples: np.ndarray, rate: int) -> float:
    """Integrated loudness in LUFS, gated as BS.1770-4 specifies.

    Two gates: everything below -70 LUFS is silence, and everything more than
    10 LU below the average of what remains is a quiet passage that should not
    drag the number down.
    """
    if samples.ndim == 1:
        samples = samples[:, None]
    weighted = k_weight(samples.astype(np.float64), rate)
    block = int(0.4 * rate)
    step = max(int(0.1 * rate), 1)
    if len(weighted) < block:
        return -70.0
    starts = range(0, len(weighted) - block + 1, step)
    powers = np.array([float(np.mean(weighted[start : start + block] ** 2, axis=0).sum()) for start in starts])
    levels = -0.691 + 10 * np.log10(np.maximum(powers, 1e-12))
    loud = powers[levels > -70.0]
    if not len(loud):
        return -70.0
    relative = -0.691 + 10 * math.log10(float(loud.mean())) - 10.0
    gated = powers[(levels > -70.0) & (levels > relative)]
    if not len(gated):
        gated = loud
    return -0.691 + 10 * math.log10(float(gated.mean()))


# A band holding less than this share of the whole mix is not somewhere two
# parts can meaningfully fight, however evenly they split it. Without this,
# two tracks with almost no top end score a perfect collision in "air".
BAND_PRESENCE = 0.03


def collisions(tracks: list[TrackMix]) -> list[Collision]:
    """Where two parts are both loud in the same band.

    Scored as how much of the band the pair accounts for, times how evenly they
    split it. Two quiet parts overlapping is not a problem, and one part
    dominating a band it shares is not a problem either — the problem is two
    parts of similar weight in the same place.

    Only the worst band is kept per pair: telling a producer that the pads and
    the lead collide in four regions at once is noise, not judgement.
    """
    total = sum(t.energy for t in tracks)
    if total <= 0:
        return []
    worst: dict[tuple[str, str], Collision] = {}
    for name, _, _ in BANDS:
        energies = {t.track_id: t.bands[name] * t.energy for t in tracks}
        band_total = sum(energies.values())
        if band_total / total < BAND_PRESENCE:
            continue
        for index, first in enumerate(tracks):
            for second in tracks[index + 1 :]:
                low, high = sorted((energies[first.track_id], energies[second.track_id]))
                if high <= 0:
                    continue
                score = ((low + high) / band_total) * (low / high)
                pair = (first.track_id, second.track_id)
                if score > 0.05 and score > getattr(worst.get(pair), "score", 0.0):
                    worst[pair] = Collision(first.track_id, second.track_id, name, score)
    return sorted(worst.values(), key=lambda c: c.score, reverse=True)[:8]


def analyse(stems: dict[str, np.ndarray], rate: int, tracks: dict[str, tuple[str, str]], master: np.ndarray | None = None) -> Mix:
    """Measure a set of rendered stems. `tracks` maps id to (name, role)."""
    measured: list[TrackMix] = []
    for track_id, samples in stems.items():
        name, role = tracks.get(track_id, (track_id, "lead"))
        audio = samples if samples.ndim > 1 else samples[:, None]
        energies, total = band_energy(audio, rate)
        rms = float(np.sqrt(np.mean(audio**2))) if audio.size else 0.0
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        measured.append(TrackMix(track_id=track_id, name=name, role=role, rms_db=db(rms), peak_db=db(peak), crest_db=db(peak) - db(rms), correlation=correlation(audio), bands=shares(energies, total), energy=total))

    length = max((len(s) for s in stems.values()), default=0)
    if master is not None:
        summed = master if master.ndim > 1 else master[:, None]
    elif stems:
        summed = np.zeros((length, 2), dtype=np.float64)
        for samples in stems.values():
            audio = samples if samples.ndim > 1 else samples[:, None]
            if audio.shape[1] == 1:  # a mono stem sits in the middle, not the left
                audio = np.repeat(audio, 2, axis=1)
            summed[: len(audio), : audio.shape[1]] += audio[:, :2]
    else:
        summed = np.zeros((1, 2), dtype=np.float64)
    energies, total = band_energy(summed, rate)
    rms = float(np.sqrt(np.mean(summed**2))) if summed.size else 0.0
    peak = float(np.max(np.abs(summed))) if summed.size else 0.0
    return Mix(tracks=measured, bands=shares(energies, total), crest_db=db(peak) - db(rms), peak_db=db(peak), loudness_lufs=loudness(summed, rate), collisions=collisions(measured))


@dataclass
class Finding:
    """One measured problem, in plain language, with the fix it implies."""

    problem: str
    headline: str
    detail: str
    tracks: list[str]
    actions: list[dict]

    def as_dict(self) -> dict:
        return {"problem": self.problem, "headline": self.headline, "detail": self.detail, "tracks": self.tracks, "actions": self.actions}


def percent(value: float) -> str:
    return f"{round(value * 100)}%"


def loudest_in(mix: Mix, band: str, exclude: set[str] = frozenset()) -> list[TrackMix]:
    """Which parts are actually putting energy into a band, loudest first."""
    contributors = [t for t in mix.tracks if t.role not in exclude and t.bands[band] * t.energy > 0]
    return sorted(contributors, key=lambda t: t.bands[band] * t.energy, reverse=True)


# The measurement says which region is crowded; these are the controls that
# reach each region, so a finding can only ever propose an edit RDX can make.
CONTROL_FOR_BAND = {"sub": "low", "low": "low", "mud": "low", "mid": "mid", "high": "high", "air": "high"}


def cut(project: Project, track_id: str, control: str, amount: float) -> dict:
    """A `sound` action that lowers one EQ band from where it currently sits.

    The action vocabulary takes absolute values, so the current setting has to
    be read from the project rather than assumed to be flat — otherwise a
    second pass over an already-corrected mix would undo the first one.
    """
    track = next((t for t in project.tracks if t.id == track_id), None)
    current = getattr(track.sound, control) if track else 0.0
    return {"kind": "sound", "track": track_id, "params": {control: round(max(-24.0, current - amount), 1)}}


def findings(mix: Mix, project: Project) -> list[Finding]:
    """Everything worth telling a producer about, most important first.

    Order matters: a masking problem between two parts is more useful than a
    broad statement about the whole spectrum, because it names what to change.
    """
    found: list[Finding] = []
    by_id = {t.track_id: t for t in mix.tracks}

    # Three at most. A list of every overlap is a spectrum analyser; a mix
    # engineer tells you the two things to fix first.
    for collision in [c for c in mix.collisions if c.score >= LIMITS["collision"]][:3]:
        first, second = by_id[collision.a], by_id[collision.b]
        pair = sorted((first, second), key=lambda t: t.energy, reverse=True)
        actions: list[dict]
        if collision.band in {"sub", "low"} and {"drums"} & {first.role, second.role}:
            # The oldest collision in dance music, and ducking is its answer.
            other = first if second.role == "drums" else second
            source = first if first.role == "drums" else second
            actions = [{"kind": "sidechain", "track": other.track_id, "params": {"source": source.track_id, "shape": "tight"}}]
            headline = f"{other.name} and {source.name} are fighting in {BAND_WORDS[collision.band]}"
            detail = f"They share {percent(collision.score)} of {BAND_WORDS[collision.band]}. Ducking {other.name} under the kick is what makes room without turning anything down."
        else:
            quieter = pair[1]
            control = CONTROL_FOR_BAND[collision.band]
            actions = [cut(project, quieter.track_id, control, 3.0)]
            headline = f"{pair[0].name} and {quieter.name} are competing in {BAND_WORDS[collision.band]}"
            detail = f"They share {percent(collision.score)} of {BAND_WORDS[collision.band]}. Taking 3 dB out of {quieter.name} there leaves {pair[0].name} the space."
        found.append(Finding("masking", headline, detail, [first.track_id, second.track_id], actions))

    if mix.bands["mud"] > LIMITS["mud_share"]:
        crowding = [t for t in loudest_in(mix, "mud", exclude={"drums"})[:2]]
        found.append(Finding(
            "muddy",
            "The mix is muddy",
            f"{percent(mix.bands['mud'])} of the energy sits between 200 and 400 Hz, against {percent(LIMITS['mud_share'])} in a mix that reads as clear. "
            + (f"Most of it is coming from {' and '.join(t.name for t in crowding)}." if crowding else ""),
            [t.track_id for t in crowding],
            [cut(project, t.track_id, "low", 3.5) for t in crowding],
        ))

    bottom = mix.bands["sub"] + mix.bands["low"]
    if bottom + mix.bands["mud"] > LIMITS["low_share"]:
        heavy = loudest_in(mix, "low", exclude={"bass"})[:2]
        found.append(Finding(
            "boomy",
            "There is too much bottom end",
            f"{percent(bottom + mix.bands['mud'])} of the mix is below 400 Hz, against {percent(LIMITS['low_share'])} where it stops sounding powerful and starts sounding heavy. "
            + (f"The bass is doing its job; it is {' and '.join(t.name for t in heavy)} adding weight underneath it." if heavy else "It is coming from the bass itself."),
            [t.track_id for t in heavy],
            [cut(project, t.track_id, "low", 4.0) for t in heavy],
        ))
    elif bottom < LIMITS["bottom_thin"]:
        bass = next((t for t in mix.tracks if t.role == "bass"), None)
        found.append(Finding("thin", "The mix has no weight underneath", f"Only {percent(bottom)} of the energy is below 200 Hz, against {percent(LIMITS['bottom_thin'])} in a mix with a foundation.", [bass.track_id] if bass else [], [{"kind": "character", "track": bass.track_id, "params": {"character": "fat", "intensity": 0.6}}] if bass else []))

    if mix.bands["high"] > LIMITS["high_share"]:
        harshest = loudest_in(mix, "high")[:1]
        found.append(Finding("harsh", "The top is harsh", f"{percent(mix.bands['high'])} of the energy is between 2.5 and 8 kHz, where the ear is most sensitive. Above {percent(LIMITS['high_share'])} it becomes tiring.", [t.track_id for t in harshest], [{"kind": "character", "track": t.track_id, "params": {"character": "smooth", "intensity": 0.6}} for t in harshest]))
    elif mix.bands["air"] < LIMITS["air_thin"]:
        brightest = loudest_in(mix, "air", exclude={"bass"})[:1]
        found.append(Finding("dull", "The mix is closed in", f"Only {percent(mix.bands['air'])} of the energy is above 8 kHz. There is nothing open at the top.", [t.track_id for t in brightest], [{"kind": "character", "track": t.track_id, "params": {"character": "airy", "intensity": 0.5}} for t in brightest]))

    if mix.crest_db < LIMITS["crest"]:
        eased = round(min(0.0, project.master.compression + 6), 1)
        found.append(Finding("squashed", "The mix has no dynamics left", f"Peaks are only {round(mix.crest_db, 1)} dB above the average level; below about {LIMITS['crest']} dB nothing punches. The master compressor is working too hard.", [], [{"kind": "master", "params": {"compression": eased}}]))

    loudest = max(mix.tracks, key=lambda t: t.rms_db, default=None)
    if loudest:
        for track in mix.tracks:
            if loudest.rms_db - track.rms_db > LIMITS["buried"] and track.energy > 0:
                found.append(Finding("buried", f"{track.name} is buried", f"It sits {round(loudest.rms_db - track.rms_db)} dB below {loudest.name}. Anything more than {round(LIMITS['buried'])} dB down stops being part of the music.", [track.track_id], [{"kind": "mix", "track": track.track_id, "params": {"delta_db": 4}}]))

    if mix.loudness_lufs > LIMITS["loudness"]:
        quieter = round(max(-30.0, project.master.volume_db - (mix.loudness_lufs - LIMITS["loudness"])), 1)
        found.append(Finding("loud", "The master is pushed very hard", f"Integrated loudness is {round(mix.loudness_lufs, 1)} LUFS. Streaming turns everything down to about -14, so past {LIMITS['loudness']} the extra level is thrown away and only the damage is kept.", [], [{"kind": "master", "params": {"volume_db": quieter}}]))

    return found


def summarise(mix: Mix, found: list[Finding]) -> str:
    """The reading a producer gets, whether or not anything is wrong."""
    header = f"Measured: {round(mix.loudness_lufs, 1)} LUFS, {round(mix.crest_db, 1)} dB of dynamic range, " + ", ".join(f"{name} {percent(share)}" for name, share in mix.bands.items() if share >= 0.01) + "."
    if not found:
        return header + "\nNothing measures as a problem."
    return header + "\n" + "\n".join(f"{index + 1}. {finding.headline}. {finding.detail}" for index, finding in enumerate(found))
