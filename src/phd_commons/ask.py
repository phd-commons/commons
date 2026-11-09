"""Ask: hybrid retrieval, grounded answer, mechanical citation check.

Retrieval fuses SQLite FTS5 (BM25) and vector cosine rankings by reciprocal rank fusion, caps chunks per
source, optionally reranks, and fits a token budget. The answer must cite [n] for its factual sentences and
quote exactly; the check is mechanical, and a failed check triggers one regeneration and then a visible warning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import prompts
from .ingest import approx_tokens
from .llm import max_tier

ABSTAIN_PATTERNS = re.compile(
    r"(corpus does not (hold|contain)|no (relevant )?(passage|material|evidence) in the corpus|"
    r"passages do not (answer|address|cover)|not (in|covered by) the (corpus|passages))", re.I)


@dataclass
class Answer:
    question: str
    mode: str
    text: str
    passages: list[dict]
    problems: list[str] = field(default_factory=list)
    abstained: bool = False
    regenerated: bool = False

    def cited_numbers(self) -> set[int]:
        return {int(n) for n in re.findall(r"\[(\d+)\]", self.text)}


def caller_tiers(ws, caller: str) -> set[str]:
    if caller == "local":
        return {"PUBLIC", "PRIVATE", "RESTRICTED"}
    if caller == "mcp":
        tiers = {"PUBLIC"} if ws.get("mcp.public", True) else set()
        if ws.get("mcp.private", False):
            tiers.add("PRIVATE")
        return tiers
    return {"PUBLIC"}


def retrieve(ws, store, router, query: str, tiers: set[str], k: int | None = None,
             include_drafted: bool = False) -> list[dict]:
    k = k or ws.get("retrieval.top_k", 10)
    cap = ws.get("retrieval.per_source_cap", 2)
    rrf_k = ws.get("retrieval.rrf_k", 60)
    if not tiers:
        return []
    fused: dict[int, float] = {}
    for rank, (cid, _) in enumerate(store.text_search(query, 50, tiers)):
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (rrf_k + rank)
    try:
        qtier = "RESTRICTED" if "RESTRICTED" in tiers else "PRIVATE" if "PRIVATE" in tiers else "PUBLIC"
        qvec = router.embed([query], app="ask/embed-query", tier=qtier)[0]
        floor = ws.get("retrieval.min_similarity", 0.2)
        hits = [h for h in store.vector_search(qvec, 50, tiers) if h[1] >= floor]
        for rank, (cid, _) in enumerate(hits):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (rrf_k + rank)
    except Exception:  # noqa: BLE001 - text search alone still works
        pass
    if not fused:
        return []
    ids = sorted(fused, key=lambda i: -fused[i])
    marks = ",".join("?" for _ in ids)
    rows = {r["id"]: dict(r) for r in store.q(
        f"SELECT ch.id, ch.text, ch.page_from, ch.page_to, ch.tier, ch.source_id, s.title, s.year, s.slug, s.kind, "
        f"s.authors_json, s.doi, s.url FROM chunks ch JOIN sources s ON s.id=ch.source_id "
        f"WHERE ch.id IN ({marks}) AND s.status='ingested'", ids)}
    picked, per_source = [], {}
    for cid in ids:
        r = rows.get(cid)
        if not r:
            continue
        if not include_drafted and r["kind"] in ("insight", "model-drafted"):
            continue
        if per_source.get(r["source_id"], 0) >= cap:
            continue
        per_source[r["source_id"]] = per_source.get(r["source_id"], 0) + 1
        r["score"] = fused[cid]
        picked.append(r)
        if len(picked) >= k * 2:
            break
    scores = router.rerank(query, [p["text"] for p in picked], tier=max_tier(p["tier"] for p in picked)) \
        if picked else None
    if scores:
        picked = [p for _, p in sorted(zip(scores, picked), key=lambda sp: -sp[0])]
    budget, out, used = ws.get("retrieval.context_tokens", 10000), [], 0
    for p in picked[:k]:
        t = approx_tokens(p["text"])
        if out and used + t > budget:
            break
        out.append(p)
        used += t
    return out


def check_answer(text: str, passages: list[dict]) -> list[str]:
    problems = []
    n = len(passages)
    for m in re.findall(r"\[(\d+)\]", text):
        if not 1 <= int(m) <= n:
            problems.append(f"citation [{m}] does not match any passage")
    from .claims import norm_for_match
    for q in re.findall(r"\"([^\"]{12,})\"", text):
        if not any(norm_for_match(q) in norm_for_match(p["text"]) for p in passages):
            problems.append(f"quoted text not found in the passages: \"{q[:60]}\"")
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if re.search(r"\d", re.sub(r"\[\d+\]", "", sent)) and not re.search(r"\[\d+\]", sent) \
                and not sent.lstrip().startswith(("|", "#", "-")) and len(sent) > 25:
            problems.append(f"number without a citation: \"{sent.strip()[:60]}\"")
    return problems


def ask(ws, store, router, question: str, mode: str = "answer", caller: str = "local",
        include_drafted: bool = False) -> Answer:
    wanted = caller_tiers(ws, caller)
    tiers = {t for t in wanted if router.can("author", t) and router.can("embed", t)}
    notes = [f"{t} material excluded: no permitted model for it" for t in sorted(wanted - tiers)]
    query = question
    for code in set(re.findall(r"\b([A-Z]{1,3}\d{1,3})\b", question)):
        p = store.one("SELECT title, statement FROM propositions WHERE code=?", (code,))
        if p:
            query += f" {p['title'] or ''} {p['statement'] or ''}"
    passages = retrieve(ws, store, router, query, tiers, include_drafted=include_drafted)
    if not passages:
        return Answer(question, mode, "The corpus does not hold material that answers this question.", [],
                      problems=notes, abstained=True)
    tier = max_tier(p["tier"] for p in passages)
    sids = sorted({p["source_id"] for p in passages})
    tables = [dict(r) for r in store.q("SELECT name, description, provenance FROM data_tables ORDER BY name")]
    msgs = prompts.answer(question, passages, mode, tables)
    text = router.chat("author", msgs, app=f"ask/{mode}", tier=tier, source_ids=sids, max_tokens=2500)
    problems = check_answer(text, passages)
    regenerated = False
    if problems:
        regenerated = True
        msgs = msgs + [{"role": "assistant", "content": text},
                       {"role": "user", "content": "Your answer failed these checks. Fix them, keeping only what "
                        "the passages support:\n- " + "\n- ".join(problems)}]
        text = router.chat("author", msgs, app=f"ask/{mode}/retry", tier=tier, source_ids=sids, max_tokens=2500)
        problems = check_answer(text, passages)
    abstained = bool(ABSTAIN_PATTERNS.search(text))
    return Answer(question, mode, text, passages, problems + notes, abstained, regenerated)
