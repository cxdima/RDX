from __future__ import annotations

import asyncio
import io
import hashlib
import json
import secrets
import time
import threading
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import audio
from .bridge import Bridge
from .domain import Clip, EditRequest, Model, Project, new_track, uid
from .engine import EditError, apply_actions, context, starter_project
from .model import DATA, ROOT, LocalModel
from .store import Conflict, Store

DATA.mkdir(exist_ok=True)
ASSETS = DATA / "audio"
ASSETS.mkdir(exist_ok=True)
RENDERS = DATA / "renders"
RENDERS.mkdir(exist_ok=True)
store = Store(DATA / "rdx.sqlite")
model = LocalModel()
bridge = Bridge()
proposals = {}
proposal_lock = threading.RLock()
chat_lock = asyncio.Lock()
build_hash = hashlib.sha256()
for source in sorted((ROOT / "rdx").glob("*.py")):
    build_hash.update(source.name.encode())
    build_hash.update(source.read_bytes())
BUILD = build_hash.hexdigest()


@asynccontextmanager
async def lifespan(app):
    (DATA / "bridge-token").write_text(bridge.token)
    if not store.list():
        store.create(starter_project())
    yield
    model.close()


app = FastAPI(title="RDX Studio", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])


@app.middleware("http")
async def local_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and urlparse(origin).hostname not in {"127.0.0.1", "localhost"}:
        return JSONResponse({"detail": "Local requests only"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(ValueError)
async def invalid(request, error):
    return JSONResponse({"detail": str(error)}, status_code=409 if isinstance(error, Conflict) else 400)


@app.exception_handler(KeyError)
async def missing(request, error):
    return JSONResponse({"detail": "Project or asset not found"}, status_code=404)


@app.get("/api/status")
def status():
    return {"service":"rdx-studio", "build":BUILD, "model": model.status(), "bridge": bridge.status()}


@app.get("/api/projects")
def projects():
    return store.list()


class NewProject(Model):
    name: str = Field(default="Untitled", max_length=100, min_length=1)
    starter: bool = True


@app.post("/api/projects")
def create(request: NewProject):
    project = starter_project()
    project.name = request.name
    if not request.starter:
        for track in project.tracks:
            track.clips = []
    return store.create(project)


@app.get("/api/projects/{project_id}")
def get(project_id: str):
    return store.get(project_id)


@app.post("/api/projects/import")
async def import_project(file: UploadFile = File()):
    contents = await file.read(300 * 1024 * 1024 + 1)
    if len(contents) > 300 * 1024 * 1024:
        raise ValueError("Project archives must be under 300 MB")
    try:
        with zipfile.ZipFile(io.BytesIO(contents)) as archive:
            entries = archive.infolist()
            if len(entries) > 200 or sum(e.file_size for e in entries) > 500 * 1024 * 1024:
                raise ValueError("This archive exceeds the project size limit")
            if len({e.filename for e in entries}) != len(entries):
                raise ValueError("The archive contains duplicate files")
            if archive.getinfo("project.rdx.json").file_size > 16 * 1024 * 1024:
                raise ValueError("The project description is too large")
            project = Project.model_validate_json(archive.read("project.rdx.json"))
            if not project.tracks or not project.sections:
                raise ValueError("A project must have at least one track and section")
            recordings = {}
            import soundfile as sf
            for old_id in {c.audio_id for t in project.tracks for c in t.clips if c.audio_id}:
                path = f"audio/{old_id}.wav"
                if archive.getinfo(path).file_size > 55 * 1024 * 1024:
                    raise ValueError("A recording exceeds the supported size")
                data = archive.read(path)
                info = sf.info(io.BytesIO(data))
                if info.format != "WAV" or not 0 < info.duration <= 301:
                    raise ValueError("Invalid project recording")
                recordings[old_id] = (uid(), data)
            project.id, project.revision = uid(), 0
            for old_id, (new_id, data) in recordings.items():
                destination = ASSETS / f"{new_id}.wav"
                destination.write_bytes(data)
                (ASSETS / f"{new_id}.json").write_text(json.dumps(audio.analysis(destination)))
                for track in project.tracks:
                    for clip in track.clips:
                        if clip.audio_id == old_id:
                            clip.audio_id = new_id
    except (zipfile.BadZipFile, KeyError, RuntimeError) as error:
        raise ValueError("This is not a complete RDX project archive") from error
    return store.create(project)


@app.post("/api/projects/{project_id}/edits")
def edit(project_id: str, request: EditRequest):
    original = store.get(project_id)
    if original.revision != request.revision:
        raise Conflict("The project changed; refresh before editing")
    return store.save(apply_actions(original, request.actions), request.revision, request.label)


class Revision(Model):
    revision: int


@app.post("/api/projects/{project_id}/undo")
def undo(project_id: str, request: Revision):
    return store.move(project_id, request.revision, -1)


@app.post("/api/projects/{project_id}/redo")
def redo(project_id: str, request: Revision):
    return store.move(project_id, request.revision, 1)


@app.get("/api/projects/{project_id}/history")
def history(project_id: str):
    store.get(project_id)
    return store.history(project_id)


@app.get("/api/projects/{project_id}/messages")
def messages(project_id: str):
    return store.messages(project_id)


class Chat(Revision):
    message: str = Field(min_length=1, max_length=2000)
    track_id: str | None = None
    section_id: str | None = None


@app.post("/api/projects/{project_id}/chat")
async def chat(project_id: str, request: Chat):
    if chat_lock.locked():
        raise HTTPException(429, "The local model is already preparing an edit")
    async with chat_lock:
        original = store.get(project_id)
        if original.revision != request.revision:
            raise Conflict("Refresh the project before asking for a change")
        ctx = context(original, request.track_id, request.section_id)
        previous = store.messages(project_id)
        store.add_message(project_id, "user", request.message)
        try:
            plan = await asyncio.to_thread(model.generate, ctx, request.message, previous)
            try:
                preview = apply_actions(original, plan.actions) if plan.actions else original
            except ValueError as error:
                if any(t.locked for t in original.tracks):
                    raise
                correction = request.message + "\nYour previous proposal failed validation: " + str(error)[:500] + "\nPrevious JSON: " + plan.model_dump_json() + "\nReturn one corrected JSON plan using the supported action kinds, track and section targets, and params. Do not broaden the original request."
                plan = await asyncio.to_thread(model.generate, ctx, correction, [])
                preview = apply_actions(original, plan.actions) if plan.actions else original
        except ValueError as error:
            store.add_message(project_id, "assistant", str(error))
            raise
        if store.get(project_id).revision != request.revision:
            raise Conflict("The project changed while the alternative was being prepared")
        store.add_message(project_id, "assistant", plan.summary)
        proposal_id = uid()
        with proposal_lock:
            proposals[proposal_id] = {"project_id": project_id, "revision": original.revision, "request": request.message, "context": ctx, "plan": plan, "created": time.time()}
            for old in list(proposals):
                if time.time() - proposals[old]["created"] > 3600:
                    del proposals[old]
        return {"id": proposal_id, "plan": plan, "preview": preview}


class Decision(Revision):
    keep: bool
    comment: str = Field(default="", max_length=2000)


@app.post("/api/proposals/{proposal_id}")
def decide(proposal_id: str, request: Decision):
    with proposal_lock:
        return apply_decision(proposal_id, request)


def apply_decision(proposal_id: str, request: Decision):
    proposed = proposals.get(proposal_id)
    if not proposed:
        raise HTTPException(404, "That alternative is no longer available")
    original = store.get(proposed["project_id"])
    if original.revision != request.revision or proposed["revision"] != request.revision:
        raise Conflict("The project changed after this alternative was prepared")
    if request.keep:
        original = store.save(apply_actions(original, proposed["plan"].actions), request.revision, proposed["plan"].summary[:150])
    store.feedback(original.id, original.revision, proposed["request"], proposed["context"], proposed["plan"].model_dump(), "accepted" if request.keep else "rejected", request.comment)
    del proposals[proposal_id]
    return original


@app.post("/api/projects/{project_id}/audio")
async def import_audio(project_id: str, file: UploadFile = File(), revision: int = Form(), section_id: str = Form(), mode: str = Form("audio"), track_id: str = Form("")):
    if mode not in {"audio", "hum", "rhythm", "midi"}:
        raise ValueError("Unknown recording mode")
    project = store.get(project_id)
    if project.revision != revision:
        raise Conflict("Refresh the project before importing")
    section = next((s for s in project.sections if s.id == section_id), None)
    if not section:
        raise ValueError("Select a section")
    contents = await file.read(50 * 1024 * 1024 + 1)
    if len(contents) > 50 * 1024 * 1024:
        raise ValueError("This version accepts recordings up to 50 MB")
    name = Path(file.filename or "Recording").stem[:55]
    if mode == "midi":
        for track_name, role, notes in audio.midi_import(contents, section.bars):
            track = new_track(role, track_name)
            track.clips = [Clip(name=track_name, section_id=section.id, notes=notes)]
            project.tracks.append(track)
    else:
        asset_id = uid()
        source, destination = ASSETS / f"{asset_id}.upload", ASSETS / f"{asset_id}.wav"
        source.write_bytes(contents)
        try:
            await asyncio.to_thread(audio.decode_audio, source, destination)
        finally:
            source.unlink(missing_ok=True)
        info = await asyncio.to_thread(audio.analysis, destination)
        (ASSETS / f"{asset_id}.json").write_text(json.dumps({**info, "name": name}))
        if mode == "audio":
            track = new_track("audio", name)
            track.clips = [Clip(name=name, section_id=section.id, audio_id=asset_id)]
            project.tracks.append(track)
        else:
            track = next((t for t in project.tracks if t.id == track_id), None)
            if not track or track.locked:
                raise ValueError("Select an unprotected track for the recording")
            if mode == "rhythm" and track.role != "drums":
                raise ValueError("Select a drum track for rhythm input")
            if mode == "hum" and track.role in {"drums", "audio"}:
                raise ValueError("Select a melodic instrument for humming")
            notes = await asyncio.to_thread(audio.transcribe, destination, project.tempo, section.bars, mode)
            track.clips = [c for c in track.clips if c.section_id != section.id] + [Clip(name=name, section_id=section.id, notes=notes)]
    return store.save(Project.model_validate(project.model_dump()), revision, f"Imported {name}")


@app.get("/api/audio/{asset_id}/{kind}")
def asset(asset_id: str, kind: str):
    if not asset_id.isalnum() or len(asset_id) != 12 or kind not in {"wave", "info"}:
        raise HTTPException(404)
    path = ASSETS / (asset_id + (".wav" if kind == "wave" else ".json"))
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="audio/wav" if kind == "wave" else "application/json")


@app.get("/api/projects/{project_id}/export/{kind}")
def export(project_id: str, kind: str):
    project = store.get(project_id)
    if kind == "midi":
        return Response(audio.midi_export(project), media_type="audio/midi", headers={"Content-Disposition": 'attachment; filename="RDX.mid"'})
    if kind == "project":
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("project.rdx.json", project.model_dump_json(indent=2))
            archive.writestr("arrangement.mid", audio.midi_export(project))
            for asset_id in {c.audio_id for t in project.tracks for c in t.clips if c.audio_id}:
                archive.write(ASSETS / f"{asset_id}.wav", f"audio/{asset_id}.wav")
        return Response(buffer.getvalue(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="RDX-project.zip"'})
    raise HTTPException(404)


@app.post("/api/renders")
async def upload_render(file: UploadFile = File()):
    contents = await file.read(300 * 1024 * 1024 + 1)
    if len(contents) > 300 * 1024 * 1024:
        raise ValueError("The rendered stem exceeds 300 MB")
    import soundfile as sf
    try:
        info = sf.info(io.BytesIO(contents))
        if info.format != "WAV" or info.channels != 2 or info.samplerate != 44100 or not 0 < info.duration <= 1600:
            raise ValueError("Expected a stereo 44.1 kHz WAV stem")
    except RuntimeError as error:
        raise ValueError("Invalid audio render") from error
    render_id = uid()
    (RENDERS / f"{render_id}.wav").write_bytes(contents)
    return {"id": render_id}


class Transfer(Revision):
    stems: dict[str, str]


@app.post("/api/projects/{project_id}/ableton")
def send_to_ableton(project_id: str, request: Transfer):
    project = store.get(project_id)
    if project.revision != request.revision:
        raise Conflict("Refresh before sending to Ableton")
    if set(request.stems) != {t.id for t in project.tracks}:
        raise ValueError("Render every track before transferring")
    paths = {}
    for track_id, asset_id in request.stems.items():
        if len(asset_id) != 12 or not asset_id.isalnum() or not (RENDERS / f"{asset_id}.wav").is_file():
            raise ValueError("A rendered stem is missing")
        paths[track_id] = str(RENDERS / f"{asset_id}.wav")
    return {"id": bridge.send(project, paths)}


@app.get("/api/bridge/device")
def bridge_device():
    path = ROOT / "artifacts" / "RDX Bridge.amxd"
    if not path.exists():
        raise HTTPException(404, "Bridge device has not been built")
    return FileResponse(path, filename="RDX Bridge.amxd", media_type="application/octet-stream")


def bridge_auth(token):
    if not token or not secrets.compare_digest(token, bridge.token):
        raise HTTPException(403, "Invalid bridge connection")


@app.post("/api/bridge/poll")
def poll(body: dict, x_rdx_token: str | None = Header(default=None)):
    bridge_auth(x_rdx_token)
    return {"command": bridge.poll(body)}


@app.post("/api/bridge/result")
def result(body: dict, x_rdx_token: str | None = Header(default=None)):
    bridge_auth(x_rdx_token)
    bridge.acknowledge(body)
    return {"ok": True}


if (ROOT / "dist").exists():
    app.mount("/", StaticFiles(directory=ROOT / "dist", html=True), name="studio")
