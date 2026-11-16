"""Chat history: SQLite locally, DynamoDB HISTORY_TABLE on AWS."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

USE_AWS = os.environ.get("USE_AWS_STORAGE", "false").lower() == "true"


def _sqlite_path() -> Path:
    root = Path(os.environ.get("MOBILERUN_DATA", Path.home() / ".mobilerun"))
    root.mkdir(parents=True, exist_ok=True)
    return root / "chat.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_sqlite_path()))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            meta TEXT,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_messages(session_id, created_at)"
    )
    conn.commit()
    return conn


def _dynamo_table():
    if not USE_AWS:
        return None
    name = os.environ.get("HISTORY_TABLE")
    if not name:
        return None
    import boto3

    return boto3.resource("dynamodb").Table(name)


def ensure_session(session_id: Optional[str] = None) -> str:
    return session_id or f"chat_{uuid.uuid4().hex[:12]}"


def append_message(
    session_id: str,
    role: str,
    content: str,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    msg_id = f"msg_{uuid.uuid4().hex[:10]}"
    created = time.time()
    record = {
        "id": msg_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "meta": meta or {},
        "created_at": created,
    }

    table = _dynamo_table()
    if table is not None:
        # HISTORY_TABLE: PK task_id, SK timestamp — reuse for chat sessions
        table.put_item(
            Item={
                "task_id": f"chat:{session_id}",
                "timestamp": int(created * 1000),
                "msg_id": msg_id,
                "role": role,
                "content": content,
                "meta": json.dumps(meta or {}),
                "ttl": int(created) + 60 * 60 * 24 * 30,
            }
        )
        return record

    with _conn() as conn:
        conn.execute(
            "INSERT INTO chat_messages(id, session_id, role, content, meta, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (msg_id, session_id, role, content, json.dumps(meta or {}), created),
        )
        conn.commit()
    return record


def list_messages(session_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    table = _dynamo_table()
    if table is not None:
        resp = table.query(
            KeyConditionExpression="task_id = :t",
            ExpressionAttributeValues={":t": f"chat:{session_id}"},
            Limit=limit,
            ScanIndexForward=True,
        )
        out = []
        for item in resp.get("Items", []):
            meta_raw = item.get("meta") or "{}"
            try:
                meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw
            except json.JSONDecodeError:
                meta = {}
            out.append(
                {
                    "id": item.get("msg_id"),
                    "session_id": session_id,
                    "role": item.get("role"),
                    "content": item.get("content"),
                    "meta": meta,
                    "created_at": float(item.get("timestamp", 0)) / 1000.0,
                }
            )
        return out

    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, session_id, role, content, meta, created_at FROM chat_messages "
            "WHERE session_id = ? ORDER BY created_at ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    result = []
    for r in rows:
        try:
            meta = json.loads(r["meta"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        result.append(
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "role": r["role"],
                "content": r["content"],
                "meta": meta,
                "created_at": r["created_at"],
            }
        )
    return result
