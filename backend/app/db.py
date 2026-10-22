"""Banco SQLite (arquivo único em <data_dir>/clipflow.db)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from . import config, storage

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT '',
    progress REAL NOT NULL DEFAULT 0,
    source_type TEXT NOT NULL,
    source_url TEXT,
    source_key TEXT,
    source_title TEXT,
    source_channel TEXT,
    source_duration REAL,
    source_width INTEGER,
    source_height INTEGER,
    source_size INTEGER,
    source_path TEXT,
    source_thumbnail TEXT,
    rights_basis TEXT NOT NULL,
    rights_note TEXT NOT NULL DEFAULT '',
    rights_confirmed_at REAL NOT NULL,
    options_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    processing_seconds REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projects_key ON projects(source_key);

CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL DEFAULT 0,
    start REAL NOT NULL,
    end REAL NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    score REAL NOT NULL DEFAULT 0,
    scores_json TEXT NOT NULL DEFAULT '{}',
    reasons_json TEXT NOT NULL DEFAULT '[]',
    selected INTEGER NOT NULL DEFAULT 0,
    layout TEXT NOT NULL DEFAULT 'auto',
    manual_x REAL,
    words_json TEXT,
    status TEXT NOT NULL DEFAULT 'candidate',
    output_path TEXT,
    thumb_path TEXT,
    srt_path TEXT,
    duration REAL,
    size_bytes INTEGER,
    titles_json TEXT NOT NULL DEFAULT '[]',
    description TEXT NOT NULL DEFAULT '',
    hashtags_json TEXT NOT NULL DEFAULT '[]',
    keywords_json TEXT NOT NULL DEFAULT '[]',
    render_info_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at REAL NOT NULL,
    rendered_at REAL
);
CREATE INDEX IF NOT EXISTS idx_clips_project ON clips(project_id);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT '',
    progress REAL NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 2,
    error TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    run_after REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

-- publicação nas redes (hoje: YouTube); um registro por envio de um corte
CREATE TABLE IF NOT EXISTS publications (
    id TEXT PRIMARY KEY,
    clip_id TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    platform TEXT NOT NULL DEFAULT 'youtube',
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    privacy TEXT NOT NULL DEFAULT 'private',
    publish_at REAL,
    category_id TEXT NOT NULL DEFAULT '24',
    notify INTEGER NOT NULL DEFAULT 1,
    video_id TEXT,
    url TEXT,
    session_url TEXT,
    bytes_sent INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    run_after REAL NOT NULL DEFAULT 0,
    error TEXT,
    note TEXT,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_publications_clip ON publications(clip_id);
CREATE INDEX IF NOT EXISTS idx_publications_status ON publications(status);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
"""

_init_lock = threading.Lock()
_initialized_for: str | None = None


def db_path():
    return storage.root() / "clipflow.db"


def _connect() -> sqlite3.Connection:
    c = sqlite3.connect(db_path(), timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA busy_timeout = 30000")
    return c


# Colunas acrescentadas depois da 1ª versão (só adições: versões antigas do app as ignoram)
MIGRATIONS = [
    ("clips", "hook_json", "TEXT"),   # ganchos: candidatos, notas, escolha manual (pipeline/hooks.py)
]


def _migrate(c: sqlite3.Connection) -> None:
    for table, column, decl in MIGRATIONS:
        cols = {row["name"] for row in c.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init() -> None:
    global _initialized_for
    with _init_lock:
        storage.ensure_layout()
        c = _connect()
        try:
            c.execute("PRAGMA journal_mode = WAL")
            c.executescript(SCHEMA)
            _migrate(c)
            c.commit()
            for row in c.execute("SELECT key, value_json FROM settings"):
                try:
                    config.set_override(row["key"], config.coerce(row["key"], json.loads(row["value_json"])))
                except ValueError:
                    pass
        finally:
            c.close()
        _initialized_for = str(db_path())


@contextmanager
def conn() -> Iterator[sqlite3.Connection]:
    if _initialized_for != str(db_path()):
        init()
    c = _connect()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now() -> float:
    return time.time()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    for k in list(d.keys()):
        if k.endswith("_json"):
            raw = d.pop(k)
            d[k[:-5]] = json.loads(raw) if raw else None
    return d


def fetch_one(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    with conn() as c:
        return row_to_dict(c.execute(sql, params).fetchone())


def fetch_all(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with conn() as c:
        return [row_to_dict(r) for r in c.execute(sql, params).fetchall()]


def execute(sql: str, params: tuple = ()) -> int:
    with conn() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid if cur.lastrowid else cur.rowcount


def update(table: str, row_id: Any, **fields: Any) -> None:
    if table not in {"projects", "clips", "jobs", "publications"}:
        raise ValueError("tabela inválida")
    if not fields:
        return
    cols, vals = [], []
    for k, v in fields.items():
        if not k.replace("_", "").isalnum():
            raise ValueError("coluna inválida")
        if k.endswith("_json") and not isinstance(v, str) and v is not None:
            v = json.dumps(v, ensure_ascii=False)
        cols.append(f"{k} = ?")
        vals.append(v)
    if table == "projects" and "updated_at" not in fields:
        cols.append("updated_at = ?")
        vals.append(now())
    vals.append(row_id)
    with conn() as c:
        c.execute(f"UPDATE {table} SET {', '.join(cols)} WHERE id = ?", tuple(vals))


def save_setting(key: str, value: Any) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO settings(key, value_json) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
            (key, json.dumps(value)),
        )
    config.set_override(key, value)
