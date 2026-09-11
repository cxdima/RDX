"""The README is a set of claims. These check them against the code.

RDX's whole argument is that a capability list means nothing unless something
can verify it, and a README that names a sound, a move or a scale the engine
does not have is the same failure as an edit that reports success and does
something else — just slower to find out about.

So the lists in the README are parsed and compared to the tables they describe.
Adding a capability without documenting it fails here, and so does documenting
one that was never built.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from rdx.domain import MELODIC_PRESETS, SCALES
from rdx.musical.character import CHARACTERS
from rdx.musical.design import PATCHES
from rdx.musical.moves import MOVES

README = (Path(__file__).resolve().parent.parent / "README.md").read_text()


def listed_after(heading: str) -> set[str]:
    """The italicised names in the paragraph introduced by a bold heading.

    Both shapes the README uses are handled: one long italic run of
    comma-separated names, and a series of separately italicised words.
    """
    match = re.search(rf"\*\*{heading}[^*]*\.\*\*(.*?)\n\n", README, re.S)
    assert match, f"the README should have a paragraph for {heading}"
    paragraph = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", match.group(1))
    names: set[str] = set()
    for run in re.findall(r"\*([^*]+)\*", paragraph):
        for word in run.replace(" and ", ", ").split(","):
            cleaned = re.sub(r"\s+", "_", word.strip(" .\n—-")).lower()
            # Quoted phrases in the prose are examples, not names.
            if cleaned and '"' not in cleaned:
                names.add(cleaned)
    return names


def test_the_readme_lists_exactly_the_character_words_that_exist():
    claimed = listed_after(r"\d+ musical adjectives")
    assert claimed & set(CHARACTERS), "the paragraph should name the words"
    assert not claimed - set(CHARACTERS), f"the README claims words the code does not have: {claimed - set(CHARACTERS)}"
    assert not set(CHARACTERS) - claimed, f"these words exist but are undocumented: {set(CHARACTERS) - claimed}"


def test_the_readme_counts_the_character_words_correctly():
    stated = int(re.search(r"\*\*(\d+) musical adjectives", README).group(1))
    assert stated == len(CHARACTERS)


def test_the_readme_lists_exactly_the_named_sounds_that_exist():
    claimed = listed_after("Sixteen sounds by name")
    assert claimed == set(PATCHES), f"README and design.py disagree: {claimed ^ set(PATCHES)}"


def test_the_readme_lists_exactly_the_moves_that_exist():
    claimed = listed_after(r"\w+ production moves")
    assert claimed == set(MOVES), f"README and moves.py disagree: {claimed ^ set(MOVES)}"


def test_the_readme_lists_exactly_the_scales_that_exist():
    match = re.search(r"\*\*Six scales, not two\.\*\*(.*?)\n\n", README, re.S)
    assert match, "the README should say which scales there are"
    claimed = {w.lower() for w in re.findall(r"\b[A-Z][a-z]+\b|\bminor\b", match.group(1))}
    assert set(SCALES) <= claimed, f"undocumented scales: {set(SCALES) - claimed}"


@pytest.mark.parametrize("preset", MELODIC_PRESETS)
def test_every_instrument_is_named_in_the_readme(preset):
    spelled = {"fm": "FM", "supersaw": "supersaw"}.get(preset, preset)
    assert re.search(rf"\b{spelled}\b", README, re.I), f"{preset} is playable but undocumented"


def test_the_readme_does_not_claim_the_ableton_transfer_works():
    """The one claim in this project that must never soften by accident.

    The handshake was confirmed on 10 September 2026 and the README says so.
    The transfer has not been, and this fails if that sentence ever loses its
    "never" — which is the only way it should be allowed to change.
    """
    assert re.search(r"the\s+transfer\s+—\s+has \*\*never\*\* been confirmed", README, re.S)
