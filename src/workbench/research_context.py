"""Durable, local evidence archive, independent of temporary search history."""
import hashlib
import json
from .store import now

def initialize(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS research_context (
      id INTEGER PRIMARY KEY,run_id TEXT NOT NULL,kind TEXT NOT NULL,
      content_hash TEXT NOT NULL,payload TEXT NOT NULL,created TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS research_context_run ON research_context(run_id,id);
    CREATE TABLE IF NOT EXISTS research_assets (
      id TEXT PRIMARY KEY,mime TEXT NOT NULL,content BLOB NOT NULL,created TEXT NOT NULL);
    """)

def capture(store,run_id,kind,payload):
    encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True)
    digest=hashlib.sha256(encoded.encode()).hexdigest()
    with store.db() as db:
        return db.execute('INSERT INTO research_context(run_id,kind,content_hash,payload,created) VALUES(?,?,?,?,?)',
            (run_id,kind,digest,encoded,now())).lastrowid

def asset(store,content):
    if len(content)>2_000_000:raise ValueError('Image exceeds capture limit')
    digest=hashlib.sha256(content).hexdigest()
    with store.db() as db:
        db.execute('INSERT OR IGNORE INTO research_assets VALUES(?,?,?,?)',(digest,'image/png',content,now()))
    return digest
