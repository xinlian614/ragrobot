"""SQLite 存储层：知识库文档与向量分块。"""

import sqlite3
import threading
from datetime import datetime
from typing import Any

import numpy as np

from . import config

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    """创建数据库连接（行数据以字典方式访问）。"""
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """初始化数据表。"""
    with _lock, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id          TEXT PRIMARY KEY,
                filename    TEXT NOT NULL,
                ext         TEXT NOT NULL,
                size        INTEGER NOT NULL,
                status      TEXT NOT NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                error       TEXT,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id      TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content     TEXT NOT NULL,
                embedding   BLOB,
                FOREIGN KEY (doc_id) REFERENCES documents (id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks (doc_id);
            """
        )


def _now() -> str:
    """当前时间字符串。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_document(doc_id: str, filename: str, ext: str, size: int) -> None:
    """写入一条处于解析中状态的文档记录。"""
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO documents (id, filename, ext, size, status, chunk_count, created_at) "
            "VALUES (?, ?, ?, ?, 'processing', 0, ?)",
            (doc_id, filename, ext, size, _now()),
        )


def mark_document_ready(doc_id: str, chunk_count: int) -> None:
    """标记文档入库完成。"""
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE documents SET status='ready', chunk_count=?, error=NULL WHERE id=?",
            (chunk_count, doc_id),
        )


def mark_document_failed(doc_id: str, error: str) -> None:
    """标记文档入库失败并记录原因。"""
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE documents SET status='failed', error=? WHERE id=?",
            (error[:500], doc_id),
        )


def delete_document(doc_id: str) -> bool:
    """删除文档及其分块，返回是否存在该文档。"""
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        return cur.rowcount > 0


def list_documents() -> list[dict[str, Any]]:
    """按创建时间倒序列出全部文档。"""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT id, filename, ext, size, status, chunk_count, error, created_at "
            "FROM documents ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def insert_chunks(doc_id: str, chunks: list[str], vectors: list[list[float]] | None) -> None:
    """批量写入分块；vectors 为空表示使用关键词检索、不保存向量。"""
    payload = []
    for idx, text in enumerate(chunks):
        blob = np.asarray(vectors[idx], dtype=np.float32).tobytes() if vectors else None
        payload.append((doc_id, idx, text, blob))
    with _lock, _connect() as conn:
        conn.executemany(
            "INSERT INTO chunks (doc_id, chunk_index, content, embedding) VALUES (?, ?, ?, ?)",
            payload,
        )


def load_chunks() -> list[dict[str, Any]]:
    """加载全部分块用于检索。"""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT c.doc_id, c.chunk_index, c.content, c.embedding, d.filename "
            "FROM chunks c JOIN documents d ON d.id = c.doc_id "
            "WHERE d.status='ready'"
        ).fetchall()
    result = []
    for row in rows:
        result.append(
            {
                "doc_id": row["doc_id"],
                "filename": row["filename"],
                "chunk_index": row["chunk_index"],
                "content": row["content"],
                "vector": np.frombuffer(row["embedding"], dtype=np.float32) if row["embedding"] else None,
            }
        )
    return result


def stats() -> dict[str, int]:
    """统计文档数量、就绪数与分块总数。"""
    with _lock, _connect() as conn:
        doc_total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        doc_ready = conn.execute("SELECT COUNT(*) FROM documents WHERE status='ready'").fetchone()[0]
        chunk_total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    return {"documents": doc_total, "ready_documents": doc_ready, "chunks": chunk_total}
