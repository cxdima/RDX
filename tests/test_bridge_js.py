"""Tests for the Max side of the bridge, without Ableton.

`bridge/live.js` is the one piece of RDX that can only run inside Max, which
made it the least tested code in the project — and the three faults behind the
first working transfer were all in here, all silent.

This runs it in Node against a stubbed Live API. It proves the logic: that a
Set is read into the shape RDX expects, that a name containing spaces survives
Max splitting it into symbols, that a plugin is recognised as one, and that a
device scan failing does not take the whole poll down with it. It cannot prove
how real Live behaves — that is what the notes in RDX_PLAN.md are for.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "bridge" / "harness.cjs"


def run(live_set: dict, tmp_path: Path) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    # Everything the stub can reach by id, the way Live's object model works.
    # The Set itself is reached by path rather than by id, so it stays out of
    # the index — putting it in makes the structure refer to itself.
    by_id: dict[str, dict] = {}
    for track in live_set.get("track_objects", []):
        by_id[str(track["id"])] = track
        for slot in track.get("slot_objects", []):
            by_id[str(slot["id"])] = slot
        for device in track.get("device_objects", []):
            by_id[str(device["id"])] = device
            for parameter in device.get("parameter_objects", []):
                by_id[str(parameter["id"])] = parameter
    live_set["byId"] = by_id
    path = tmp_path / "set.json"
    path.write_text(json.dumps(live_set))
    result = subprocess.run([node, str(HARNESS), "--set", str(path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def a_set(tracks: list[dict], tempo: float = 124.0) -> dict:
    """A Live Set as the stub exposes it: ids that resolve to objects."""
    identifier = [10]

    def next_id() -> int:
        identifier[0] += 1
        return identifier[0]

    track_objects = []
    for track in tracks:
        devices = []
        for device in track.get("devices", []):
            parameters = [{"id": next_id(), "name": name, "min": 0.0, "max": 1.0, "value": 0.5} for name in device.get("parameters", [])]
            devices.append({"id": next_id(), "name": device["name"], "class_name": device.get("class_name", "InstrumentVector"), "class_display_name": device.get("kind", device["name"]), "parameters": [p["id"] for p in parameters], "parameter_objects": parameters})
        slots = [{"id": next_id(), "has_clip": 0} for _ in range(track.get("slots", 0))]
        track_objects.append({
            "id": next_id(),
            "name": track["name"],
            "has_midi_input": 1 if track.get("midi") else 0,
            "devices": [d["id"] for d in devices],
            "device_objects": devices,
            "arrangement_clips": [],
            "clip_slots": [s["id"] for s in slots],
            "slot_objects": slots,
        })
    return {"id": 1, "tempo": tempo, "is_playing": 0, "tracks": [t["id"] for t in track_objects], "track_objects": track_objects}


def test_the_set_is_read_into_the_shape_rdx_expects(tmp_path):
    state = run(a_set([
        {"name": "Lead", "midi": True, "devices": [{"name": "Wavetable", "kind": "Wavetable"}]},
        {"name": "Drums", "midi": True, "devices": [{"name": "Drum Rack", "kind": "Drum Rack"}]},
        {"name": "Vocals", "midi": False, "devices": []},
    ]), tmp_path)["state"]
    assert state["tempo"] == 124 and state["track_count"] == 3
    assert [t["name"] for t in state["tracks"]] == ["Lead", "Drums", "Vocals"]
    assert [t["midi"] for t in state["tracks"]] == [True, True, False]
    assert state["tracks"][0]["devices"][0]["kind"] == "Wavetable"
    assert state["tracks"][2]["devices"] == []


def test_a_device_name_with_spaces_survives_max_splitting_it(tmp_path):
    """Max returns a symbol containing spaces as several symbols."""
    state = run(a_set([{"name": "Bus", "midi": False, "devices": [{"name": "EQ Eight", "kind": "EQ Eight"}]}]), tmp_path)["state"]
    assert state["tracks"][0]["devices"][0]["name"] == "EQ Eight"
    assert state["tracks"][0]["devices"][0]["kind"] == "EQ Eight"


def test_a_plugin_is_reported_as_one(tmp_path):
    """RDX can drive a plugin's parameters but can never insert it."""
    state = run(a_set([
        {"name": "Serum", "midi": True, "devices": [{"name": "Serum 2", "class_name": "PluginDevice", "kind": "Serum 2"}]},
        {"name": "Native", "midi": True, "devices": [{"name": "Operator", "class_name": "InstrumentVector", "kind": "Operator"}]},
    ]), tmp_path)["state"]
    assert state["tracks"][0]["devices"][0]["plugin"] is True
    assert state["tracks"][1]["devices"][0]["plugin"] is False


def test_an_empty_set_reads_as_empty_rather_than_failing(tmp_path):
    result = run(a_set([]), tmp_path)
    assert result["errors"] == []
    assert result["state"]["track_count"] == 0 and result["state"]["tracks"] == []


def test_the_poll_keeps_working_even_if_the_device_scan_cannot_run(tmp_path):
    """The tempo is what the transfer checks; it must survive a scan failure."""
    broken = a_set([{"name": "Odd", "midi": True, "devices": []}])
    broken["track_objects"][0]["devices"] = "not-a-list"
    result = run(broken, tmp_path)
    assert result["state"]["tempo"] == 124, "the rest of the poll still has to arrive"
    assert result["polls"] >= 1


def count_notes(reply, tmp_path: Path) -> dict:
    """Run countNotes against a scripted get_notes_extended reply."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    path = tmp_path / "reply.json"
    path.write_text(json.dumps({"reply": reply}))
    result = subprocess.run([node, str(HARNESS), "--notes", str(path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_notes_are_counted_from_the_reply_live_actually_sends(tmp_path):
    """get_notes_extended answers with the dictionary's contents, as JSON."""
    reply = json.dumps({"notes": [{"note_id": 1, "pitch": 36, "start_time": 0.0, "duration": 0.12, "velocity": 100}, {"note_id": 2, "pitch": 38, "start_time": 1.0, "duration": 0.12, "velocity": 90}]})
    assert count_notes(reply, tmp_path)["count"] == 2


def test_an_empty_clip_counts_as_empty_rather_than_as_an_error(tmp_path):
    assert count_notes('{"notes": []}', tmp_path)["count"] == 0


def test_a_reply_that_cannot_be_read_is_reported_rather_than_counted_as_zero(tmp_path):
    """Zero notes and an unreadable answer are different, and were confused.

    Treating the reply as a dictionary name produced an empty dictionary, so a
    clip full of notes read back as zero — which looked exactly like the write
    having failed, and hid the real bug for three attempts.
    """
    unreadable = count_notes("dictionary u123456789", tmp_path)
    assert unreadable["count"] == -1
    assert "unreadable" in unreadable["detail"]


def test_device_parameters_are_discovered_by_name(tmp_path):
    """A sound mapping has to be built from the names Live actually reports."""
    state = run(a_set([{"name": "Lead", "midi": True, "devices": [
        {"name": "Wavetable", "kind": "Wavetable", "parameters": ["Device On", "Filter 1 Freq", "Osc 1 Transpose"]},
    ]}]), tmp_path)["state"]
    device = state["tracks"][0]["devices"][0]
    assert [p["name"] for p in device["parameters"]] == ["Device On", "Filter 1 Freq", "Osc 1 Transpose"]
    assert device["parameter_count"] == 3
    assert device["parameters"][0]["min"] == 0 and device["parameters"][0]["max"] == 1


def test_a_device_with_many_parameters_does_not_bloat_the_poll(tmp_path):
    many = [f"Param {n}" for n in range(200)]
    state = run(a_set([{"name": "Big", "midi": True, "devices": [{"name": "Wavetable", "parameters": many}]}]), tmp_path)["state"]
    device = state["tracks"][0]["devices"][0]
    assert device["parameter_count"] == 200, "the real count is still reported"
    assert len(device["parameters"]) == 24, "but the names are capped"


def test_no_single_poll_ever_costs_live_very_much(tmp_path):
    """The bridge runs inside Live's own process, so every Live API object it
    builds and every property it reads is CPU taken from the music.

    Against the Set RDX had just transferred into — nine tracks, a Wavetable on
    each — reading the whole picture on every poll cost over a thousand round
    trips every 1.5 seconds, and Live sat at 137% CPU with nothing playing.
    Moving that to a slow timer would have fixed the average and left a burst
    big enough to cause a dropout, so instead the sweep walks one track per
    poll: no poll is expensive, and the full picture still arrives.
    """
    tracks = [
        {"name": f"RDX {i}", "midi": True, "slots": 8, "devices": [{"name": "Wavetable", "parameters": [f"Param {q}" for q in range(93)]}]}
        for i in range(9)
    ]
    state = run(a_set(tracks), tmp_path)
    cost = state["cost"]
    assert max(cost) < 200, f"no poll reads much: {cost}"
    assert sum(cost) / len(cost) < 100, f"and the average poll costs a fraction of the old 1340: {cost}"
    assert min(cost) <= 8, "and a poll during the rest between sweeps reads almost nothing"
    assert len(state["state"]["tracks"]) == 9, "and the whole Set is still reported"
    assert state["state"]["scanned"] is True


def test_the_set_reads_as_unscanned_until_the_first_sweep_finishes(tmp_path):
    """Nothing read yet must not look like an empty Set: RDX appends a transfer
    after whatever Live already contains, and 'nothing here' is where it would
    put the tracks."""
    tracks = [{"name": f"T{i}", "midi": True, "slots": 8} for i in range(40)]
    state = run(a_set(tracks), tmp_path)
    assert state["state"]["scanned"] is False, "40 tracks take more than 26 polls to sweep"
    assert state["state"]["tracks"] is None


def transfer_job(tempo=124):
    return {"id": "review-job", "kind": "append_project", "project": {
        "tempo": tempo, "revision": 1, "sections": [],
        "tracks": [{"id": "source", "name": "Rendered", "role": "audio", "color": "#ffffff", "mute": False, "solo": False}],
    }, "stems": {"source": "/test/stem.wav"}}


def test_transfer_reads_new_content_after_the_cached_sweep(tmp_path):
    live_set = a_set([{"name": "User recording", "midi": False}])
    live_set["command"] = transfer_job()
    live_set["new_content"] = {"end": 96.5}
    result = run(live_set, tmp_path)
    assert result["state"]["arrangement_end"] == 0, "the published sweep predates the recording"
    assert result["transfer"]["ok"] is True
    assert result["transfer"]["start_beat"] == 100
    clips = [w for w in result["writes"] if w.get("call") == "create_audio_clip"]
    assert clips[0]["args"] == ["/test/stem.wav", 100]
    assert not any(w.get("property") == "tempo" for w in result["writes"])


def test_content_added_after_the_sweep_prevents_a_tempo_overwrite(tmp_path):
    live_set = a_set([{"name": "User recording", "midi": False}], tempo=120)
    live_set["command"] = transfer_job(tempo=138)
    live_set["new_content"] = {"end": 32}
    result = run(live_set, tmp_path)
    assert result["transfer"]["ok"] is False
    assert "tempo" in result["transfer"]["message"]
    assert result["writes"] == [], "refuse before changing the Set"
