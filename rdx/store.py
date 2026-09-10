from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .domain import Project


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT, revision INTEGER, cursor INTEGER, updated REAL, state TEXT);
          CREATE TABLE IF NOT EXISTS history(project_id TEXT, position INTEGER, label TEXT, state TEXT, created REAL, PRIMARY KEY(project_id, position));
          CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY, project_id TEXT, revision INTEGER, request TEXT, context TEXT, plan TEXT, rating TEXT, comment TEXT, created REAL);
          CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, project_id TEXT, role TEXT, content TEXT, created REAL);
          CREATE TABLE IF NOT EXISTS measurements(project_id TEXT, revision INTEGER, mix TEXT, created REAL, PRIMARY KEY(project_id, revision));
        """)

    def list(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT id,name,revision,updated FROM projects ORDER BY updated DESC")]

    def create(self, project: Project):
        with self.lock, self.db:
            self.db.execute("INSERT INTO projects VALUES(?,?,?,?,?,?)", (project.id, project.name, 0, 0, time.time(), project.model_dump_json()))
            self.db.execute("INSERT INTO history VALUES(?,?,?,?,?)", (project.id, 0, "Created project", project.model_dump_json(), time.time()))
        return project

    def get(self, project_id: str) -> Project:
        with self.lock:
            row = self.db.execute("SELECT state FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise KeyError("Project not found")
        return Project.model_validate_json(row["state"])

    def save(self, project: Project, expected: int, label: str):
        with self.lock, self.db:
            row = self.db.execute("SELECT revision,cursor FROM projects WHERE id=?", (project.id,)).fetchone()
            if row is None or row["revision"] != expected:
                raise Conflict("The project changed while this edit was being prepared. Refresh and retry.")
            project.revision = expected + 1
            position = row["cursor"] + 1
            self.db.execute("DELETE FROM history WHERE project_id=? AND position>?", (project.id, row["cursor"]))
            self.db.execute("INSERT INTO history VALUES(?,?,?,?,?)", (project.id, position, label, project.model_dump_json(), time.time()))
            self.db.execute("UPDATE projects SET name=?,revision=?,cursor=?,updated=?,state=? WHERE id=?", (project.name, project.revision, position, time.time(), project.model_dump_json(), project.id))
        return project

    def move(self, project_id: str, revision: int, direction: int):
        with self.lock, self.db:
            row = self.db.execute("SELECT revision,cursor FROM projects WHERE id=?", (project_id,)).fetchone()
            if row is None or row["revision"] != revision:
                raise Conflict("The project has changed")
            cursor = row["cursor"] + direction
            snapshot = self.db.execute("SELECT state FROM history WHERE project_id=? AND position=?", (project_id, cursor)).fetchone()
            if snapshot is None:
                raise Conflict("No further history in that direction")
            project = Project.model_validate_json(snapshot["state"])
            project.revision = revision + 1
            self.db.execute("UPDATE projects SET name=?,revision=?,cursor=?,updated=?,state=? WHERE id=?", (project.name, project.revision, cursor, time.time(), project.model_dump_json(), project_id))
        return project

    def history(self, project_id: str):
        with self.lock:
            row = self.db.execute("SELECT cursor FROM projects WHERE id=?", (project_id,)).fetchone()
            return {"cursor": row[0], "entries": [dict(r) for r in self.db.execute("SELECT position,label,created FROM history WHERE project_id=? ORDER BY position DESC LIMIT 100", (project_id,))]}

    def add_message(self, project_id, role, content):
        with self.lock, self.db:
            self.db.execute("INSERT INTO messages(project_id,role,content,created) VALUES(?,?,?,?)", (project_id, role, content, time.time()))

    def messages(self, project_id):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT role,content FROM messages WHERE project_id=? ORDER BY id DESC LIMIT 40", (project_id,))][::-1]

    def measure(self, project_id: str, revision: int, mix: dict):
        """Keep a mix measurement against the exact revision that produced it.

        Pinning to the revision is the point: a measurement of a different
        arrangement is worse than no measurement, because it looks current.
        """
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO measurements VALUES(?,?,?,?)", (project_id, revision, json.dumps(mix), time.time()))
            self.db.execute("DELETE FROM measurements WHERE project_id=? AND revision<?", (project_id, revision - 8))

    def measurement(self, project_id: str, revision: int) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT mix FROM measurements WHERE project_id=? AND revision=?", (project_id, revision)).fetchone()
        return json.loads(row["mix"]) if row else None

    def last_measured(self, project_id: str) -> int | None:
        """The newest revision that was ever measured, so the studio can say
        "this is out of date" rather than "this was never done"."""
        with self.lock:
            row = self.db.execute("SELECT MAX(revision) AS revision FROM measurements WHERE project_id=?", (project_id,)).fetchone()
        return row["revision"] if row and row["revision"] is not None else None

    def feedback(self, project_id, revision, request, context, plan, rating, comment):
        with self.lock, self.db:
            self.db.execute("INSERT INTO feedback(project_id,revision,request,context,plan,rating,comment,created) VALUES(?,?,?,?,?,?,?,?)", (project_id, revision, request, json.dumps(context), json.dumps(plan), rating, comment, time.time()))
