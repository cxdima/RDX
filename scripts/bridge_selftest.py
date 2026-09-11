"""Pretend to be the Max device, so the two halves can be told apart.

When the bridge does not connect there are two possible faults and no way to
tell them apart from inside Live: either the studio's HTTP side is wrong, or
Node for Max never ran the script that talks to it.

This does exactly what `bridge/connection.js` does — reads the same two files,
sends the same request with the same header — using nothing but Python. If it
succeeds, the studio side is proven and the fault is inside Max. If it fails,
the message says which part.

    .venv/bin/python scripts/bridge_selftest.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

from rdx.bridge import DEVICE_VERSION

ROOT = Path(__file__).resolve().parent.parent
# Exactly what bridge/live.js reports, version included: a payload that has
# drifted from the device it impersonates proves the wrong thing, and would make
# the studio show a stale-device warning during its own self-test.
STATE = {"tempo": 124.0, "has_content": False, "arrangement_end": 0, "track_count": 0, "playing": False, "busy": False, "tracks": None, "scanned": False, "device_version": DEVICE_VERSION}


def fail(message: str) -> int:
    print(f"FAILED  {message}")
    return 1


def main() -> int:
    connection = ROOT / "data" / "bridge-connection.json"
    token_file = ROOT / "data" / "bridge-token"
    if not connection.exists():
        return fail("data/bridge-connection.json is missing. Start the studio first with `npm start`.")
    if not token_file.exists():
        return fail("data/bridge-token is missing. The studio writes it on startup; start it with `npm start`.")

    port = json.loads(connection.read_text())["port"]
    token = token_file.read_text().strip()
    url = f"http://127.0.0.1:{port}/api/bridge"
    print(f"studio     http://127.0.0.1:{port}")
    print(f"token      {token[:6]}... ({len(token)} characters)")

    try:
        status = httpx.get(f"http://127.0.0.1:{port}/api/status", timeout=5).json()
    except httpx.HTTPError as error:
        return fail(f"nothing is listening on port {port} ({error}). Start the studio with `npm start`.")
    print(f"service    {status['service']}, bridge currently {'connected' if status['bridge']['connected'] else 'disconnected'}")

    refused = httpx.post(f"{url}/poll", json=STATE, headers={"X-RDX-Token": "wrong"}, timeout=5)
    if refused.status_code != 403:
        return fail(f"an invalid token was accepted with {refused.status_code}; the bridge is not authenticating")
    print("auth       an invalid token is rejected with 403")

    answer = httpx.post(f"{url}/poll", json=STATE, headers={"X-RDX-Token": token}, timeout=5)
    if answer.status_code != 200:
        return fail(f"a valid token was rejected with {answer.status_code}: {answer.text[:200]}")
    print(f"poll       accepted, command queued: {answer.json()['command'] is not None}")

    after = httpx.get(f"http://127.0.0.1:{port}/api/status", timeout=5).json()
    if not after["bridge"]["connected"]:
        return fail("the poll was accepted but the studio still reports the bridge as disconnected")
    print(f"state      the studio now sees Live at {after['bridge']['live'].get('tempo')} BPM")

    print()
    print("The studio's half of the bridge works. If the device in Live still says")
    print("'Connecting to RDX...', the fault is inside Max: node.script never ran")
    print("bridge/connection.js, or live.js never sent it any state.")
    print()
    print("Next, with the Max window open BEFORE the device loads:")
    print("  1. In Live, delete the RDX Bridge device and drag it in again.")
    print("  2. Watch the Max window for errors as it loads.")
    print("  3. 'node.script: could not find' means the path is wrong;")
    print("     a silent window means live.js never produced any output.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
