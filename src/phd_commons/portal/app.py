"""The local portal. Single user, bound to 127.0.0.1. No business logic here: it calls the core library."""

from __future__ import annotations

import datetime as dt
import json
import threading
import time
import uuid
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from .. import __version__
from ..ask import Answer, ask
from ..claims import confirm_link, resolve_review
from ..config import load_workspace
from ..doctor import run_doctor, summary_level
from ..export import answer_report, answer_workbook
from ..ingest import ingest_inbox
from ..llm import Router
from ..store import open_store
from ..thesis import board, evidence, sync_propositions

TPL = Path(resources.files("phd_commons") / "templates" / "portal")


def _cite(text: str) -> Markup:
    import re
    html = str(escape(text))
    html = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\[(\d+)\]", r'<a class="cite" href="#p\1">[\1]</a>', html)
    paras = [p.strip() for p in html.split("\n\n") if p.strip()]
    return Markup("".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paras))


def _md(text: str) -> Markup:
    """Small, safe Markdown subset for digests: headings, bullets, tables, bold, links."""
    import re
    out, in_list, table = [], False, []

    def inline(s):
        s = str(escape(s))
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        return re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', s)

    def flush_table():
        if table:
            rows = [r for r in table if not re.match(r"^\|?\s*-{2,}", r)]
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
            head = "".join(f"<th>{inline(c)}</th>" for c in cells[0])
            body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in cells[1:])
            out.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
            table.clear()

    for line in text.splitlines():
        if line.startswith("|"):
            table.append(line)
            continue
        flush_table()
        if line.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            lvl = len(m.group(1)) + 1
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    flush_table()
    if in_list:
        out.append("</ul>")
    return Markup("\n".join(out))


def create_app(ws_path: str | None = None, background: bool = True) -> FastAPI:
    ws = load_workspace(ws_path)
    store = open_store(ws)
    router = Router(ws, store)
    sync_propositions(ws, store)
    env = Environment(loader=FileSystemLoader(str(TPL)), autoescape=select_autoescape(["html"]))
    env.filters["cite"] = _cite
    env.filters["md"] = _md
    env.globals.update(version=__version__, project=ws.get("project", {}))
    answers: dict[str, Answer] = {}
    state = {"inbox_last": None, "inbox_msgs": []}
    app = FastAPI(title="Commons", docs_url=None, redoc_url=None)
    allowed_hosts = {"127.0.0.1", "localhost", "[::1]", "::1"} | set(ws.get("portal.extra_hosts", []) or [])

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Block DNS rebinding (foreign Host header) and cross-site form posts (foreign Origin or Referer).
        host = (request.url.hostname or "").strip("[]")
        if host not in {h.strip("[]") for h in allowed_hosts}:
            return HTMLResponse("Commons only answers on this computer (127.0.0.1).", status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            src = request.headers.get("origin") or request.headers.get("referer") or ""
            if src:
                from urllib.parse import urlparse
                if (urlparse(src).hostname or "") not in {h.strip("[]") for h in allowed_hosts}:
                    return HTMLResponse("Cross-site request refused.", status_code=403)
        return await call_next(request)

    def render(name: str, **ctx) -> HTMLResponse:
        ctx.setdefault("review_open", store.scalar("SELECT COUNT(*) FROM review_items WHERE resolved_at IS NULL") or 0)
        return HTMLResponse(env.get_template(name).render(**ctx))

    def inbox_loop():
        while True:
            try:
                res = ingest_inbox(ws, store, router)
                if res:
                    state["inbox_msgs"] = [f"{r.status}: {r.slug or ''} {r.message}" for r in res][-20:]
                state["inbox_last"] = dt.datetime.now().strftime("%H:%M:%S")
            except Exception as e:  # noqa: BLE001
                state["inbox_msgs"] = [f"inbox error: {e}"]
            time.sleep(30)

    if background:
        threading.Thread(target=inbox_loop, daemon=True).start()

    @app.get("/", response_class=HTMLResponse)
    def today():
        digests = sorted((ws.okf / "digests").glob("20*.md"))
        digest = digests[-1].read_text(encoding="utf-8") if digests else ""
        checks = run_doctor(ws, store, router, ping=False)
        return render("today.html", digest=digest, digest_name=digests[-1].stem if digests else None,
                      counts=store.counts(), level=summary_level(checks),
                      ambers=[c for c in checks if c.level != "GREEN"], inbox=state)

    @app.get("/ask", response_class=HTMLResponse)
    def ask_form():
        return render("ask.html", answer=None, aid=None)

    @app.post("/ask", response_class=HTMLResponse)
    def ask_post(question: str = Form(...), mode: str = Form("answer")):
        a = ask(ws, store, router, question, mode=mode)
        aid = uuid.uuid4().hex[:10]
        answers[aid] = a
        return render("ask.html", answer=a, aid=aid)

    @app.get("/export/{aid}/{kind}")
    def export(aid: str, kind: str):
        a = answers.get(aid)
        if a is None:
            raise HTTPException(404, "answer expired; ask again")
        if kind == "docx":
            p = answer_report(ws, store, a)
        elif kind == "xlsx":
            p = answer_workbook(ws, store, a)
        elif kind in ("bib", "ris"):
            p = answer_report(ws, store, a).with_suffix("." + kind)
            if not p.exists():
                raise HTTPException(404, "no cited sources")
        else:
            raise HTTPException(400, "unknown export")
        return FileResponse(p, filename=p.name)

    @app.get("/library", response_class=HTMLResponse)
    def library(status: str = "ingested"):
        rows = store.q("SELECT id, title, year, kind, tier, status, fail_reason, origin_feed FROM sources "
                       "WHERE status=? ORDER BY created_at DESC LIMIT 500", (status,))
        return render("library.html", rows=rows, status=status, inbox=state)

    @app.post("/library/upload")
    async def upload(file: UploadFile = File(...), tier: str = Form("PRIVATE")):
        tier = (tier or "PRIVATE").upper()
        if tier not in ("PUBLIC", "PRIVATE", "RESTRICTED"):
            raise HTTPException(400, "invalid tier")
        name = Path(file.filename or "").name.strip()
        if name in ("", ".", "..") or name.startswith("."):
            name = f"upload-{uuid.uuid4().hex[:8]}"
        data = await file.read()
        limit = int(ws.get("portal.max_upload_mb", 500)) * 1024 * 1024
        if len(data) > limit:
            raise HTTPException(413, "file too large for upload; copy it into inbox/ instead")
        dest = (ws.inbox / "restricted" / name) if tier == "RESTRICTED" else ws.inbox / name
        if dest.exists():
            dest = dest.with_name(f"{dest.stem}-{uuid.uuid4().hex[:6]}{dest.suffix}")
        dest.write_bytes(data)
        if tier == "PUBLIC":
            dest.with_suffix(dest.suffix + ".json").write_text(json.dumps({"tier": "PUBLIC"}))
        return RedirectResponse("/library", status_code=303)

    @app.get("/source/{sid}", response_class=HTMLResponse)
    def source(sid: int):
        s = store.one("SELECT * FROM sources WHERE id=?", (sid,))
        if s is None:
            raise HTTPException(404)
        claims = store.q("SELECT c.*, group_concat(l.proposition_code || ':' || l.stance || ':' || l.confirmed, ';') "
                         "AS links FROM claims c LEFT JOIN evidence_links l ON l.claim_id=c.id WHERE c.source_id=? "
                         "GROUP BY c.id ORDER BY c.page, c.id", (sid,))
        return render("source.html", s=s, claims=claims)

    @app.get("/original/{sid}")
    def original(sid: int):
        s = store.one("SELECT path_original FROM sources WHERE id=?", (sid,))
        if s is None or not s["path_original"]:
            raise HTTPException(404)
        return FileResponse(ws.root / s["path_original"])

    @app.get("/thesis", response_class=HTMLResponse)
    def thesis():
        sync_propositions(ws, store)
        return render("thesis.html", rows=board(store))

    @app.get("/thesis/{code}", response_class=HTMLResponse)
    def proposition(code: str):
        p = store.one("SELECT * FROM propositions WHERE code=?", (code,))
        if p is None:
            raise HTTPException(404)
        return render("proposition.html", p=p, ev=evidence(store, code))

    @app.post("/link/{claim_id}/{code}/{decision}")
    def link(claim_id: int, code: str, decision: str):
        confirm_link(store, claim_id, code, decision)
        return RedirectResponse(f"/thesis/{code}", status_code=303)

    @app.get("/review", response_class=HTMLResponse)
    def review():
        items = store.q("SELECT * FROM review_items WHERE resolved_at IS NULL ORDER BY id LIMIT 200")
        parsed = [{**dict(i), "payload": json.loads(i["payload_json"] or "{}")} for i in items]
        links = store.q("SELECT l.*, c.quote, c.claim, s.title FROM evidence_links l JOIN claims c ON c.id=l.claim_id "
                        "JOIN sources s ON s.id=c.source_id WHERE l.confirmed=0 AND c.status IN ('verified','confirmed') "
                        "ORDER BY c.id DESC LIMIT 100")
        return render("review.html", items=parsed, links=links)

    @app.post("/review/{item_id}/{decision}")
    def review_post(item_id: int, decision: str):
        resolve_review(store, item_id, decision)
        return RedirectResponse("/review", status_code=303)

    @app.post("/review-link/{claim_id}/{code}/{decision}")
    def review_link(claim_id: int, code: str, decision: str):
        confirm_link(store, claim_id, code, decision)
        return RedirectResponse("/review", status_code=303)

    @app.get("/doctor", response_class=HTMLResponse)
    def doctor():
        checks = run_doctor(ws, store, router, ping=True)
        return render("doctor.html", checks=checks, level=summary_level(checks), roles=router.describe())

    @app.get("/digest/{name}", response_class=HTMLResponse)
    def digest(name: str):
        p = ws.okf / "digests" / f"{Path(name).name}.md"
        if not p.exists():
            raise HTTPException(404)
        return render("digest.html", name=p.stem, text=p.read_text(encoding="utf-8"),
                      all=sorted(x.stem for x in (ws.okf / "digests").glob("*.md")))

    @app.get("/health")
    def health():
        return {"ok": True, "version": __version__}

    return app
