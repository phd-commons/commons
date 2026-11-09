"""Worked example of the analysis contract: count ingested sources by kind and tier."""


def run(ctx):
    rows = [{"kind": r["kind"] or "unknown", "public": r["pub"], "private": r["priv"]} for r in ctx.store.q(
        "SELECT kind, SUM(tier='PUBLIC') AS pub, SUM(tier='PRIVATE') AS priv FROM sources "
        "WHERE status='ingested' GROUP BY kind ORDER BY kind")]
    ctx.table("sources_by_kind", rows, provenance="DERIVED",
              description="Ingested sources by kind and tier (RESTRICTED excluded), from the Commons store")
    return f"{len(rows)} kinds"
