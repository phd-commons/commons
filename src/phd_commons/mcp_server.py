"""MCP server so a coding or chat agent can query the corpus.

Assume every MCP client is a cloud model: by default it sees PUBLIC material only. PRIVATE is served only if
mcp.private is true in commons.yaml. RESTRICTED is never served.
"""

from __future__ import annotations

try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

from .ask import ask as do_ask
from .ask import caller_tiers, retrieve
from .sweep import add_by_identifier
from .thesis import board
from .claims import thesis_tier
from .config import load_workspace
from .llm import Router
from .okf import append_log
from .store import open_store
from .thesis import evidence as evidence_q
from .thesis import sync_propositions


def build_server(ws_path: str | None = None) -> FastMCP:
    ws = load_workspace(ws_path)
    store = open_store(ws)
    router = Router(ws, store)
    sync_propositions(ws, store)
    tiers = caller_tiers(ws, "mcp")
    mcp = FastMCP("commons", instructions=(
        "Commons is a doctoral student's local research corpus. Every claim in it is tied to a verbatim quote. "
        "Use search_corpus or ask_corpus before answering questions about the student's research, cite the "
        "sources it returns, and say plainly when the corpus does not hold something. Never present your own "
        "knowledge as if it came from the corpus. Interview and other ethics-protected material is never served."))

    @mcp.tool()
    def search_corpus(query: str, top_k: int = 8) -> list[dict]:
        """Hybrid search over the student's corpus. Returns passages with source, year, page and tier."""
        rows = retrieve(ws, store, router, query, tiers, k=max(1, min(top_k, 20)))
        return [{"source_id": r["source_id"], "title": r["title"], "year": r["year"], "page": r["page_from"],
                 "tier": r["tier"], "text": r["text"]} for r in rows]

    @mcp.tool()
    def read_source(source_id: int, max_chars: int = 20000) -> dict:
        """Full extracted text and metadata of one source (if its tier is served to MCP clients)."""
        s = store.one("SELECT * FROM sources WHERE id=?", (source_id,))
        if s is None:
            return {"error": "no such source"}
        if s["tier"] not in tiers:
            return {"error": f"{s['tier']} material is not served to MCP clients"}
        text = (ws.root / s["path_text"]).read_text(encoding="utf-8") if s["path_text"] else ""
        return {"title": s["title"], "year": s["year"], "doi": s["doi"], "url": s["url"], "tier": s["tier"],
                "text": text[:max_chars]}

    @mcp.tool()
    def list_propositions() -> list[dict]:
        """The thesis propositions and rival explanations, with their student-set status."""
        if thesis_tier(ws) not in tiers:
            return [{"error": f"propositions are {thesis_tier(ws)} material and not served to MCP clients"}]
        return [dict(r) for r in store.q("SELECT code, family, title, statement, supports_if, disconfirms_if, status "
                                         "FROM propositions ORDER BY family, code")]

    @mcp.tool()
    def evidence(code: str, stance: str = "") -> list[dict]:
        """Verified claims linked to a proposition. stance: supports, contradicts, qualifies, context or empty."""
        if not tiers:
            return [{"error": "MCP access is switched off in commons.yaml"}]
        return evidence_q(store, code, stance or None, tiers=tuple(tiers))

    @mcp.tool()
    def latest_digest() -> str:
        """The most recent daily research digest (Markdown)."""
        if thesis_tier(ws) not in tiers:
            return f"The digest names your propositions, which are {thesis_tier(ws)} material; not served over MCP."
        ds = sorted((ws.okf / "digests").glob("20*.md"))
        return ds[-1].read_text(encoding="utf-8") if ds else "No digest yet."

    @mcp.tool()
    def ask_corpus(question: str, mode: str = "answer") -> dict:
        """Ask a question of the corpus. Commons answers with its own local author model, from passages the MCP
        client is allowed to see, citing them as [n]; or says the corpus does not hold the answer.
        mode: answer, devil (strongest case against), compare, notes."""
        a = do_ask(ws, store, router, question, mode=mode if mode in ("answer", "devil", "compare", "notes") else "answer",
                   caller="mcp")
        return {"answer": a.text, "abstained": a.abstained, "checks_failed": a.problems,
                "sources": [{"n": i, "source_id": p["source_id"], "title": p["title"], "year": p["year"],
                             "page": p["page_from"]} for i, p in enumerate(a.passages, 1)]}

    @mcp.tool()
    def thesis_board() -> list[dict]:
        """Evidence for and against each proposition and rival explanation (counts of verified claims)."""
        if thesis_tier(ws) not in tiers:
            return [{"error": f"propositions are {thesis_tier(ws)} material and not served to MCP clients"}]
        return [{k: r[k] for k in ("code", "family", "title", "statement", "status", "supports", "contradicts",
                                    "qualifies")} for r in board(store, include_restricted=False)]

    @mcp.tool()
    def add_published_work(doi: str) -> dict:
        """Add a published work to the corpus by DOI. Commons fetches the open-access full text where a lawful copy
        exists, otherwise the abstract, then extracts and verifies its claims. Stored as PUBLIC."""
        return add_by_identifier(ws, store, router, doi)

    @mcp.tool()
    def corpus_status() -> dict:
        """Counts of sources, verified claims and open review items, and which tiers this client may see."""
        c = store.counts()
        return {**c, "tiers_served_to_this_client": sorted(tiers)}

    @mcp.tool()
    def add_note(title: str, text: str) -> str:
        """Save a note to okf/notes, labelled as agent-written. It is never treated as evidence."""
        from .okf import slugify
        p = ws.okf / "notes" / f"agent-{slugify(title)}.md"
        p.write_text(f"# {title}\n\n_AGENT-WRITTEN via MCP. Not evidence._\n\n{text}\n", encoding="utf-8")
        append_log(ws, f"mcp note saved: {p.name}")
        return str(p.relative_to(ws.root))

    return mcp


def main(ws_path: str | None = None) -> None:
    build_server(ws_path).run()
