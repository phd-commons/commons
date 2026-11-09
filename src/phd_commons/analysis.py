"""Analysis modules: field-specific tests of the thesis, plus two built-ins every project gets.

A workspace module lives at analyses/<code>/run.py and defines:

    def run(ctx):
        rows = [...]                                  # list of dicts
        ctx.table("name", rows, provenance="MEASURED", description="...")
        return "one-line summary"

ctx gives the workspace (ctx.ws), the store (ctx.store), the model router (ctx.router), an HTTP client
(ctx.http) and ctx.table() to register outputs. Each run writes a stamp (as-at date, code hash, params,
outputs) so the result can be reproduced.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
from dataclasses import dataclass, field

import httpx

from .export import register_table


@dataclass
class Ctx:
    ws: object
    store: object
    router: object
    code: str
    params: dict = field(default_factory=dict)
    outputs: list = field(default_factory=list)

    @property
    def http(self):
        return httpx.Client(timeout=60, follow_redirects=True)

    def table(self, name: str, rows: list[dict], provenance: str, description: str = ""):
        register_table(self.ws, self.store, name, rows, self.code, provenance, description)
        self.outputs.append({"table": name, "rows": len(rows), "provenance": provenance})


def builtin_evidence_balance(ctx: Ctx) -> str:
    rows = []
    for p in ctx.store.q("SELECT code, title FROM propositions ORDER BY family, code"):
        r = {"proposition": p["code"]}
        for st in ("supports", "contradicts", "qualifies"):
            r[st] = ctx.store.scalar(
                "SELECT COUNT(*) FROM evidence_links l JOIN claims c ON c.id=l.claim_id WHERE l.proposition_code=? "
                "AND l.stance=? AND c.status IN ('verified','confirmed') AND c.tier!='RESTRICTED'",
                (p["code"], st)) or 0
        rows.append(r)
    ctx.table("evidence_balance", rows, "DERIVED", "Verified claims for, against and qualifying each proposition")
    return f"{len(rows)} propositions counted"


def builtin_literature_by_year(ctx: Ctx) -> str:
    rows = [{"year": str(r["year"]), "sources": r["n"]} for r in ctx.store.q(
        "SELECT year, COUNT(*) n FROM sources WHERE status='ingested' AND year IS NOT NULL AND tier!='RESTRICTED' "
        "GROUP BY year ORDER BY year")]
    ctx.table("literature_by_year", rows, "DERIVED", "Ingested sources by publication year")
    return f"{sum(r['sources'] for r in rows)} sources across {len(rows)} years"


BUILTINS = {"evidence_balance": builtin_evidence_balance, "literature_by_year": builtin_literature_by_year}


def list_modules(ws) -> list[str]:
    d = ws.root / "analyses"
    local = sorted(p.name for p in d.iterdir() if (p / "run.py").exists()) if d.exists() else []
    return list(BUILTINS) + local


def run_module(ws, store, router, code: str, params: dict | None = None) -> dict:
    ctx = Ctx(ws, store, router, code, params or {})
    if code in BUILTINS:
        summary, code_hash = BUILTINS[code](ctx), "builtin"
    else:
        path = ws.root / "analyses" / code / "run.py"
        if not path.exists():
            raise KeyError(f"no analysis module '{code}'")
        code_hash = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        spec = importlib.util.spec_from_file_location(f"commons_analysis_{code}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        summary = mod.run(ctx)
    stamp = {"module": code, "as_at": dt.datetime.now().isoformat(timespec="seconds"), "code_hash": code_hash,
             "params": ctx.params, "outputs": ctx.outputs, "summary": summary}
    out_dir = ws.okf / "analyses" / code
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"stamp-{dt.datetime.now():%Y%m%d-%H%M%S}.json").write_text(json.dumps(stamp, indent=2))
    return stamp
