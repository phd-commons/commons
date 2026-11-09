"""Propositions, rival explanations and the evidence board.

thesis.yaml is the student's own document. Commons reads it; it never changes a proposition's status.
Format:

  research_questions: {primary: "...", RQ2: "..."}
  propositions:
    - code: P1
      family: P            # any label; P (propositions) and R (rivals) by convention
      title: ...
      statement: ...
      supports_if: ...
      disconfirms_if: ...
      status: untested     # set by the student only
"""

from __future__ import annotations

import yaml

STANCES = ("supports", "contradicts", "qualifies", "context")


def load_thesis(ws) -> dict:
    p = ws.thesis_path()
    data = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}
    props = []
    for key in ("propositions", "rivals", "strategic"):  # tolerate grouped layouts
        for item in data.get(key, []) or []:
            if not isinstance(item, dict) or not str(item.get("code") or "").strip():
                continue  # an entry without a code cannot be linked; skip it rather than crash
            item = dict(item)
            item["code"] = str(item["code"]).strip()
            item.setdefault("family", "R" if key == "rivals" else "P")
            for f in ("title", "statement", "supports_if", "disconfirms_if"):
                item[f] = str(item.get(f) or "")
            props.append(item)
    data["all"] = props
    return data


def sync_propositions(ws, store) -> list[dict]:
    props = load_thesis(ws)["all"]
    with store.tx() as c:
        codes = [p["code"] for p in props]
        for p in props:
            c.execute(
                "INSERT INTO propositions (code, family, title, statement, supports_if, disconfirms_if, status) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET family=excluded.family, "
                "title=excluded.title, statement=excluded.statement, supports_if=excluded.supports_if, "
                "disconfirms_if=excluded.disconfirms_if, status=excluded.status",
                (p["code"], p.get("family"), p.get("title"), (p.get("statement") or "").strip(),
                 (p.get("supports_if") or "").strip(), (p.get("disconfirms_if") or "").strip(),
                 p.get("status", "untested")))
        if codes:
            marks = ",".join("?" for _ in codes)
            c.execute(f"DELETE FROM propositions WHERE code NOT IN ({marks})", codes)
    return props


def board(store, include_restricted: bool = True) -> list[dict]:
    tier_filter = "" if include_restricted else "AND c.tier != 'RESTRICTED'"
    out = []
    for p in store.q("SELECT * FROM propositions ORDER BY family, code"):
        row = dict(p)
        for stance in STANCES:
            row[stance] = store.scalar(
                f"SELECT COUNT(*) FROM evidence_links l JOIN claims c ON c.id=l.claim_id WHERE l.proposition_code=? "
                f"AND l.stance=? AND c.status IN ('verified','confirmed') {tier_filter}", (p["code"], stance)) or 0
            row[stance + "_confirmed"] = store.scalar(
                f"SELECT COUNT(*) FROM evidence_links l JOIN claims c ON c.id=l.claim_id WHERE l.proposition_code=? "
                f"AND l.stance=? AND l.confirmed=1 {tier_filter}", (p["code"], stance)) or 0
        row["top_for"] = _top(store, p["code"], "supports", tier_filter)
        row["top_against"] = _top(store, p["code"], "contradicts", tier_filter)
        out.append(row)
    return out


def _top(store, code: str, stance: str, tier_filter: str) -> list[dict]:
    rows = store.q(
        f"SELECT c.id, c.quote, c.page, s.title, s.year, l.confirmed FROM evidence_links l "
        f"JOIN claims c ON c.id=l.claim_id JOIN sources s ON s.id=c.source_id WHERE l.proposition_code=? "
        f"AND l.stance=? AND c.status IN ('verified','confirmed') {tier_filter} "
        f"ORDER BY l.confirmed DESC, c.id DESC LIMIT 3", (code, stance))
    return [dict(r) for r in rows]


def evidence(store, code: str, stance: str | None = None, tiers=("PUBLIC", "PRIVATE", "RESTRICTED")) -> list[dict]:
    marks = ",".join("?" for _ in tiers)
    args = [code, *tiers]
    sql = (f"SELECT c.id, c.claim, c.quote, c.page, c.tier, l.stance, l.confirmed, s.title, s.year, s.slug "
           f"FROM evidence_links l JOIN claims c ON c.id=l.claim_id JOIN sources s ON s.id=c.source_id "
           f"WHERE l.proposition_code=? AND c.tier IN ({marks}) AND c.status != 'rejected'")
    if stance:
        sql += " AND l.stance=?"
        args.append(stance)
    return [dict(r) for r in store.q(sql + " ORDER BY l.confirmed DESC, c.id", args)]
