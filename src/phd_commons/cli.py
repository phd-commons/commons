"""The `commons` command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from . import __version__

app = typer.Typer(help="Commons: a local-first research system for doctoral students. Bring your own LLM.",
                  no_args_is_help=True, add_completion=False)
schedule_app = typer.Typer(help="Install or remove the daily schedule and the always-on portal.")
review_app = typer.Typer(help="Work through the review queue from the terminal.")
app.add_typer(schedule_app, name="schedule")
app.add_typer(review_app, name="review")

WS_OPT = typer.Option(None, "--workspace", "-w", help="Workspace folder (default: current folder or COMMONS_HOME)")


def _ctx(ws_path):
    from .config import load_workspace
    from .llm import Router
    from .store import open_store
    ws = load_workspace(ws_path)
    store = open_store(ws)
    return ws, store, Router(ws, store)


@app.command()
def version():
    """Print the version."""
    typer.echo(__version__)


@app.command()
def init(folder: Path = typer.Argument(..., help="Where to create the workspace, e.g. ~/Commons"),
         preset: str = typer.Option("demo", help="demo | ollama | lmstudio | mlx | hosted | anthropic"),
         title: str = typer.Option("", help="Thesis working title"),
         candidate: str = typer.Option("", help="Your name"),
         institution: str = typer.Option(""), field: str = typer.Option("", help="Discipline"),
         force: bool = typer.Option(False, help="Rewrite commons.yaml in an existing workspace")):
    """Create a workspace for one thesis."""
    from .workspace import init_workspace
    root, notes = init_workspace(folder, preset, title, candidate, institution, field, force)
    typer.echo(f"Workspace ready at {root}")
    for n in notes:
        typer.echo(n)
    typer.echo("Next: cd into it, put your proposal in inbox/, and run `commons doctor`. "
               "With a coding agent, ask it to run the commons-setup skill.")


@app.command()
def doctor(workspace: Optional[Path] = WS_OPT, no_ping: bool = typer.Option(False, help="Skip model calls")):
    """Check models, corpus, schedule and safety. Exits non-zero on any RED."""
    from .doctor import run_doctor, summary_level
    ws, store, router = _ctx(workspace)
    checks = run_doctor(ws, store, router, ping=not no_ping)
    for c in checks:
        typer.echo(f"{c.level:<6} {c.name:<24} {c.detail}" + (f"\n{'':31}fix: {c.fix}" if c.fix else ""))
    level = summary_level(checks)
    typer.echo(f"\nOverall: {level}")
    raise typer.Exit(1 if level == "RED" else 0)


@app.command()
def ingest(paths: list[Path], workspace: Optional[Path] = WS_OPT,
           tier: Optional[str] = typer.Option(None, help="PUBLIC | PRIVATE | RESTRICTED (default: PRIVATE, or "
                                                         "RESTRICTED for audio and inbox/restricted)"),
           title: Optional[str] = None, year: Optional[int] = None, doi: Optional[str] = None,
           url: Optional[str] = None, no_claims: bool = typer.Option(False, help="Skip claim extraction")):
    """Ingest files or folders."""
    from .ingest import ingest_file
    ws, store, router = _ctx(workspace)
    files = []
    for p in paths:
        files += [f for f in p.rglob("*") if f.is_file()] if p.is_dir() else [p]
    for f in files:
        meta = {k: v for k, v in (("title", title), ("year", year), ("doi", doi), ("url", url)) if v}
        r = ingest_file(ws, store, router, f, tier=tier, meta=meta, extract_claims=not no_claims)
        typer.echo(f"{r.status:<11} {f.name}  {r.message}  ({r.chunks} chunks)")


@app.command()
def inbox(workspace: Optional[Path] = WS_OPT):
    """Process everything waiting in inbox/ once."""
    from .ingest import ingest_inbox
    ws, store, router = _ctx(workspace)
    for r in ingest_inbox(ws, store, router):
        typer.echo(f"{r.status:<11} {r.slug or ''}  {r.message}")


@app.command()
def ask(question: str, workspace: Optional[Path] = WS_OPT,
        mode: str = typer.Option("answer", help="answer | devil | compare | notes"),
        export: Optional[str] = typer.Option(None, help="docx | xlsx"),
        show_passages: bool = typer.Option(False, "--passages")):
    """Ask a question of the corpus. Answers cite their passages or say the corpus does not hold it."""
    from .ask import ask as do_ask
    from .export import answer_report, answer_workbook
    ws, store, router = _ctx(workspace)
    a = do_ask(ws, store, router, question, mode=mode)
    typer.echo(a.text + "\n")
    for i, p in enumerate(a.passages, 1):
        if i in a.cited_numbers() or show_passages:
            pg = f", p. {p['page_from']}" if p.get("page_from") else ""
            typer.echo(f"[{i}] {p['title']} ({p.get('year') or 'n.d.'}{pg}) {p['tier']}")
            if show_passages:
                typer.echo("    " + p["text"][:400].replace("\n", " ") + "\n")
    if a.problems:
        typer.echo("\nChecks that did not pass:\n- " + "\n- ".join(a.problems))
    if export == "docx":
        typer.echo(f"\nWord report: {answer_report(ws, store, a)}")
    elif export == "xlsx":
        typer.echo(f"\nWorkbook: {answer_workbook(ws, store, a)}")


@app.command()
def sweep(workspace: Optional[Path] = WS_OPT, feed: Optional[str] = typer.Option(None, help="Run one feed only"),
          digest_after: bool = typer.Option(True, "--digest/--no-digest")):
    """Run the research sweep now (normally scheduled daily)."""
    from .sweep import run_sweep, write_digest
    ws, store, router = _ctx(workspace)
    rep = run_sweep(ws, store, router, only=feed)
    typer.echo(f"kept {len(rep['kept'])}, screened out {len(rep['rejected'])}, failed feeds {len(rep['failed_feeds'])}")
    for f in rep["failed_feeds"]:
        typer.echo(f"  feed {f['feed']}: {f['error']}")
    if digest_after:
        typer.echo(f"digest: {write_digest(ws, store)}")


@app.command()
def digest(workspace: Optional[Path] = WS_OPT, date: Optional[str] = None):
    """Write the digest for today (or a date) from the last sweep."""
    from .sweep import write_digest
    ws, store, _ = _ctx(workspace)
    typer.echo(str(write_digest(ws, store, date)))


@app.command()
def thesis(workspace: Optional[Path] = WS_OPT):
    """Show the evidence board."""
    from .thesis import board, sync_propositions
    ws, store, _ = _ctx(workspace)
    sync_propositions(ws, store)
    for r in board(store):
        typer.echo(f"{r['code']:<6} for {r['supports']:>3}  against {r['contradicts']:>3}  qualifies {r['qualifies']:>3}"
                   f"  [{r['status']}]  {r['title'] or r['statement'][:70]}")


@app.command()
def analysis(code: Optional[str] = typer.Argument(None, help="Module to run; omit to list"),
             workspace: Optional[Path] = WS_OPT):
    """List or run analysis modules (built-ins plus analyses/<code>/run.py in the workspace)."""
    from .analysis import list_modules, run_module
    ws, store, router = _ctx(workspace)
    if not code:
        for m in list_modules(ws):
            typer.echo(m)
        return
    typer.echo(json.dumps(run_module(ws, store, router, code), indent=2))


@app.command()
def models(workspace: Optional[Path] = WS_OPT):
    """Show which model serves each role, and where it runs."""
    from .config import load_workspace
    from .llm import Router
    ws = load_workspace(workspace)
    for r in Router(ws).describe():
        fb = f"  fallback: {r['fallback']}" if r["fallback"] else ""
        typer.echo(f"{r['role']:<9} {r['model']:<45} {r['provider']} ({r['kind']}, {r['locality']}){fb}")


@app.command()
def serve(workspace: Optional[Path] = WS_OPT, port: Optional[int] = None):
    """Run the portal on 127.0.0.1."""
    import uvicorn
    from .config import load_workspace
    from .portal.app import create_app
    ws = load_workspace(workspace)
    host = ws.get("portal.host", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise typer.BadParameter("portal.host must be a loopback address")
    uvicorn.run(create_app(str(ws.root)), host=host, port=port or ws.get("portal.port", 8700), log_level="warning")


mcp_app = typer.Typer(help="Use your corpus from Claude or any other MCP client.", invoke_without_command=True)
app.add_typer(mcp_app, name="mcp")


@mcp_app.callback()
def mcp(ctx: typer.Context, workspace: Optional[Path] = WS_OPT):
    """Run the MCP server on stdio. Clients launch this; use `commons mcp install` to register it."""
    if ctx.invoked_subcommand is None:
        from .mcp_server import main
        main(str(workspace) if workspace else None)


@mcp_app.command("install")
def mcp_install(client: str = typer.Argument("print", help="claude-desktop | claude-code | print"),
                workspace: Optional[Path] = WS_OPT):
    """Register this workspace's MCP server with Claude Desktop or Claude Code, or print the entry for any client."""
    from . import mcp_install as mi
    from .config import load_workspace
    ws = load_workspace(workspace)
    if client == "claude-desktop":
        typer.echo(mi.install_claude_desktop(ws))
    elif client == "claude-code":
        typer.echo(mi.install_claude_code(ws))
    elif client == "print":
        typer.echo("Add this to your MCP client's configuration:\n" + mi.snippet(ws))
        typer.echo("\nClaude Code: " + mi.manual_claude_code(ws))
    else:
        raise typer.BadParameter("choose claude-desktop, claude-code or print")
    typer.echo("The server serves PUBLIC material only unless you set mcp.private: true in commons.yaml. "
               "Interview and other RESTRICTED material is never served.")


@app.command()
def rebuild(workspace: Optional[Path] = WS_OPT,
            force: bool = typer.Option(False, help="Swap in the rebuilt database even if sources were skipped")):
    """Recreate the database from okf/ and library/ into a new file; swapped in only if nothing is lost."""
    from .maintenance import rebuild as do_rebuild
    ws, store, router = _ctx(workspace)
    store.close()
    try:
        typer.echo(json.dumps(do_rebuild(ws, router, force=force), indent=2))
    except RuntimeError as e:
        typer.echo(str(e))
        raise typer.Exit(1)


@app.command()
def claims(source_id: Optional[int] = typer.Argument(None, help="Source to (re)extract; omit for every source "
                                                                 "with no claims"),
           workspace: Optional[Path] = WS_OPT):
    """Run claim extraction again, for one source or for every ingested source that has none."""
    from .claims import process_source_claims
    from .okf import write_source_note
    ws, store, router = _ctx(workspace)
    ids = [source_id] if source_id else [r[0] for r in store.q(
        "SELECT id FROM sources WHERE status='ingested' AND id NOT IN (SELECT DISTINCT source_id FROM claims)")]
    for sid in ids:
        st = process_source_claims(ws, store, router, sid)
        write_source_note(ws, store, sid)
        typer.echo(f"source {sid}: {st}")


@app.command()
def backup(workspace: Optional[Path] = WS_OPT,
           restricted_to: Optional[Path] = typer.Option(None, help="Also copy RESTRICTED material to this "
                                                                     "(encrypted) location")):
    """Snapshot okf/, library/, config and the database next to the workspace."""
    from .maintenance import backup as do_backup
    ws, store, _ = _ctx(workspace)
    typer.echo(str(do_backup(ws, store, restricted_to)))
    if not restricted_to:
        typer.echo("RESTRICTED material was not included. Use --restricted-to <encrypted volume> to copy it.")


@app.command()
def purge(source_id: int, workspace: Optional[Path] = WS_OPT):
    """Permanently delete one source and everything derived from it (for ethics-required destruction)."""
    from .maintenance import purge as do_purge
    ws, store, _ = _ctx(workspace)
    s = store.one("SELECT slug FROM sources WHERE id=?", (source_id,))
    if s is None:
        raise typer.BadParameter("no such source")
    typed = typer.prompt(f"Type the slug to permanently delete it ({s['slug']})")
    if typed != s["slug"]:
        raise typer.Abort()
    typer.echo(f"purged {do_purge(ws, store, source_id)}. Older backups still hold it; delete those too if required.")


@review_app.command("list")
def review_list(workspace: Optional[Path] = WS_OPT):
    """List open review items."""
    ws, store, _ = _ctx(workspace)
    for r in store.q("SELECT * FROM review_items WHERE resolved_at IS NULL ORDER BY id"):
        typer.echo(f"{r['id']:>5} {r['kind']:<16} {r['payload_json'][:120]}")


@review_app.command("resolve")
def review_resolve(item_id: int, decision: str = typer.Argument(..., help="accept | reject"),
                   workspace: Optional[Path] = WS_OPT):
    from .claims import resolve_review
    ws, store, _ = _ctx(workspace)
    resolve_review(store, item_id, decision)
    typer.echo("done")


@schedule_app.command("install")
def schedule_install(workspace: Optional[Path] = WS_OPT, dry_run: bool = False):
    """Daily sweep, digest and backup, plus the portal kept running. No admin rights needed."""
    from .config import load_workspace
    from .schedule import install
    for line in install(load_workspace(workspace), dry_run=dry_run):
        typer.echo(line)


@schedule_app.command("remove")
def schedule_remove(workspace: Optional[Path] = WS_OPT):
    from .config import load_workspace
    from .schedule import uninstall
    for line in uninstall(load_workspace(workspace)):
        typer.echo(f"removed {line}")


if __name__ == "__main__":
    app()
