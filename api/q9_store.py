"""Q9 — durable persistence layer.

Uses SQLite by default (file path via Q9_DB_PATH env var). IMPORTANT: this
only survives across grading runs if the file lives on a persistent disk.
On platforms without a guaranteed persistent disk, point Q9_DB_PATH at a
mounted volume, or swap this module for a real hosted Postgres connection.
"""
import json
import os
import sqlite3
import threading

DB_PATH = os.environ.get("Q9_DB_PATH", os.path.join(os.path.dirname(__file__), "q9_state.db"))

_lock = threading.Lock()


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock, get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dossier_cache (
                content_hash TEXT PRIMARY KEY,
                dossier_id TEXT NOT NULL,
                call_id TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT,
                payload TEXT NOT NULL,
                evidence TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS evaluations (
                evaluation_id TEXT PRIMARY KEY,
                input_digest TEXT NOT NULL,
                pubkey_x TEXT NOT NULL,
                proposals_json TEXT NOT NULL,
                propose_request_hash TEXT NOT NULL,
                propose_response_json TEXT NOT NULL,
                status TEXT NOT NULL,
                commit_request_hash TEXT,
                commit_response_json TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS executed_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                evaluation_id TEXT NOT NULL,
                dossier_id TEXT NOT NULL,
                call_id TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT,
                payload TEXT NOT NULL,
                executed_at TEXT NOT NULL
            )
        """)
        conn.commit()


init_db()


# ---------------------------------------------------------------------------
# dossier_cache: canonical-content -> stable (callId, action, target,
# payload, evidence), so identical dossiers always produce the identical
# proposal & callId, and never re-trigger a model call once cached.
# ---------------------------------------------------------------------------

def get_cached_proposal(content_hash: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM dossier_cache WHERE content_hash = ?", (content_hash,)
        ).fetchone()
    if not row:
        return None
    return {
        "dossierId": row["dossier_id"],
        "callId": row["call_id"],
        "action": row["action"],
        "target": json.loads(row["target"]) if row["target"] else None,
        "payload": json.loads(row["payload"]),
        "evidence": json.loads(row["evidence"]),
    }


def put_cached_proposal(content_hash: str, dossier_id: str, proposal: dict):
    with _lock, get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO dossier_cache
               (content_hash, dossier_id, call_id, action, target, payload, evidence)
               VALUES (?,?,?,?,?,?,?)""",
            (
                content_hash,
                dossier_id,
                proposal["callId"],
                proposal["action"],
                json.dumps(proposal["target"]) if proposal["target"] is not None else None,
                json.dumps(proposal["payload"]),
                json.dumps(proposal["evidence"]),
            ),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# evaluations: one row per evaluationId, tracking propose state, then commit
# state once it arrives. Enables exact replay + conflict detection.
# ---------------------------------------------------------------------------

def get_evaluation(evaluation_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM evaluations WHERE evaluation_id = ?", (evaluation_id,)
        ).fetchone()
    return dict(row) if row else None


def put_evaluation_propose(evaluation_id, input_digest, pubkey_x, proposals, propose_request_hash, propose_response):
    with _lock, get_conn() as conn:
        conn.execute(
            """INSERT INTO evaluations
               (evaluation_id, input_digest, pubkey_x, proposals_json,
                propose_request_hash, propose_response_json, status)
               VALUES (?,?,?,?,?,?,?)""",
            (
                evaluation_id,
                input_digest,
                pubkey_x,
                json.dumps(proposals),
                propose_request_hash,
                json.dumps(propose_response),
                "awaiting_receipts",
            ),
        )
        conn.commit()


def put_evaluation_commit(evaluation_id, commit_request_hash, commit_response):
    with _lock, get_conn() as conn:
        conn.execute(
            """UPDATE evaluations
               SET status = 'completed', commit_request_hash = ?, commit_response_json = ?
               WHERE evaluation_id = ?""",
            (commit_request_hash, json.dumps(commit_response), evaluation_id),
        )
        conn.commit()


def log_executed_action(evaluation_id, dossier_id, call_id, action, target, payload):
    import datetime
    with _lock, get_conn() as conn:
        conn.execute(
            """INSERT INTO executed_actions
               (evaluation_id, dossier_id, call_id, action, target, payload, executed_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                evaluation_id, dossier_id, call_id, action,
                json.dumps(target) if target is not None else None,
                json.dumps(payload),
                datetime.datetime.utcnow().isoformat() + "Z",
            ),
        )
        conn.commit()
