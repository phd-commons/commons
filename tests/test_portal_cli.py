"""Portal pages render; the CLI runs; schedules generate; the inbox flow works."""

from __future__ import annotations

import shutil

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from phd_commons.cli import app as cli


def test_portal_pages(ctx, docs):
    ws, store, router = ctx
    from phd_commons.ingest import ingest_file
    from phd_commons.portal.app import create_app
    r = ingest_file(ws, store, router, docs["a"], tier="PUBLIC", meta={"title": "Heat and admissions"})
    client = TestClient(create_app(str(ws.root), background=False), base_url="http://127.0.0.1")
    for path in ("/", "/ask", "/library", "/thesis", "/thesis/P1", "/review", "/doctor", f"/source/{r.source_id}",
                 "/health", "/library?status=failed"):
        assert client.get(path).status_code == 200, path
    resp = client.post("/ask", data={"question": "Do admissions rise on hot days?", "mode": "answer"})
    assert resp.status_code == 200 and "Passages" in resp.text
    aid = resp.text.split("/export/")[1].split("/")[0]
    assert client.get(f"/export/{aid}/docx").status_code == 200
    up = client.post("/library/upload", files={"file": ("note.md", b"# Note\n\n" + b"my own note text " * 60)},
                     data={"tier": "PRIVATE"}, follow_redirects=False)
    assert up.status_code == 303 and (ws.inbox / "note.md").exists()


def test_inbox_flow(ctx, docs):
    ws, store, router = ctx
    from phd_commons.ingest import ingest_inbox
    shutil.copy(docs["b"], ws.inbox / "warnings.docx")
    (ws.inbox / "notes.xyz").write_text("not a supported type")
    res = ingest_inbox(ws, store, router)
    assert any(r.status == "ingested" for r in res)
    assert not (ws.inbox / "warnings.docx").exists()
    assert any(p.name.endswith("-notes.xyz") for p in ws.quarantine.iterdir())


def test_cli(ws, docs, monkeypatch):
    runner = CliRunner()
    monkeypatch.setenv("COMMONS_HOME", str(ws.root))
    assert runner.invoke(cli, ["ingest", str(docs["a"]), "--tier", "PUBLIC"]).exit_code == 0
    out = runner.invoke(cli, ["ask", "Do admissions rise on hot days?"])
    assert out.exit_code == 0 and "[1]" in out.output
    assert runner.invoke(cli, ["thesis"]).exit_code == 0
    assert runner.invoke(cli, ["models"]).exit_code == 0
    assert runner.invoke(cli, ["analysis", "evidence_balance"]).exit_code == 0
    assert runner.invoke(cli, ["doctor", "--no-ping"]).exit_code == 0
    assert runner.invoke(cli, ["backup"]).exit_code == 0
    assert runner.invoke(cli, ["schedule", "install", "--dry-run"]).exit_code == 0


def test_schedule_plans_for_each_os(ws, monkeypatch):
    import phd_commons.schedule as sch
    for system in ("Darwin", "Linux", "Windows"):
        monkeypatch.setattr(sch.platform, "system", lambda s=system: s)
        files = sch.plan(ws)
        assert files, system
        if system == "Darwin":
            assert any("StartCalendarInterval" in c for _, c in files)
        if system == "Linux":
            assert any(p.suffix == ".timer" for p, _ in files)
        if system == "Windows":
            tasks = [c for _, c in files if c.startswith("schtasks")]
            assert len(tasks) == 4 and any("ONLOGON" in t for t in tasks)


def test_digest_without_network(ctx, docs):
    ws, store, router = ctx
    from phd_commons.ingest import ingest_file
    from phd_commons.sweep import write_digest
    ingest_file(ws, store, router, docs["a"], tier="PUBLIC")
    p = write_digest(ws, store)
    assert p.exists() and "Evidence movement" in p.read_text()


def test_portal_refuses_foreign_hosts_and_origins(ctx):
    ws, _, _ = ctx
    from phd_commons.portal.app import create_app
    app = create_app(str(ws.root), background=False)
    assert TestClient(app, base_url="http://attacker.example").get("/").status_code == 403
    local = TestClient(app, base_url="http://127.0.0.1")
    r = local.post("/library/upload", files={"file": ("x.md", b"x" * 500)}, data={"tier": "PRIVATE"},
                   headers={"Origin": "https://evil.example"}, follow_redirects=False)
    assert r.status_code == 403 and not (ws.inbox / "x.md").exists()
    r = local.post("/library/upload", files={"file": ("..", b"x" * 500)}, data={"tier": "restricted"},
                   headers={"Origin": "http://127.0.0.1:8700"}, follow_redirects=False)
    assert r.status_code == 303 and any((ws.inbox / "restricted").iterdir())


def test_schedule_quotes_paths_with_spaces(tmp_path, monkeypatch):
    import phd_commons.schedule as sch
    from phd_commons.config import load_workspace
    from phd_commons.workspace import init_workspace
    root, _ = init_workspace(tmp_path / "My Thesis", preset="demo")
    monkeypatch.setattr(sch.platform, "system", lambda: "Linux")
    units = [c for p, c in sch.plan(load_workspace(root)) if p.suffix == ".service"]
    assert all('WorkingDirectory="' in u and 'ExecStart="' in u for u in units)


def test_mcp_install_writes_desktop_config(ws, tmp_path):
    import json
    from phd_commons import mcp_install as mi
    cfg = tmp_path / "Claude" / "claude_desktop_config.json"
    cfg.parent.mkdir()
    cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
    mi.install_claude_desktop(ws, cfg)
    data = json.loads(cfg.read_text())
    assert "other" in data["mcpServers"] and data["theme"] == "dark"
    entry = data["mcpServers"][mi.server_name(ws)]
    assert entry["args"][-3:] == ["mcp", "-w", str(ws.root)]
    assert list(cfg.parent.glob("*.bak-*"))
    assert "mcpServers" in mi.snippet(ws)


def test_mcp_tools_over_the_protocol(ctx, docs):
    import asyncio
    from phd_commons.ingest import ingest_file
    from phd_commons.mcp_server import build_server
    ws, store, router = ctx
    ingest_file(ws, store, router, docs["a"], tier="PUBLIC", meta={"title": "Heat and admissions"})
    ingest_file(ws, store, router, docs["b"], tier="PRIVATE", meta={"title": "Private draft"})
    m = build_server(str(ws.root))
    names = {t.name for t in asyncio.run(m.list_tools())}
    assert {"search_corpus", "ask_corpus", "thesis_board", "add_published_work", "corpus_status"} <= names
    out = str(asyncio.run(m.call_tool("ask_corpus", {"question": "Do admissions rise on hot days?"})))
    assert "Heat and admissions" in out and "Private draft" not in out
    assert "not served" in str(asyncio.run(m.call_tool("thesis_board", {})))
    assert "refused" in str(asyncio.run(m.call_tool("add_published_work", {"doi": "not a doi"})))
