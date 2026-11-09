"""Regression tests for the pre-release review findings."""

from __future__ import annotations

import os
import shutil
import sqlite3
import zipfile

import pytest

from phd_commons.ingest import ingest_file, ingest_inbox
from phd_commons.llm import Router, TierViolation


def _restricted_doc(tmp_path):
    from conftest import DOC_A, make_pdf
    return make_pdf(tmp_path / "interview-jane-citizen.pdf", DOC_A.replace("synthetic test document",
                                                                           "interview with Jane Citizen"))


def test_backup_holds_no_restricted_text(ctx, docs, tmp_path):
    ws, store, router = ctx
    from phd_commons.maintenance import backup
    ingest_file(ws, store, router, docs["a"], tier="PUBLIC")
    ingest_file(ws, store, router, _restricted_doc(tmp_path), tier="RESTRICTED", meta={"title": "Interview"})
    out = backup(ws, store)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        z.extract("data/commons.db", tmp_path / "x")
        blob = b"".join(z.read(n) for n in names)
    assert b"Jane Citizen" not in blob
    db = sqlite3.connect(tmp_path / "x" / "data" / "commons.db")
    assert db.execute("SELECT COUNT(*) FROM sources WHERE tier='RESTRICTED'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM sources WHERE tier='PUBLIC'").fetchone()[0] == 1
    assert b"Jane Citizen" not in (tmp_path / "x" / "data" / "commons.db").read_bytes()


def test_restricted_text_stays_in_restricted_folder(ctx, tmp_path):
    ws, store, router = ctx
    ingest_file(ws, store, router, _restricted_doc(tmp_path), tier="RESTRICTED")
    assert not any((ws.data / "text").glob("*.txt")) if (ws.data / "text").exists() else True
    assert any((ws.okf / "restricted" / "text").glob("*.txt"))
    assert "jane" not in (ws.okf / "log.md").read_text().lower()


def test_mislabelled_local_providers_are_treated_as_cloud(ws):
    ws.cfg["providers"]["ant"] = {"kind": "anthropic", "locality": "local"}
    ws.cfg["providers"]["far"] = {"kind": "openai", "base_url": "https://api.openai.com/v1", "locality": "local"}
    ws.cfg["roles"]["verifier"] = {"provider": "ant", "model": "x",
                                   "local_fallback": {"provider": "far", "model": "y"}}
    with pytest.raises(TierViolation):
        Router(ws).resolve("verifier", "RESTRICTED")


def test_tier_floor_beats_sidecar_and_symlink(ctx, tmp_path):
    ws, store, router = ctx
    src = _restricted_doc(tmp_path)
    shutil.copy(src, ws.inbox / "restricted" / "a.pdf")
    (ws.inbox / "restricted" / "a.pdf.json").write_text('{"tier": "PUBLIC"}')
    res = ingest_inbox(ws, store, router)
    assert res[0].status == "ingested"
    assert store.scalar("SELECT tier FROM sources WHERE id=?", (res[0].source_id,)) == "RESTRICTED"
    target = tmp_path / "outside.pdf"
    shutil.copy(src, target)
    link = ws.inbox / "restricted" / "b.pdf"
    try:
        os.symlink(target, link)
    except OSError:  # Windows without symlink rights
        link = None
    if link:
        assert ingest_file(ws, store, router, link).status == "refused"
    assert ingest_file(ws, store, router, src, tier="secret").status == "refused"


def test_rebuild_without_thesis_keeps_the_database(ctx, docs):
    ws, store, router = ctx
    from phd_commons.maintenance import rebuild
    ingest_file(ws, store, router, docs["a"], tier="PUBLIC")
    calls_before = store.scalar("SELECT COUNT(*) FROM model_calls")
    reviews_before = store.scalar("SELECT COUNT(*) FROM review_items")
    store.close()
    ws.thesis_path().unlink()
    res = rebuild(ws, Router(ws))
    from phd_commons.store import open_store
    s2 = open_store(ws)
    assert res["after"]["sources"] == 1 and res["after"]["claims_verified"] >= 1
    assert s2.scalar("SELECT COUNT(*) FROM model_calls") >= calls_before
    assert s2.scalar("SELECT COUNT(*) FROM review_items") == reviews_before


def test_rebuild_refuses_to_lose_sources(ctx, docs):
    ws, store, router = ctx
    from phd_commons.maintenance import rebuild
    r = ingest_file(ws, store, router, docs["a"], tier="PUBLIC")
    (ws.root / store.one("SELECT path_original FROM sources WHERE id=?", (r.source_id,))[0]).unlink()
    store.close()
    with pytest.raises(RuntimeError, match="left untouched"):
        rebuild(ws, Router(ws))
    from phd_commons.store import open_store
    assert open_store(ws).counts()["sources"] == 1


def test_purge_removes_everything(ctx, tmp_path):
    ws, store, router = ctx
    from phd_commons.maintenance import purge
    r = ingest_file(ws, store, router, _restricted_doc(tmp_path), tier="RESTRICTED")
    store.add_review("claim", store.scalar("SELECT id FROM claims WHERE source_id=?", (r.source_id,)),
                     {"quote": "Jane Citizen"}, tier="RESTRICTED")
    purge(ws, store, r.source_id)
    assert store.scalar("SELECT COUNT(*) FROM review_items WHERE payload_json LIKE '%Jane%'") == 0
    assert store.scalar("SELECT COUNT(*) FROM chunks") == 0
    assert not any((ws.okf / "restricted" / "text").glob("*.txt"))


def test_quarantine_never_overwrites(ctx, tmp_path):
    ws, store, router = ctx
    from conftest import DOC_MARKED, make_pdf
    (tmp_path / "d1").mkdir()
    (tmp_path / "d2").mkdir()
    a = make_pdf(tmp_path / "d1" / "report.pdf", DOC_MARKED)
    b = make_pdf(tmp_path / "d2" / "report.pdf", DOC_MARKED + " two")
    ingest_file(ws, store, router, a)
    ingest_file(ws, store, router, b)
    assert len(list(ws.quarantine.glob("*report.pdf"))) == 2


def test_propositions_not_served_over_mcp_by_default(ctx):
    ws, store, router = ctx
    import asyncio
    from phd_commons.mcp_server import build_server
    m = build_server(str(ws.root))
    out = asyncio.run(m.call_tool("list_propositions", {}))
    assert "not served" in str(out)


def test_thesis_entries_without_code_or_statement(ctx, docs):
    ws, store, router = ctx
    ws.thesis_path().write_text("propositions:\n  - title: no code\n  - code: P9\n    statement:\n")
    r = ingest_file(ws, store, router, docs["a"], tier="PUBLIC")
    assert r.status == "ingested"
    assert store.scalar("SELECT COUNT(*) FROM propositions") == 1


def test_retry_after_failure_is_not_a_duplicate(ctx, tmp_path):
    ws, store, router = ctx
    p = tmp_path / "thin.md"
    p.write_text("too short")
    assert ingest_file(ws, store, router, p).status == "failed"
    assert ingest_file(ws, store, router, p).status == "failed"
    assert store.scalar("SELECT COUNT(*) FROM sources") == 1


def test_unknown_encryption_needs_confirmation(ws, monkeypatch, tmp_path):
    from phd_commons import safety
    monkeypatch.delenv("COMMONS_ALLOW_RESTRICTED_UNENCRYPTED", raising=False)
    monkeypatch.setattr(safety, "disk_encryption", lambda: "unknown")
    monkeypatch.setattr(safety, "in_sync_folder", lambda p: None)
    assert "cannot check" in safety.restricted_blocked_reason(ws)
    ws.cfg["restricted"] = {"encryption_confirmed": True}
    assert safety.restricted_blocked_reason(ws) is None


def test_single_object_json_replies_are_kept():
    """Found live: in JSON mode a Qwen worker returned one link object, not an array, and it was dropped."""
    from phd_commons.claims import _as_list
    one = {"code": "P4", "stance": "supports", "reason": "r"}
    assert _as_list(one, "links") == [one]
    assert _as_list({"links": [one]}, "links") == [one]
    assert _as_list({"links": None}, "links") == []
    assert _as_list([one], "links") == [one]
    assert _as_list("x", "links") == []
