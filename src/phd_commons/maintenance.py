"""Rebuild, backup and purge."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sqlite3
import zipfile
from pathlib import Path

import yaml

from .ingest import ingest_file
from .okf import append_log, export_claims_register, write_index, write_source_note
from .store import Store

CARRY_TABLES = ("review_items", "model_calls", "data_tables", "feeds_state", "runs")


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    return yaml.safe_load(text.split("---", 2)[1]) or {}


def _copy_rows(src: sqlite3.Connection, dst: sqlite3.Connection, table: str, where: str = "") -> int:
    rows = src.execute(f"SELECT * FROM {table} {where}").fetchall()
    if not rows:
        return 0
    cols = [d[0] for d in src.execute(f"SELECT * FROM {table} LIMIT 0").description]
    dst.executemany(f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
                    [tuple(r) for r in rows])
    return len(rows)


def rebuild(ws, router, force: bool = False) -> dict:
    """Recreate the database from okf/ and library/ into a new file, and swap it in only if nothing was lost.

    Sources are re-read from their originals; claims and links come back from the claim register (not the
    model); the audit log, review queue, data tables, feed state and failed or quarantined source records are
    carried over from the old database when it exists.
    """
    old_path = ws.db_path
    tmp_path = ws.data / "commons.rebuild.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(tmp_path) + suffix).unlink(missing_ok=True)
    before, old = None, None
    if old_path.exists():
        st = Store(old_path)
        export_claims_register(ws, st)
        before = st.counts()
        st.close()
        old = sqlite3.connect(old_path)

    new = Store(tmp_path)
    router.store = new
    skipped: list[str] = []
    try:
        from .thesis import sync_propositions
        sync_propositions(ws, new)
        if old is not None:
            with new.tx() as c:
                for t in CARRY_TABLES:
                    _copy_rows(old, c, t)
                _copy_rows(old, c, "sources", "WHERE status != 'ingested'")
        notes = list((ws.okf / "sources").glob("*.md")) + list((ws.okf / "restricted" / "sources").glob("*.md"))
        slug_map = {}
        for note in sorted(notes):
            fm = _frontmatter(note)
            if fm.get("status") != "ingested":
                continue
            orig = ws.root / (fm.get("original") or "")
            if not fm.get("original") or not orig.exists():
                skipped.append(f"{note.name}: original file missing ({fm.get('original')})")
                continue
            meta = {k: fm.get(k) for k in ("title", "authors", "year", "venue", "doi", "url", "kind")}
            meta["published_at"] = fm.get("published")
            res = ingest_file(ws, new, router, orig, tier=fm.get("tier"), meta=meta, extract_claims=False,
                              min_chars=150, source_id=fm.get("id"))
            if res.status not in ("ingested", "duplicate") or not res.source_id:
                skipped.append(f"{note.name}: {res.status} ({res.message})")
                continue
            with new.tx() as c:
                c.execute("UPDATE sources SET slug=? WHERE id=?", (fm["slug"], res.source_id))
            slug_map[fm["slug"]] = res.source_id
        restored = 0
        for reg in (ws.okf / "claims" / "claims.jsonl", ws.okf / "restricted" / "claims.jsonl"):
            if not reg.exists():
                continue
            for line in reg.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                sid = slug_map.get(r["slug"])
                if sid is None:
                    continue
                with new.tx() as c:
                    c.execute(
                        "INSERT INTO claims (id, source_id, claim, quote, page, claim_type, quote_verified, "
                        "verifier_verdict, status, provenance, strength, tier) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (r["id"], sid, r["claim"], r["quote"], r["page"], r["claim_type"], int(bool(r["quote_verified"])),
                         r["verifier_verdict"], r["status"], r.get("provenance"), r.get("strength"), r["tier"]))
                    for ln in r.get("links", []):
                        c.execute("INSERT OR IGNORE INTO evidence_links (claim_id, proposition_code, stance, "
                                  "proposed_by, confirmed) VALUES (?,?,?,?,?)",
                                  (r["id"], ln["p"], ln["stance"], "rebuild", int(ln["confirmed"])))
                restored += 1
        after = new.counts()
        lost = before and any(after[k] < before[k] for k in ("sources", "claims_verified", "review_open"))
        if (skipped or lost) and not force:
            raise RuntimeError("rebuild would lose data; the existing database was left untouched.\n"
                               + "\n".join(skipped) + (f"\nbefore {before}\nafter {after}" if lost else ""))
    except Exception:
        new.close()
        if old is not None:
            old.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(tmp_path) + suffix).unlink(missing_ok=True)
        raise
    new.close()
    if old is not None:
        old.close()
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(old_path) + suffix)
            if p.exists():
                p.rename(Path(str(old_path) + f".{stamp}.bak{suffix}"))
    os.replace(tmp_path, old_path)
    for suffix in ("-wal", "-shm"):
        Path(str(tmp_path) + suffix).unlink(missing_ok=True)
    final = Store(old_path)
    router.store = final
    for sid in slug_map.values():
        write_source_note(ws, final, sid)
    write_index(ws, final)
    after = final.counts()
    final.close()
    return {"before": before, "after": after, "claims_restored": restored, "skipped": skipped}


def _scrub_restricted(db: Path) -> None:
    """Remove every RESTRICTED row from a database copy and vacuum, so no free page still holds the text."""
    c = sqlite3.connect(db, isolation_level=None)
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA secure_delete=ON")
    c.execute("DELETE FROM review_items WHERE tier='RESTRICTED'")
    c.execute("DELETE FROM sources WHERE tier='RESTRICTED'")
    c.execute("DELETE FROM chunks WHERE tier='RESTRICTED'")
    c.execute("DELETE FROM claims WHERE tier='RESTRICTED'")
    c.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    c.execute("VACUUM")
    c.execute("PRAGMA journal_mode=DELETE")
    c.close()


def backup(ws, store, include_restricted_to: Path | None = None, keep: int = 14) -> Path:
    dest_dir = ws.root.parent / f"{ws.root.name}-backups"
    dest_dir.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    snap = ws.data / f"snapshot-{stamp}.db"
    dst = sqlite3.connect(snap)
    try:
        store.conn.backup(dst)
    finally:
        dst.close()  # Windows will not delete a file that is still open
    _scrub_restricted(snap)
    out = dest_dir / f"commons-{stamp}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for top in ("okf", "library", "analyses"):
            base = ws.root / top
            for p in base.rglob("*") if base.exists() else []:
                rel = p.relative_to(ws.root)
                if p.is_file() and "restricted" not in rel.parts:
                    z.write(p, rel)
        for f in ("commons.yaml", "thesis.yaml", "sources.yaml"):
            if (ws.root / f).exists():
                z.write(ws.root / f, f)
        z.write(snap, "data/commons.db")
    snap.unlink(missing_ok=True)
    if include_restricted_to:
        rdir = Path(include_restricted_to).expanduser()
        rdir.mkdir(parents=True, exist_ok=True)
        rout = rdir / f"commons-restricted-{stamp}.zip"
        with zipfile.ZipFile(rout, "w", zipfile.ZIP_DEFLATED) as z:
            for base in (ws.okf / "restricted", ws.library_dir("RESTRICTED")):
                for p in base.rglob("*"):
                    if p.is_file():
                        z.write(p, p.relative_to(ws.root))
    for old in sorted(dest_dir.glob("commons-2*.zip"))[:-keep]:
        old.unlink()
    return out


def purge(ws, store, source_id: int) -> str:
    s = store.one("SELECT * FROM sources WHERE id=?", (source_id,))
    if s is None:
        raise KeyError(source_id)
    for rel in (s["path_original"], s["path_text"]):
        if rel:
            (ws.root / rel).unlink(missing_ok=True)
    for base in (ws.okf / "sources", ws.okf / "restricted" / "sources"):
        (base / f"{s['slug']}.md").unlink(missing_ok=True)
    claim_ids = [r[0] for r in store.q("SELECT id FROM claims WHERE source_id=?", (source_id,))]
    with store.tx() as c:
        if claim_ids:
            marks = ",".join("?" for _ in claim_ids)
            c.execute(f"DELETE FROM review_items WHERE kind='claim' AND ref_id IN ({marks})", claim_ids)
        c.execute("DELETE FROM review_items WHERE kind IN ('quarantine','extraction_failed') AND ref_id=?",
                  (source_id,))
        c.execute("DELETE FROM sources WHERE id=?", (source_id,))
    store.conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    store.conn.commit()
    store.conn.execute("VACUUM")
    export_claims_register(ws, store)
    append_log(ws, f"PURGED source {source_id} ({s['tier']})")
    return s["slug"]
