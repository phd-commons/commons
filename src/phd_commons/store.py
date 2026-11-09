"""The derived store: one SQLite file with FTS5 for text search and float32 blobs for vectors.

Everything here can be rebuilt from okf/ and library/ with `commons rebuild`. Vector search is a numpy
scan over a cached matrix, which is fast enough for a doctoral corpus (tens of thousands of chunks) and
works on every platform without loading SQLite extensions.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA secure_delete=ON;

CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY,
  slug TEXT UNIQUE,
  kind TEXT, title TEXT, authors_json TEXT, year INTEGER, venue TEXT,
  doi TEXT, url TEXT, licence TEXT,
  tier TEXT NOT NULL,
  sha256 TEXT UNIQUE,
  path_original TEXT, path_text TEXT,
  published_at TEXT, retrieved_at TEXT,
  status TEXT NOT NULL DEFAULT 'ingested',
  fail_reason TEXT, origin_feed TEXT, abstract TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  idx INTEGER, page_from INTEGER, page_to INTEGER, section TEXT,
  text TEXT NOT NULL,
  tier TEXT NOT NULL,
  embed_model TEXT,
  embedding BLOB
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, content='chunks', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.id, old.text);
END;

CREATE TABLE IF NOT EXISTS claims (
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  chunk_id INTEGER REFERENCES chunks(id) ON DELETE SET NULL,
  claim TEXT NOT NULL, quote TEXT NOT NULL, page INTEGER,
  claim_type TEXT,
  quote_verified INTEGER NOT NULL DEFAULT 0,
  verifier_verdict TEXT,
  status TEXT NOT NULL,
  provenance TEXT DEFAULT 'MEASURED',
  strength TEXT,
  tier TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS propositions (
  id INTEGER PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,
  family TEXT, title TEXT, statement TEXT,
  supports_if TEXT, disconfirms_if TEXT,
  status TEXT DEFAULT 'untested'
);

CREATE TABLE IF NOT EXISTS evidence_links (
  claim_id INTEGER NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
  proposition_code TEXT NOT NULL,
  stance TEXT NOT NULL,
  proposed_by TEXT, confirmed INTEGER NOT NULL DEFAULT 0, note TEXT,
  PRIMARY KEY (claim_id, proposition_code)
);

CREATE TABLE IF NOT EXISTS review_items (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL, ref_id INTEGER, payload_json TEXT, tier TEXT NOT NULL DEFAULT 'PRIVATE',
  created_at TEXT DEFAULT (datetime('now')),
  resolved_at TEXT, resolution TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL, payload_json TEXT,
  priority INTEGER NOT NULL DEFAULT 5,
  status TEXT NOT NULL DEFAULT 'queued',
  attempts INTEGER NOT NULL DEFAULT 0,
  lease_until REAL, log TEXT,
  created_at TEXT DEFAULT (datetime('now')), finished_at TEXT
);

CREATE TABLE IF NOT EXISTS model_calls (
  id INTEGER PRIMARY KEY,
  app TEXT, role TEXT, provider TEXT, model TEXT, locality TEXT, max_tier TEXT,
  prompt_sha TEXT, source_ids_json TEXT,
  tokens_in INTEGER, tokens_out INTEGER, ms INTEGER, ok INTEGER,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS data_tables (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE, module TEXT, as_at TEXT, path TEXT, provenance TEXT, description TEXT
);

CREATE TABLE IF NOT EXISTS feeds_state (
  feed_id TEXT PRIMARY KEY, cursor TEXT, last_run TEXT, last_ok TEXT, last_error TEXT
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, job TEXT, started_at TEXT, finished_at TEXT, ok INTEGER, summary TEXT
);
"""

_LOCK = threading.RLock()


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.execute("PRAGMA secure_delete=ON")
        self._vec_cache: tuple[int, np.ndarray, list[int], list[str]] | None = None

    # ---------- basics
    @contextmanager
    def tx(self):
        with _LOCK:
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def q(self, sql: str, args: tuple | list = ()) -> list[sqlite3.Row]:
        with _LOCK:
            return list(self.conn.execute(sql, args))

    def one(self, sql: str, args: tuple | list = ()) -> sqlite3.Row | None:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def scalar(self, sql: str, args: tuple | list = ()):
        r = self.one(sql, args)
        return r[0] if r else None

    def close(self) -> None:
        self.conn.close()

    # ---------- sources and chunks
    def add_source(self, **fields) -> int:
        fields.setdefault("retrieved_at", time.strftime("%Y-%m-%d"))
        if "authors" in fields:
            fields["authors_json"] = json.dumps(fields.pop("authors") or [])
        cols = ",".join(fields)
        marks = ",".join("?" for _ in fields)
        with self.tx() as c:
            cur = c.execute(f"INSERT INTO sources ({cols}) VALUES ({marks})", list(fields.values()))
            return int(cur.lastrowid)

    def add_chunks(self, source_id: int, tier: str, chunks: list[dict], embed_model: str,
                   vectors: np.ndarray | None) -> list[int]:
        existing = self.embed_models()
        if existing and embed_model not in existing:
            raise RuntimeError(
                f"Refusing to mix embedding spaces: index uses {sorted(existing)}, got {embed_model}. "
                "Run `commons rebuild` to re-embed everything with the new model."
            )
        ids = []
        with self.tx() as c:
            for i, ch in enumerate(chunks):
                blob = vectors[i].astype(np.float32).tobytes() if vectors is not None else None
                cur = c.execute(
                    "INSERT INTO chunks (source_id, idx, page_from, page_to, section, text, tier, embed_model, embedding)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (source_id, i, ch.get("page_from"), ch.get("page_to"), ch.get("section"), ch["text"], tier,
                     embed_model, blob),
                )
                ids.append(int(cur.lastrowid))
        self._vec_cache = None
        return ids

    def embed_models(self) -> set[str]:
        return {r[0] for r in self.q("SELECT DISTINCT embed_model FROM chunks WHERE embed_model IS NOT NULL")}

    # ---------- vector search
    def _matrix(self):
        n = self.scalar("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL") or 0
        maxid = self.scalar("SELECT MAX(id) FROM chunks") or 0
        key = n * 1_000_003 + maxid
        if self._vec_cache and self._vec_cache[0] == key:
            return self._vec_cache
        rows = self.q("SELECT id, tier, embedding FROM chunks WHERE embedding IS NOT NULL ORDER BY id")
        if not rows:
            self._vec_cache = (key, np.zeros((0, 1), dtype=np.float32), [], [])
            return self._vec_cache
        mat = np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        mat = mat / norms
        self._vec_cache = (key, mat, [int(r["id"]) for r in rows], [r["tier"] for r in rows])
        return self._vec_cache

    def vector_search(self, qvec: np.ndarray, k: int, tiers: set[str]) -> list[tuple[int, float]]:
        _, mat, ids, row_tiers = self._matrix()
        if not ids:
            return []
        q = qvec.astype(np.float32)
        q = q / (np.linalg.norm(q) or 1.0)
        scores = mat @ q
        mask = np.array([t in tiers for t in row_tiers])
        scores = np.where(mask, scores, -np.inf)
        top = np.argsort(-scores)[:k]
        return [(ids[i], float(scores[i])) for i in top if np.isfinite(scores[i])]

    def text_search(self, query: str, k: int, tiers: set[str]) -> list[tuple[int, float]]:
        terms = [t for t in "".join(ch if ch.isalnum() else " " for ch in query).split() if len(t) > 1]
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms[:30])
        marks = ",".join("?" for _ in tiers)
        rows = self.q(
            f"SELECT chunks.id, bm25(chunks_fts) AS s FROM chunks_fts JOIN chunks ON chunks.id = chunks_fts.rowid "
            f"WHERE chunks_fts MATCH ? AND chunks.tier IN ({marks}) ORDER BY s LIMIT ?",
            [match, *tiers, k],
        )
        return [(int(r[0]), float(-r[1])) for r in rows]

    # ---------- audit
    def log_call(self, **fields) -> None:
        cols = ",".join(fields)
        marks = ",".join("?" for _ in fields)
        with self.tx() as c:
            c.execute(f"INSERT INTO model_calls ({cols}) VALUES ({marks})", list(fields.values()))

    def add_review(self, kind: str, ref_id: int | None, payload: dict, tier: str = "PRIVATE") -> int:
        with self.tx() as c:
            cur = c.execute("INSERT INTO review_items (kind, ref_id, payload_json, tier) VALUES (?,?,?,?)",
                            (kind, ref_id, json.dumps(payload), tier))
            return int(cur.lastrowid)

    def counts(self) -> dict:
        return {
            "sources": self.scalar("SELECT COUNT(*) FROM sources WHERE status='ingested'") or 0,
            "chunks": self.scalar("SELECT COUNT(*) FROM chunks") or 0,
            "claims_verified": self.scalar(
                "SELECT COUNT(*) FROM claims WHERE status IN ('verified','confirmed')") or 0,
            "claims_review": self.scalar("SELECT COUNT(*) FROM claims WHERE status='review'") or 0,
            "review_open": self.scalar("SELECT COUNT(*) FROM review_items WHERE resolved_at IS NULL") or 0,
            "failed": self.scalar("SELECT COUNT(*) FROM sources WHERE status='failed'") or 0,
            "quarantined": self.scalar("SELECT COUNT(*) FROM sources WHERE status='quarantined'") or 0,
        }


def open_store(ws) -> Store:
    return Store(ws.db_path)
