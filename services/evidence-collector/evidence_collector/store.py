# Made with Claude (Claude Code, Anthropic)
"""SQLite store: raw events (one row per bus message, numbered like events.jsonl) and evidence records.

One connection behind a lock: the Zenoh callback thread, the tick thread and the HTTP server all use it.
Evidence records are also written as <evidence_dir>/<record_id>.json, so they survive without the database.
"""
import json
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    line INTEGER PRIMARY KEY, rx_ts_ms INTEGER NOT NULL, topic TEXT NOT NULL, msg_id TEXT, raw TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence (
    record_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, started_at INTEGER, verdict TEXT NOT NULL, json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS evidence_run ON evidence (run_id, started_at);
"""


class Store:
    def __init__(self, db_path, evidence_dir):
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)

    def add_event(self, line: int, rx_ts_ms: int, topic: str, msg_id: Optional[str], raw: str) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO events VALUES (?, ?, ?, ?, ?)", (line, rx_ts_ms, topic, msg_id, raw))

    def events(self, since: int = 0, limit: int = 500, until: Optional[int] = None) -> List[dict]:
        sql, args = "SELECT raw FROM events WHERE line > ?", [since]
        if until is not None:
            sql, args = sql + " AND line <= ?", args + [until]
        with self._lock:
            rows = self._db.execute(sql + " ORDER BY line LIMIT ?", (*args, limit)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def save(self, record: dict) -> None:
        text = json.dumps(record, indent=2, sort_keys=True, default=str)
        (self.evidence_dir / f"{record['record_id']}.json").write_text(text + "\n")
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, ?, ?)",
                             (record["record_id"], record["run_id"], record.get("started_at"), record["verdict"], text))

    def records(self, run_id: Optional[str] = None, limit: int = 1000) -> List[dict]:
        sql, args = "SELECT json FROM evidence", []
        if run_id:
            sql, args = sql + " WHERE run_id = ?", [run_id]
        with self._lock:
            rows = self._db.execute(sql + " ORDER BY started_at DESC LIMIT ?", (*args, limit)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def record(self, record_id: str) -> Optional[dict]:
        with self._lock:
            row = self._db.execute("SELECT json FROM evidence WHERE record_id = ?", (record_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def close(self) -> None:
        with self._lock:
            self._db.close()
