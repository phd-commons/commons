"""The daily research feed: pull, dedupe, screen, ingest, digest.

sources.yaml:

  queries: ["..."]                  # used by scholarly feeds unless a feed sets its own
  feeds:
    - {id: openalex, kind: openalex}                       # works since the last run, matching the queries
    - {id: arxiv, kind: arxiv, categories: [cs.CY]}
    - {id: crossref, kind: crossref}
    - {id: regulator, kind: rss, url: "https://example.org/feed.xml", strength: PRIMARY}

Open-access full text is fetched when a lawful copy exists; otherwise the abstract is stored and the item is
listed under "get through your library".
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
import time
from pathlib import Path

import feedparser
import httpx

from . import __version__, prompts
from .ingest import ingest_file
from .llm import extract_json
from .okf import append_log
from .thesis import sync_propositions

UA_BASE = f"phd-commons/{__version__} (+https://github.com/phd-commons/commons)"


def _client(ws) -> httpx.Client:
    ua = UA_BASE
    email = ws.get("contact_email") or ""
    if email:
        ua += f" mailto:{email}"
    return httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": ua})


def _get(http, url, params=None, tries: int = 3):
    """GET with polite backoff on 429 and 5xx."""
    r = None
    for attempt in range(tries):
        r = http.get(url, params=params)
        if r.status_code not in (429, 500, 502, 503, 504):
            return r
        wait = float(r.headers.get("Retry-After", 0) or 0) or 2 ** (attempt + 1)
        if wait > 60:
            return r
        time.sleep(wait)
    return r


def _since(store, feed_id: str, days_default: int = 30) -> str:
    r = store.one("SELECT cursor FROM feeds_state WHERE feed_id=?", (feed_id,))
    if r and r["cursor"]:
        return r["cursor"]
    return (dt.date.today() - dt.timedelta(days=days_default)).isoformat()


def _set_state(store, feed_id: str, ok: bool, error: str = "") -> None:
    today = dt.date.today().isoformat()
    with store.tx() as c:
        c.execute(
            "INSERT INTO feeds_state (feed_id, cursor, last_run, last_ok, last_error) VALUES (?,?,?,?,?) "
            "ON CONFLICT(feed_id) DO UPDATE SET cursor=CASE WHEN ? THEN excluded.cursor ELSE feeds_state.cursor END,"
            " last_run=excluded.last_run, last_ok=CASE WHEN ? THEN excluded.last_ok ELSE feeds_state.last_ok END, "
            "last_error=excluded.last_error",
            (feed_id, today, today, today if ok else None, error, int(ok), int(ok)))


def _abstract_from_inverted(inv: dict | None) -> str:
    if not inv:
        return ""
    pos = sorted((p, w) for w, ps in inv.items() for p in ps)
    return " ".join(w for _, w in pos)


# ---------- feed adapters return dicts: title, abstract, doi, url, year, authors, venue, pdf_url, published_at
def fetch_openalex(http, feed, queries, since, limit):
    items = []
    for q in feed.get("queries", queries):
        params = {"search": q, "filter": f"from_publication_date:{since}", "per-page": min(limit, 50)}
        key = os.environ.get("OPENALEX_API_KEY") or feed.get("api_key")
        if key:
            params["api_key"] = key
        r = _get(http, "https://api.openalex.org/works", params)
        if r.status_code == 429 and not key:
            raise RuntimeError("OpenAlex rate limit: get a free API key at openalex.org and set OPENALEX_API_KEY")
        r.raise_for_status()
        for w in r.json().get("results", []):
            oa = w.get("best_oa_location") or {}
            items.append({
                "title": w.get("display_name") or "", "abstract": _abstract_from_inverted(w.get("abstract_inverted_index")),
                "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
                "url": (w.get("primary_location") or {}).get("landing_page_url") or w.get("id"),
                "year": w.get("publication_year"), "published_at": w.get("publication_date"),
                "authors": [a["author"]["display_name"] for a in w.get("authorships", [])[:8]],
                "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
                "pdf_url": oa.get("pdf_url"), "licence": oa.get("license"),
            })
        time.sleep(0.2)
    return items


def fetch_arxiv(http, feed, queries, since, limit):
    items = []
    cats = feed.get("categories") or []
    for q in feed.get("queries", queries):
        terms = " AND ".join(f'all:"{w}"' if " " in w else f"all:{w}" for w in [q])
        cat = (" AND (" + " OR ".join(f"cat:{c}" for c in cats) + ")") if cats else ""
        r = _get(http, "https://export.arxiv.org/api/query",
                 {"search_query": terms + cat, "sortBy": "submittedDate", "sortOrder": "descending",
                             "max_results": limit})
        r.raise_for_status()
        for e in feedparser.parse(r.text).entries:
            pub = (e.get("published") or "")[:10]
            if pub and pub < since:
                continue
            pdf = next((ln.href for ln in e.get("links", []) if ln.get("type") == "application/pdf"), None)
            items.append({"title": e.get("title", "").replace("\n", " "), "abstract": e.get("summary", ""),
                          "doi": e.get("arxiv_doi"), "url": e.get("link"), "year": int(pub[:4]) if pub else None,
                          "published_at": pub, "authors": [a.name for a in e.get("authors", [])][:8],
                          "venue": "arXiv", "pdf_url": pdf, "licence": None})
        time.sleep(3)  # arXiv asks for a pause between requests
    return items


def fetch_crossref(http, feed, queries, since, limit):
    items = []
    for q in feed.get("queries", queries):
        r = _get(http, "https://api.crossref.org/works",
                 {"query": q, "filter": f"from-pub-date:{since},type:journal-article", "rows": limit})
        r.raise_for_status()
        for w in r.json().get("message", {}).get("items", []):
            parts = (w.get("published") or w.get("issued") or {}).get("date-parts", [[None]])[0]
            items.append({"title": " ".join(w.get("title") or []), "abstract": re.sub(r"<[^>]+>", "", w.get("abstract", "")),
                          "doi": w.get("DOI"), "url": w.get("URL"), "year": parts[0] if parts else None,
                          "published_at": "-".join(str(p).zfill(2) for p in parts if p),
                          "authors": [f"{a.get('family', '')}, {a.get('given', '')}".strip(", ")
                                      for a in w.get("author", [])[:8]],
                          "venue": " ".join(w.get("container-title") or []), "pdf_url": None, "licence": None})
    return items


def fetch_rss(http, feed, queries, since, limit):
    r = http.get(feed["url"])
    r.raise_for_status()
    out = []
    for e in feedparser.parse(r.content).entries[:limit]:
        pub = ""
        if e.get("published_parsed"):
            pub = time.strftime("%Y-%m-%d", e.published_parsed)
        if pub and pub < since:
            continue
        out.append({"title": e.get("title", ""), "abstract": re.sub(r"<[^>]+>", "", e.get("summary", "")),
                    "doi": None, "url": e.get("link"), "year": int(pub[:4]) if pub else None, "published_at": pub,
                    "authors": [], "venue": feed.get("name") or feed["id"],
                    "pdf_url": e.get("link") if (e.get("link") or "").lower().endswith(".pdf") else None,
                    "licence": None})
    return out


ADAPTERS = {"openalex": fetch_openalex, "arxiv": fetch_arxiv, "crossref": fetch_crossref, "rss": fetch_rss}


def _seen(store, it) -> bool:
    if it.get("doi") and store.one("SELECT 1 FROM sources WHERE lower(doi)=lower(?)", (it["doi"],)):
        return True
    if it.get("url") and store.one("SELECT 1 FROM sources WHERE url=?", (it["url"],)):
        return True
    return False


def screen(ws, router, it, props) -> dict:
    """Propositions are the student's drafts, so screening runs at the thesis tier (PRIVATE by default)."""
    from .claims import thesis_tier
    try:
        reply = router.chat("worker", prompts.screen_item(it["title"], (it.get("abstract") or "")[:4000], props),
                            app="sweep/screen", tier=thesis_tier(ws), json_mode=True, temperature=0.0,
                            max_tokens=300)
        d = extract_json(reply)
        if isinstance(d, list):
            d = d[0] if d and isinstance(d[0], dict) else {}
        return {"score": int(d.get("score", 0)), "challenges": d.get("challenges") or [], "reason": d.get("reason", ""),
                "ok": True}
    except Exception as e:  # noqa: BLE001
        return {"score": 0, "challenges": [], "reason": f"screen failed: {e}", "ok": False}


def run_sweep(ws, store, router, only: str | None = None) -> dict:
    cfg = ws.load_yaml(ws.sources_path())
    queries = cfg.get("queries") or []
    feeds = [f for f in cfg.get("feeds", []) if not only or f.get("id") == only]
    props = sync_propositions(ws, store)
    keep = ws.get("sweep.keep_threshold", 2)
    limit = ws.get("sweep.max_items_per_feed", 25)
    report = {"date": dt.date.today().isoformat(), "kept": [], "rejected": [], "failed_feeds": [], "library": []}
    http = _client(ws)
    for feed in feeds:
        fid, kind = feed.get("id"), feed.get("kind")
        adapter = ADAPTERS.get(kind)
        if adapter is None:
            report["failed_feeds"].append({"feed": fid, "error": f"unknown kind {kind}"})
            continue
        try:
            items = adapter(http, feed, queries, _since(store, fid), limit)
        except Exception as e:  # noqa: BLE001
            report["failed_feeds"].append({"feed": fid, "error": str(e)[:200]})
            _set_state(store, fid, False, str(e)[:200])
            continue
        screen_failures = 0
        for it in items:
            if not it.get("title") or _seen(store, it):
                continue
            sc = screen(ws, router, it, props)
            it.update(sc, feed=fid)
            if not sc["ok"]:
                screen_failures += 1
                continue
            if sc["score"] >= keep or (sc["challenges"] and sc["score"] >= 1):
                res = _ingest_item(ws, store, router, it, feed)
                it["result"] = res
                report["kept"].append(it)
                if res in ("abstract-only", "skipped-no-text"):
                    report["library"].append(it)
            else:
                report["rejected"].append({"title": it["title"], "score": sc["score"], "reason": sc["reason"],
                                           "feed": fid})
        if screen_failures:
            # Do not advance the cursor: tomorrow's run sees these items again once the model is back.
            report["failed_feeds"].append({"feed": fid, "error": f"{screen_failures} items could not be screened "
                                                                    "(model unavailable?); they will be retried"})
            _set_state(store, fid, False, f"{screen_failures} screening failures")
        else:
            _set_state(store, fid, True)
    _write_rejections(ws, report)
    append_log(ws, f"sweep: {len(report['kept'])} kept, {len(report['rejected'])} rejected, "
                   f"{len(report['failed_feeds'])} feeds failed")
    (ws.data / "last_sweep.json").write_text(json.dumps(report, default=str, indent=1))
    return report


def _ingest_item(ws, store, router, it, feed) -> str:
    meta = {k: it.get(k) for k in ("title", "doi", "url", "year", "authors", "venue", "abstract", "licence",
                                   "published_at")}
    meta["origin_feed"] = feed.get("id")
    meta["kind"] = feed.get("source_kind", "article")
    if it.get("pdf_url"):
        try:
            with _client(ws) as http:
                r = http.get(it["pdf_url"])
                r.raise_for_status()
                if b"%PDF" in r.content[:1024]:
                    with tempfile.TemporaryDirectory() as td:
                        p = Path(td) / "item.pdf"
                        p.write_bytes(r.content)
                        res = ingest_file(ws, store, router, p, tier="PUBLIC", meta=meta)
                        if res.status == "ingested":
                            return "full-text"
        except Exception:  # noqa: BLE001
            pass
    if not it.get("abstract"):
        return "skipped-no-text"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "abstract.md"
        p.write_text(f"# {it['title']}\n\n{it['abstract']}\n\nSource: {it.get('url') or it.get('doi')}\n"
                     "(Abstract only. Get the full text through your library.)\n", encoding="utf-8")
        meta["kind"] = "abstract"
        res = ingest_file(ws, store, router, p, tier="PUBLIC", meta=meta, min_chars=150)
    return "abstract-only" if res.status == "ingested" else f"failed: {res.message}"


def _write_rejections(ws, report) -> None:
    p = ws.okf / "digests" / f"rejected-{report['date']}.md"
    lines = [f"# Screened out on {report['date']}", "", "Every item the relevance screen dropped, with its reason.", ""]
    for r in report["rejected"]:
        lines.append(f"- [{r['score']}] {r['title']} ({r['feed']}): {r['reason']}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_digest(ws, store, date: str | None = None) -> Path:
    date = date or dt.date.today().isoformat()
    rep_path = ws.data / "last_sweep.json"
    rep = json.loads(rep_path.read_text()) if rep_path.exists() else {"kept": [], "failed_feeds": [], "library": []}
    since = (dt.date.fromisoformat(date) - dt.timedelta(days=1)).isoformat()
    lines = [f"# Research digest, {date}", ""]
    kept = rep.get("kept", [])
    lines += [f"{len(kept)} new items kept from the sweep. "
              f"{store.scalar('SELECT COUNT(*) FROM review_items WHERE resolved_at IS NULL') or 0} items wait in Review.", ""]
    lines += ["## Evidence movement since yesterday", "",
              "| Proposition | For | Against | Qualifies |", "|---|---|---|---|"]
    for p in store.q("SELECT code, title FROM propositions ORDER BY family, code"):
        cnt = {}
        for st in ("supports", "contradicts", "qualifies"):
            cnt[st] = store.scalar(
                "SELECT COUNT(*) FROM evidence_links l JOIN claims c ON c.id=l.claim_id WHERE l.proposition_code=? "
                "AND l.stance=? AND c.created_at >= ? AND c.status IN ('verified','confirmed') AND c.tier!='RESTRICTED'",
                (p["code"], st, since)) or 0
        lines.append(f"| {p['code']} {p['title'] or ''} | {cnt['supports']} | {cnt['contradicts']} | {cnt['qualifies']} |")
    lines += ["", "## New items", ""]
    challenging = [k for k in kept if k.get("challenges")]
    for it in sorted(kept, key=lambda k: -k.get("score", 0)):
        flag = f" Challenges {', '.join(it['challenges'])}." if it.get("challenges") else ""
        lines.append(f"- **{it['title']}** ({it.get('venue') or it.get('feed')}, {it.get('year') or ''}). "
                     f"{it.get('reason', '')}{flag} [{it.get('result', '')}]")
    if challenging:
        lines += ["", "## Items that cut against a proposition", ""]
        lines += [f"- {it['title']}: {', '.join(it['challenges'])}" for it in challenging]
    if rep.get("library"):
        lines += ["", "## Get through your library (abstract only so far)", ""]
        lines += [f"- {it['title']} {('https://doi.org/' + it['doi']) if it.get('doi') else it.get('url', '')}"
                  for it in rep["library"]]
    if rep.get("failed_feeds"):
        lines += ["", "## Feeds that failed", ""]
        lines += [f"- {f['feed']}: {f['error']}" for f in rep["failed_feeds"]]
    lines += ["", "## Recommended reads", ""]
    for it in sorted(kept, key=lambda k: (-(len(k.get("challenges") or []) > 0), -k.get("score", 0)))[:3]:
        lines.append(f"- {it['title']}: {it.get('reason', '')}")
    path = ws.okf / "digests" / f"{date}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    append_log(ws, f"digest {date}: {len(kept)} items")
    return path


def add_by_identifier(ws, store, router, ident: str) -> dict:
    """Add one published work by DOI (or doi.org URL) as PUBLIC: open-access full text if lawful, else abstract."""
    ident = ident.strip()
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", ident, flags=re.I)
    if not re.match(r"^10\.\d{4,9}/\S+$", doi):
        return {"status": "refused", "message": "give a DOI such as 10.1234/abcd or a doi.org link"}
    params = {}
    key = os.environ.get("OPENALEX_API_KEY")
    if key:
        params["api_key"] = key
    with _client(ws) as http:
        r = _get(http, f"https://api.openalex.org/works/doi:{doi}", params)
        if r.status_code == 404:
            return {"status": "failed", "message": f"OpenAlex has no record of {doi}"}
        if r.status_code >= 400:
            return {"status": "failed", "message": f"OpenAlex returned {r.status_code}"}
        w = r.json()
    oa = w.get("best_oa_location") or {}
    it = {"title": w.get("display_name") or doi, "abstract": _abstract_from_inverted(w.get("abstract_inverted_index")),
          "doi": doi, "url": (w.get("primary_location") or {}).get("landing_page_url") or f"https://doi.org/{doi}",
          "year": w.get("publication_year"), "published_at": w.get("publication_date"),
          "authors": [a["author"]["display_name"] for a in w.get("authorships", [])[:8]],
          "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
          "pdf_url": oa.get("pdf_url"), "licence": oa.get("license")}
    if _seen(store, it):
        return {"status": "duplicate", "message": "already in the corpus", "title": it["title"]}
    res = _ingest_item(ws, store, router, it, {"id": "manual", "source_kind": "article"})
    return {"status": "added" if res in ("full-text", "abstract-only") else "failed", "message": res,
            "title": it["title"], "year": it["year"]}
