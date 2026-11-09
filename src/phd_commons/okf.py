"""The OKF: the plain-Markdown knowledge base that is the source of truth.

Source notes keep a frontmatter block (machine-owned) and an "Your notes" section (human-owned, preserved on
rewrite). The claim register is a JSONL file. The log records every run with counts.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata

import yaml

NOTES_HEADING = "## Your notes"


def slugify(text: str, maxlen: int = 80) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return re.sub(r"-{2,}", "-", text)[:maxlen].strip("-") or "source"


def append_log(ws, line: str) -> None:
    log = ws.okf / "log.md"
    if not log.exists():
        log.write_text("# log\n\n", encoding="utf-8")
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"- {time.strftime('%Y-%m-%d %H:%M')} {line}\n")


def source_note_path(ws, slug: str, tier: str):
    base = ws.okf / ("restricted/sources" if tier == "RESTRICTED" else "sources")
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{slug}.md"


def write_source_note(ws, store, source_id: int) -> None:
    s = store.one("SELECT * FROM sources WHERE id=?", (source_id,))
    if s is None:
        return
    path = source_note_path(ws, s["slug"], s["tier"])
    preserved = ""
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if NOTES_HEADING in old:
            preserved = old.split(NOTES_HEADING, 1)[1]
    claims = store.q(
        "SELECT c.*, group_concat(l.proposition_code || ' ' || l.stance || CASE WHEN l.confirmed THEN '' ELSE '?' END, '; ')"
        " AS links FROM claims c LEFT JOIN evidence_links l ON l.claim_id=c.id WHERE c.source_id=? "
        "AND c.status != 'rejected' GROUP BY c.id ORDER BY c.page, c.id", (source_id,))
    fm = {
        "id": s["id"], "slug": s["slug"], "kind": s["kind"], "title": s["title"],
        "authors": json.loads(s["authors_json"] or "[]"), "year": s["year"], "venue": s["venue"],
        "doi": s["doi"], "url": s["url"], "tier": s["tier"], "sha256": s["sha256"],
        "published": s["published_at"], "retrieved": s["retrieved_at"], "status": s["status"],
        "original": s["path_original"],
    }
    lines = ["---", yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip(), "---", "", f"# {s['title']}", ""]
    if s["abstract"]:
        lines += ["## Abstract (from the publisher)", "", s["abstract"].strip(), ""]
    lines += ["## Claims", ""]
    if not claims:
        lines.append("_No verified claims yet._")
    for c in claims:
        page = f" (p. {c['page']})" if c["page"] else ""
        mark = "" if c["status"] in ("verified", "confirmed") else " [needs review]"
        links = f" → {c['links']}" if c["links"] else ""
        lines.append(f"- C{c['id']}{mark} \"{c['quote']}\"{page}{links}")
    lines += ["", "_Links marked ? are proposed by a model and await confirmation._", "",
              NOTES_HEADING + (preserved if preserved else "\n\n")]
    path.write_text("\n".join(lines), encoding="utf-8")


def export_claims_register(ws, store) -> int:
    """Write okf/claims/claims.jsonl (non-restricted) and okf/restricted/claims.jsonl."""
    rows = store.q(
        "SELECT c.*, s.slug FROM claims c JOIN sources s ON s.id=c.source_id ORDER BY c.id")
    links = {}
    for r in store.q("SELECT * FROM evidence_links"):
        links.setdefault(r["claim_id"], []).append(
            {"p": r["proposition_code"], "stance": r["stance"], "confirmed": bool(r["confirmed"])})
    out_pub = ws.okf / "claims" / "claims.jsonl"
    out_res = ws.okf / "restricted" / "claims.jsonl"
    out_pub.parent.mkdir(parents=True, exist_ok=True)
    out_res.parent.mkdir(parents=True, exist_ok=True)
    with open(out_pub, "w", encoding="utf-8") as fp, open(out_res, "w", encoding="utf-8") as fr:
        for r in rows:
            rec = {k: r[k] for k in ("id", "slug", "page", "claim", "quote", "claim_type", "quote_verified",
                                     "verifier_verdict", "status", "provenance", "strength", "tier")}
            rec["links"] = links.get(r["id"], [])
            (fr if r["tier"] == "RESTRICTED" else fp).write(json.dumps(rec, ensure_ascii=False) + "\n")
    return len(rows)


def write_index(ws, store) -> None:
    c = store.counts()
    lines = [
        "# Index", "",
        f"Sources: {c['sources']} · Chunks: {c['chunks']} · Verified claims: {c['claims_verified']} · "
        f"Open review items: {c['review_open']}", "",
        "- [Thesis](../thesis.yaml)", "- [Claim register](claims/claims.jsonl)", "- [Log](log.md)",
        "- [Digests](digests/)", "",
        "## Sources", "",
    ]
    for s in store.q("SELECT slug, title, year, tier FROM sources WHERE status='ingested' AND tier!='RESTRICTED' "
                     "ORDER BY year DESC, title"):
        lines.append(f"- [{s['title']}](sources/{s['slug']}.md) ({s['year'] or 'n.d.'}, {s['tier']})")
    (ws.okf / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
