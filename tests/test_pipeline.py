"""End-to-end with the fake provider: ingest, claims, links, ask, exports, rebuild, analyses."""

from __future__ import annotations

import zipfile

import pytest

from phd_commons.ask import ask, check_answer
from phd_commons.claims import quote_in_source
from phd_commons.export import answer_report, answer_workbook, register_table
from phd_commons.ingest import ingest_file


def test_ingest_extracts_claims_and_links(ctx, docs):
    ws, store, router = ctx
    r = ingest_file(ws, store, router, docs["a"], tier="PUBLIC", meta={"title": "Heat and admissions", "year": 2024})
    assert r.status == "ingested" and r.chunks >= 1
    claims = store.q("SELECT * FROM claims WHERE source_id=?", (r.source_id,))
    assert claims and all(c["quote_verified"] for c in claims if c["status"] != "rejected")
    assert store.scalar("SELECT COUNT(*) FROM evidence_links") >= 1
    note = (ws.okf / "sources" / f"{r.slug}.md").read_text()
    assert "## Your notes" in note and "Heat and admissions" in note


def test_duplicate_is_idempotent(ctx, docs):
    ws, store, router = ctx
    first = ingest_file(ws, store, router, docs["a"], tier="PUBLIC")
    second = ingest_file(ws, store, router, docs["a"], tier="PUBLIC")
    assert second.status == "duplicate" and second.source_id == first.source_id


def test_marked_document_is_quarantined(ctx, docs):
    ws, store, router = ctx
    r = ingest_file(ws, store, router, docs["marked"], tier="PUBLIC")
    assert r.status == "quarantined"
    assert store.scalar("SELECT COUNT(*) FROM chunks") == 0
    assert store.scalar("SELECT COUNT(*) FROM review_items WHERE kind='quarantine'") == 1


def test_quote_check_is_mechanical():
    src = "Admissions rose by 7 per cent on hot\ndays after adjust-\nment for season."
    assert quote_in_source("Admissions rose by 7 per cent on hot days after adjustment for season", src)
    assert not quote_in_source("Admissions rose by 9 per cent on hot days", src)


def test_ask_cites_and_abstains(ctx, docs):
    ws, store, router = ctx
    ingest_file(ws, store, router, docs["a"], tier="PUBLIC", meta={"title": "Heat and admissions"})
    a = ask(ws, store, router, "Do emergency admissions rise on hot days?")
    assert a.passages and a.cited_numbers() and not a.problems
    empty = ask(ws, store, router, "zzzz qqqq xxxx")
    assert empty.abstained or not empty.passages


def test_answer_check_catches_bad_citations():
    passages = [{"text": "Heat raised admissions by 7 per cent."}]
    assert check_answer("Admissions rose [2].", passages)
    assert check_answer('It said "admissions doubled overnight in every city".', passages)
    assert check_answer("Admissions rose by 7 per cent on hot days in the cities studied.", passages)
    assert not check_answer('It found "Heat raised admissions by 7 per cent" [1].', passages)


def test_exports(ctx, docs):
    ws, store, router = ctx
    ingest_file(ws, store, router, docs["a"], tier="PUBLIC", meta={"title": "Heat and admissions", "year": 2024,
                                                                   "doi": "10.0000/test"})
    register_table(ws, store, "admissions", [{"city": "A", "rr": 1.07}, {"city": "B", "rr": 1.04}], "test", "MEASURED")
    a = ask(ws, store, router, "emergency admissions hot days")
    a.text += "\n\n{{FIG:admissions:bar:Relative risk by city}}"
    p = answer_report(ws, store, a)
    assert p.exists() and zipfile.is_zipfile(p)
    import docx
    d = docx.Document(str(p))
    assert len(d.inline_shapes) == 1
    assert p.with_suffix(".bib").exists() and "10.0000/test" in p.with_suffix(".bib").read_text()
    x = answer_workbook(ws, store, a)
    import openpyxl
    assert "admissions" in openpyxl.load_workbook(x).sheetnames


def test_invented_table_is_an_error(ctx, docs):
    ws, store, router = ctx
    ingest_file(ws, store, router, docs["a"], tier="PUBLIC")
    a = ask(ws, store, router, "emergency admissions")
    a.text += "\n{{FIG:made_up_numbers:bar:Invented}}"
    with pytest.raises(KeyError):
        answer_report(ws, store, a)


def test_rebuild_reproduces_counts(ctx, docs):
    ws, store, router = ctx
    ingest_file(ws, store, router, docs["a"], tier="PUBLIC", meta={"title": "Heat and admissions"})
    ingest_file(ws, store, router, docs["b"], tier="PRIVATE", meta={"title": "Warnings"})
    before = store.counts()
    links_before = store.scalar("SELECT COUNT(*) FROM evidence_links")
    store.close()
    from phd_commons.maintenance import rebuild
    from phd_commons.llm import Router
    res = rebuild(ws, Router(ws))
    after = res["after"]
    for k in ("sources", "chunks", "claims_verified"):
        assert after[k] == before[k], k
    from phd_commons.store import open_store
    assert open_store(ws).scalar("SELECT COUNT(*) FROM evidence_links") == links_before


def test_analyses_and_board(ctx, docs):
    ws, store, router = ctx
    from phd_commons.analysis import list_modules, run_module
    from phd_commons.thesis import board
    ingest_file(ws, store, router, docs["a"], tier="PUBLIC")
    ingest_file(ws, store, router, docs["b"], tier="PUBLIC")
    assert {"evidence_balance", "literature_by_year", "sources_by_kind"} <= set(list_modules(ws))
    stamp = run_module(ws, store, router, "evidence_balance")
    assert stamp["outputs"][0]["table"] == "evidence_balance"
    run_module(ws, store, router, "sources_by_kind")
    rows = board(store)
    assert {r["code"] for r in rows} >= {"P1", "R1"}
    assert sum(r["supports"] + r["contradicts"] for r in rows) >= 1
