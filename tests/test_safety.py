"""Tier enforcement: what may reach which model, and what the MCP server and portal may show."""

from __future__ import annotations

import pytest

from phd_commons.ask import ask, caller_tiers
from phd_commons.ingest import ingest_file
from phd_commons.llm import Router, TierViolation, host_is_local


def _cloud_author(ws, public=True, fallback=False):
    ws.cfg["providers"]["cloudy"] = {"kind": "fake", "locality": "cloud"}
    ws.cfg["roles"]["author"] = {"provider": "cloudy", "model": "x"}
    if fallback:
        ws.cfg["roles"]["author"]["local_fallback"] = {"provider": "fake", "model": "local-small"}
    ws.cfg["cloud"] = {"public": public, "private": False}
    return Router(ws)


def test_cloud_never_gets_restricted(ws):
    r = _cloud_author(ws, public=True)
    assert r.resolve("author", "PUBLIC").provider_name == "cloudy"
    with pytest.raises(TierViolation):
        r.resolve("author", "PRIVATE")
    with pytest.raises(TierViolation):
        r.resolve("author", "RESTRICTED")


def test_cloud_public_off_by_default(ws):
    r = _cloud_author(ws, public=False)
    with pytest.raises(TierViolation):
        r.resolve("author", "PUBLIC")


def test_local_fallback_takes_sensitive_material(ws):
    r = _cloud_author(ws, public=True, fallback=True)
    assert r.resolve("author", "PUBLIC").provider_name == "cloudy"
    assert r.resolve("author", "RESTRICTED").model == "local-small"


def test_institutional_needs_named_approval(ws):
    ws.cfg["providers"]["uni"] = {"kind": "fake", "locality": "institutional"}
    ws.cfg["roles"]["author"] = {"provider": "uni", "model": "x"}
    with pytest.raises(TierViolation):
        Router(ws).resolve("author", "RESTRICTED")
    ws.cfg["providers"]["uni"]["restricted_approval"] = "HREC 2026-123"
    assert Router(ws).resolve("author", "RESTRICTED").provider_name == "uni"


def test_ask_drops_tiers_the_author_cannot_see(ctx, docs):
    ws, store, _ = ctx
    from conftest import make_pdf, DOC_A
    p = make_pdf(docs["a"].parent / "interview.pdf", DOC_A.replace("synthetic test document", "interview P01"))
    r_local = Router(ws, store)
    ingest_file(ws, store, r_local, p, tier="RESTRICTED", meta={"title": "Interview P01"})
    router = _cloud_author(ws, public=True)
    router.store = store
    a = ask(ws, store, router, "emergency admissions hot days")
    assert all(x["tier"] != "RESTRICTED" for x in a.passages)
    assert any("RESTRICTED material excluded" in pr for pr in a.problems)


def test_mcp_tiers(ws):
    assert caller_tiers(ws, "mcp") == {"PUBLIC"}
    ws.cfg["mcp"]["private"] = True
    assert caller_tiers(ws, "mcp") == {"PUBLIC", "PRIVATE"}


def test_mislabelled_local_provider_is_flagged(ctx):
    ws, store, _ = ctx
    from phd_commons.doctor import run_doctor
    ws.cfg["providers"]["sneaky"] = {"kind": "openai", "base_url": "https://api.example.com/v1", "locality": "local"}
    ws.cfg["roles"]["worker"] = {"provider": "sneaky", "model": "m"}
    checks = run_doctor(ws, store, ping=False)
    assert any(c.level == "RED" and "sneaky" in c.name for c in checks)
    assert host_is_local("http://127.0.0.1:11434/v1") and host_is_local("http://192.168.1.5:8000")
    assert not host_is_local("https://api.example.com")


def test_embedding_spaces_never_mix(ctx, docs):
    ws, store, router = ctx
    ingest_file(ws, store, router, docs["a"], tier="PUBLIC")
    ws.cfg["roles"]["embed"] = {"provider": "fake", "model": "another-embedder"}
    with pytest.raises(RuntimeError, match="mix embedding spaces"):
        ingest_file(ws, store, Router(ws, store), docs["b"], tier="PUBLIC")


def test_restricted_refused_in_sync_folder(tmp_path, monkeypatch):
    from phd_commons.config import load_workspace
    from phd_commons.workspace import init_workspace
    from phd_commons.ingest import ingest_file as ing
    monkeypatch.delenv("COMMONS_ALLOW_RESTRICTED_UNENCRYPTED", raising=False)
    root, notes = init_workspace(tmp_path / "Dropbox" / "ws", preset="demo")
    assert any("synced" in n for n in notes)
    w = load_workspace(root)
    from phd_commons.store import open_store
    s = open_store(w)
    f = tmp_path / "t.md"
    f.write_text("interview text " * 100)
    assert ing(w, s, Router(w, s), f, tier="RESTRICTED").status == "refused"
