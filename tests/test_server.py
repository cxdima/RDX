import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from rdx import server
from rdx.bridge import Bridge
from rdx.domain import Action, Plan
from rdx.engine import starter_project
from rdx.store import Store
import time


@pytest.fixture
def client(tmp_path, monkeypatch):
    database = Store(tmp_path / "test.sqlite")
    monkeypatch.setattr(server, "store", database)
    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "ASSETS", tmp_path)
    monkeypatch.setattr(server, "RENDERS", tmp_path)
    monkeypatch.setattr(server, "bridge", Bridge())
    monkeypatch.setattr(server, "proposals", {})
    with TestClient(server.app, base_url="http://127.0.0.1") as client:
        yield client
    database.db.close()


def test_edit_stale_revision_and_undo(client):
    project = client.get("/api/projects").json()[0]
    url = f'/api/projects/{project["id"]}'
    edit = {"revision":0, "actions":[{"kind":"project", "params":{"tempo":117}}]}
    result = client.post(url + "/edits", json=edit)
    assert result.status_code == 200
    assert result.json()["tempo"] == 117
    assert client.post(url + "/edits", json=edit).status_code == 409
    assert client.post(url + "/undo", json={"revision":1}).json()["tempo"] == 124


def test_model_preview_keep_and_rejection_feedback(client, monkeypatch):
    project = client.get("/api/projects").json()[0]
    url = f'/api/projects/{project["id"]}'
    monkeypatch.setattr(server.model, "generate", lambda *args: Plan(summary="Slower", actions=[Action(kind="project", params={"tempo":117})]))
    proposed = client.post(url + "/chat", json={"revision":0,"message":"Slower"}).json()
    assert proposed["preview"]["tempo"] == 117
    assert client.get(url).json()["tempo"] == 124
    assert client.post(f'/api/proposals/{proposed["id"]}', json={"revision":0,"keep":True}).json()["tempo"] == 117
    assert client.post(f'/api/proposals/{proposed["id"]}', json={"revision":0,"keep":True}).status_code == 404
    proposed = client.post(url + "/chat", json={"revision":1,"message":"Another"}).json()
    client.post(f'/api/proposals/{proposed["id"]}', json={"revision":1,"keep":False,"comment":"Too slow"})
    rows = server.store.db.execute("SELECT rating,comment FROM feedback ORDER BY id").fetchall()
    assert [(r[0], r[1]) for r in rows] == [("accepted", ""), ("rejected", "Too slow")]


def test_proposal_stale_after_manual_edit(client, monkeypatch):
    project = client.get("/api/projects").json()[0]
    url = f'/api/projects/{project["id"]}'
    monkeypatch.setattr(server.model, "generate", lambda *args: Plan(summary="Slower", actions=[Action(kind="project", params={"tempo":117})]))
    proposed = client.post(url + "/chat", json={"revision":0,"message":"Slower"}).json()
    client.post(url + "/edits", json={"revision":0,"actions":[{"kind":"project","params":{"tempo":130}}]})
    assert client.post(f'/api/proposals/{proposed["id"]}', json={"revision":1,"keep":True}).status_code == 409
    assert client.get(url).json()["tempo"] == 130


def test_validation_guided_retry_does_not_apply_failed_action(client, monkeypatch):
    project=client.get('/api/projects').json()[0]
    url=f'/api/projects/{project["id"]}'
    replies=iter([Plan(summary='Tempo',actions=[Action(kind='master',params={'tempo':117})]),Plan(summary='Tempo',actions=[Action(kind='project',params={'tempo':117})])])
    monkeypatch.setattr(server.model,'generate',lambda *args:next(replies))
    response=client.post(url+'/chat',json={'revision':0,'message':'Make it 117 BPM'})
    assert response.status_code == 200
    assert response.json()['preview']['tempo'] == 117
    assert client.get(url).json()['tempo'] == 124


def test_security_and_bridge_auth(client):
    assert client.post("/api/projects", json={}, headers={"Origin":"https://untrusted.example"}).status_code == 403
    assert client.get("/api/status", headers={"Host":"attacker.example"}).status_code == 400
    assert client.post("/api/bridge/poll", json={}).status_code == 403
    response = client.post("/api/bridge/poll", json={"tempo":124}, headers={"X-RDX-Token":server.bridge.token})
    assert response.status_code == 200
    assert client.get("/api/status").json()["bridge"]["connected"]


def test_archive_is_valid_and_midi_exported(client):
    project = client.get("/api/projects").json()[0]
    contents = client.get(f'/api/projects/{project["id"]}/export/project')
    with zipfile.ZipFile(io.BytesIO(contents.content)) as archive:
        assert json.loads(archive.read("project.rdx.json"))["id"] == project["id"]
        assert archive.read("arrangement.mid").startswith(b"MThd")
    imported = client.post('/api/projects/import',files={'file':('session.zip',contents.content,'application/zip')})
    assert imported.status_code == 200
    assert imported.json()['id'] != project['id']
    assert imported.json()['revision'] == 0


def test_bridge_delivery_is_not_repeated():
    bridge = Bridge()
    with pytest.raises(ValueError, match="not connected"):
        bridge.send(starter_project(), {})
    bridge.poll({"tempo":124,"has_content":False})
    job = bridge.send(starter_project(), {})
    assert bridge.poll({})["id"] == job
    assert bridge.poll({}) is None
    with pytest.raises(ValueError, match="Unexpected"):
        bridge.acknowledge({"id":"wrong"})
    bridge.acknowledge({"id":job,"ok":True,"message":"Done"})
    assert not bridge.status()["pending"]


def test_accepting_a_refusal_does_not_write_history(client):
    """A proposal with no actions is a question, not an edit."""
    from rdx import server

    project = client.post("/api/projects", json={"name": "Refusal", "starter": True}).json()
    proposal_id = "a" * 12
    server.proposals[proposal_id] = {
        "project_id": project["id"],
        "revision": project["revision"],
        "request": "sidechain the pads",
        "context": {},
        "selection": None,
        "plan": server.Plan(actions=[], note="RDX has no sidechain."),
        "summary": "RDX has no sidechain.",
        "created": time.time(),
    }
    before = client.get(f"/api/projects/{project['id']}/history").json()
    kept = client.post(f"/api/proposals/{proposal_id}", json={"revision": project["revision"], "keep": True})
    assert kept.status_code == 200
    assert kept.json()["revision"] == project["revision"]
    after = client.get(f"/api/projects/{project['id']}/history").json()
    assert after["entries"] == before["entries"]
