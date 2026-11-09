"""Deterministic offline provider for tests and the demo workspace. It is not a model and makes no claims.

It reads the same prompts real models get (see prompts.py markers) and returns well-formed replies, so the
whole pipeline can be exercised in CI with no network and no GPU.
"""

from __future__ import annotations

import hashlib
import json
import re

import numpy as np

DIMS = 256
_WORD = re.compile(r"[a-z0-9]+")
STOP = set("the a an and or of to in on for with by at from is are was were be been it its this that these those as "
           "not no than then so such each all any which who what how why can could would should may might".split())


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in STOP and len(w) > 2]


def fake_embed(texts: list[str]) -> np.ndarray:
    out = np.zeros((len(texts), DIMS), dtype=np.float32)
    for i, t in enumerate(texts):
        for w in _tokens(t):
            h = int(hashlib.md5(w.encode()).hexdigest(), 16)
            out[i, h % DIMS] += 1.0 if (h >> 8) % 2 else -1.0
        n = np.linalg.norm(out[i])
        if n:
            out[i] /= n
    return out


def _between(text: str, start: str, end: str) -> str:
    m = re.search(re.escape(start) + r"(.*?)" + re.escape(end), text, flags=re.S)
    return m.group(1).strip() if m else ""


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 40]


def _props(user: str) -> list[tuple[str, str]]:
    block = _between(user, "<<<PROPOSITIONS", "PROPOSITIONS>>>")
    out = []
    for line in block.splitlines():
        m = re.match(r"\s*-\s*([A-Za-z0-9_.-]+):\s*(.+)", line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def _overlap(a: str, b: str) -> int:
    return len(set(_tokens(a)) & set(_tokens(b)))


def fake_chat(app: str, messages: list[dict]) -> str:
    user = "\n".join(m["content"] for m in messages if m["role"] == "user")
    if app.startswith("claims/extract"):
        text = _between(user, "<<<TEXT", "TEXT>>>")
        page = (_between(user, "PAGE:", "\n") or "").strip() or None
        sents = _sentences(text)[:2]
        return json.dumps([{"claim": s, "quote": s, "page": int(page) if page and page.isdigit() else None,
                            "claim_type": "empirical"} for s in sents])
    if app.startswith("claims/verify"):
        return "SUPPORTED: the quote states the claim."
    if app.startswith("claims/link"):
        claim = _between(user, "<<<CLAIM", "CLAIM>>>")
        best = sorted(((_overlap(claim, s), c) for c, s in _props(user)), reverse=True)
        if best and best[0][0] >= 2:
            stance = "contradicts" if re.search(r"\b(not|no|fails?|against|contrary)\b", claim.lower()) else "supports"
            return json.dumps([{"code": best[0][1], "stance": stance, "reason": "keyword overlap (fake provider)"}])
        return "[]"
    if app.startswith("sweep/screen"):
        item = _between(user, "<<<ITEM", "ITEM>>>")
        score = max([_overlap(item, s) for _, s in _props(user)] or [0])
        return json.dumps({"score": 3 if score >= 4 else 2 if score >= 2 else 0, "challenges": [],
                           "reason": "keyword overlap (fake provider)"})
    if app.startswith("ask/"):
        passages = re.findall(r"\[(\d+)\][^\n]*\n(.+?)(?=\n\[\d+\]|\Z)", _between(user, "<<<PASSAGES", "PASSAGES>>>"),
                              flags=re.S)
        if not passages:
            return "The corpus does not hold material that answers this question."
        n, text = passages[0]
        words = text.split()
        quote = " ".join(words[:12]).strip(" ,;:")
        return f'The closest material in the corpus is [{n}], which says "{quote}" [{n}].'
    if app.startswith("summary"):
        text = _between(user, "<<<TEXT", "TEXT>>>")
        return " ".join(_sentences(text)[:2]) or text[:300]
    return "ready"
