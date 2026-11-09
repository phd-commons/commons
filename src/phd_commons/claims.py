"""Claims: extract, check mechanically, verify adversarially, link to propositions.

Mechanical checks beat model votes. A quote must appear in the stored source text (after whitespace, ligature
and hyphenation normalisation) or the claim is rejected. A verifier that rejects a verbatim-quoted claim does
not get the last word: the claim goes to the student's review queue instead of the bin.
"""

from __future__ import annotations

import re

from . import prompts
from .llm import extract_json
from .okf import append_log
from .llm import max_tier
from .thesis import STANCES, sync_propositions


def thesis_tier(ws) -> str:
    """Propositions are the student's drafts: PRIVATE unless they say otherwise."""
    return str(ws.get("thesis_tier", "PRIVATE")).upper()

STATUS_VERIFIED = "verified"
STATUS_REVIEW = "review"
STATUS_REJECTED = "rejected"


def norm_for_match(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("­", "")
    text = re.sub(r"[‘’‛′]", "'", text)
    text = re.sub(r"[“”‟″]", '"', text)
    text = re.sub(r"[‐-―]", "-", text)
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    return re.sub(r"\s+", " ", text).strip()


def quote_in_source(quote: str, source_text: str) -> bool:
    q = norm_for_match(quote).strip(" .\"'")
    return len(q) >= 12 and q in norm_for_match(source_text)


def _source_text(ws, s) -> str:
    if s["path_text"]:
        p = ws.root / s["path_text"]
        if p.exists():
            return p.read_text(encoding="utf-8")
    return ""


def process_source_claims(ws, store, router, source_id: int) -> dict:
    s = store.one("SELECT * FROM sources WHERE id=?", (source_id,))
    if s is None or s["status"] != "ingested":
        return {}
    props = sync_propositions(ws, store)
    full = _source_text(ws, s)
    max_claims = ws.get("claims.max_per_chunk", 3)
    last_error = ""
    stats = {"extracted": 0, "verified": 0, "review": 0, "rejected": 0, "linked": 0, "failed_chunks": 0}
    ptier = max_tier([s["tier"], thesis_tier(ws)])
    for ch in store.q("SELECT * FROM chunks WHERE source_id=? ORDER BY idx", (source_id,)):
        try:
            reply = router.chat("worker", prompts.extract_claims(ch["text"], ch["page_from"], None, max_claims),
                                app="claims/extract", tier=s["tier"], source_ids=[source_id], json_mode=True,
                                max_tokens=2048)
            items = extract_json(reply)
        except Exception as e:  # noqa: BLE001
            stats["failed_chunks"] += 1
            last_error = str(e)[:200]
            continue
        items = _as_list(items, "claims")
        for it in items[:max_claims] if isinstance(items, list) else []:
            claim = str(it.get("claim", "")).strip()
            quote = str(it.get("quote", "")).strip()
            if not claim or not quote:
                continue
            stats["extracted"] += 1
            ok_quote = quote_in_source(quote, ch["text"]) or quote_in_source(quote, full)
            verdict, status = None, STATUS_REJECTED
            if ok_quote:
                verdict = _verify(router, claim, quote, s, source_id)
                status = STATUS_VERIFIED if verdict == "SUPPORTED" else STATUS_REVIEW
            page = it.get("page") if isinstance(it.get("page"), int) else ch["page_from"]
            with store.tx() as c:
                cur = c.execute(
                    "INSERT INTO claims (source_id, chunk_id, claim, quote, page, claim_type, quote_verified, "
                    "verifier_verdict, status, tier) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (source_id, ch["id"], claim, quote, page, it.get("claim_type"), int(ok_quote), verdict, status,
                     s["tier"]))
                cid = int(cur.lastrowid)
            if status == STATUS_REJECTED:
                stats["rejected"] += 1
                continue
            if status == STATUS_REVIEW:
                stats["review"] += 1
                store.add_review("claim", cid, {"verdict": verdict, "claim": claim, "quote": quote}, tier=s["tier"])
            else:
                stats["verified"] += 1
            stats["linked"] += _link(router, store, cid, claim, quote, props, s, ptier)
    label = s["slug"] if s["tier"] != "RESTRICTED" else f"source {source_id} (RESTRICTED)"
    if stats["failed_chunks"]:
        store.add_review("extraction_failed", source_id,
                         {"source": label, "failed_chunks": stats["failed_chunks"], "error": last_error,
                          "retry": f"commons claims {source_id}"}, tier=s["tier"])
    append_log(ws, f"claims {label}: {stats['extracted']} extracted, {stats['verified']} verified, "
                   f"{stats['review']} to review, {stats['rejected']} rejected (quote not in source), "
                   f"{stats['failed_chunks']} chunks failed")
    return stats


def _as_list(value, key: str) -> list:
    """Servers in JSON mode often return one object, or an array wrapped in an object, instead of a bare array."""
    if isinstance(value, dict):
        inner = value.get(key)
        if isinstance(inner, list):
            return inner
        return [] if key in value else [value]
    return value if isinstance(value, list) else []


def _verify(router, claim: str, quote: str, s, source_id: int) -> str:
    try:
        reply = router.chat("verifier", prompts.verify_claim(claim, quote), app="claims/verify", tier=s["tier"],
                            source_ids=[source_id], max_tokens=200, temperature=0.0)
    except Exception:  # noqa: BLE001
        return "UNVERIFIED"
    head = reply.strip().upper()
    for label in ("NOT_SUPPORTED", "OVERSTATED", "SUPPORTED"):
        if head.startswith(label) or label in head[:40]:
            return label
    return "UNCLEAR"


def _link(router, store, claim_id: int, claim: str, quote: str, props: list[dict], s, tier: str) -> int:
    if not props:
        return 0
    try:
        reply = router.chat("worker", prompts.link_claim(claim, quote, props), app="claims/link", tier=tier,
                            source_ids=[s["id"]], json_mode=True, temperature=0.0)
        links = extract_json(reply)
    except Exception:  # noqa: BLE001
        return 0
    links = _as_list(links, "links")
    valid = {p["code"] for p in props}
    n = 0
    for ln in links if isinstance(links, list) else []:
        code, stance = str(ln.get("code", "")).strip(), str(ln.get("stance", "")).strip().lower()
        if code in valid and stance in STANCES:
            with store.tx() as c:
                c.execute("INSERT OR IGNORE INTO evidence_links (claim_id, proposition_code, stance, proposed_by, note)"
                          " VALUES (?,?,?,?,?)", (claim_id, code, stance, "worker", ln.get("reason")))
            n += 1
    return n


def resolve_review(store, item_id: int, decision: str) -> None:
    """decision: accept | reject. For claims, accept marks the claim confirmed; for links, confirms them."""
    item = store.one("SELECT * FROM review_items WHERE id=?", (item_id,))
    if item is None:
        raise KeyError(item_id)
    with store.tx() as c:
        if item["kind"] == "claim":
            c.execute("UPDATE claims SET status=? WHERE id=?",
                      ("confirmed" if decision == "accept" else STATUS_REJECTED, item["ref_id"]))
        c.execute("UPDATE review_items SET resolved_at=datetime('now'), resolution=? WHERE id=?", (decision, item_id))


def confirm_link(store, claim_id: int, code: str, decision: str) -> None:
    with store.tx() as c:
        if decision == "accept":
            c.execute("UPDATE evidence_links SET confirmed=1 WHERE claim_id=? AND proposition_code=?", (claim_id, code))
        else:
            c.execute("DELETE FROM evidence_links WHERE claim_id=? AND proposition_code=?", (claim_id, code))
