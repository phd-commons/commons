"""Prompt builders. Plain functions, no str.format on templates (JSON braces break it).

Markers such as <<<TEXT ... TEXT>>> delimit material so replies can be checked mechanically.
"""

from __future__ import annotations

HOUSE = (
    "Write plain sentences in the user's language variety. Lead with the answer. No promotional adjectives. "
    "Hedge only where the evidence is contested, and then say which way it leans and why."
)


def props_block(props: list[dict]) -> str:
    lines = [f"- {p['code']}: {(p.get('statement') or p.get('title') or '').strip()}" for p in props]
    return "<<<PROPOSITIONS\n" + "\n".join(lines) + "\nPROPOSITIONS>>>"


def extract_claims(text: str, page: int | None, props: list[dict], max_claims: int) -> list[dict]:
    return [
        {"role": "system", "content": (
            "You extract verifiable claims from research documents for a doctoral student. "
            "A claim is a single statement the source makes (a finding, a figure, a legal provision, a theoretical "
            "proposition or an argued position). Every claim must come with a VERBATIM quote copied character for "
            "character from the text that states it. Never paraphrase inside the quote. Extract claims that cut "
            "against the student's propositions as readily as claims that support them. "
            "Return only a JSON array.")},
        {"role": "user", "content": (
            f"Extract at most {max_claims} important claims from the text below.\n"
            "Return a JSON array of objects with keys: claim, quote, page, claim_type "
            "(one of empirical, statistic, legal, theoretical, normative).\n"
            "If the text holds no substantive claim, return [].\n\n"
            f"PAGE: {page if page is not None else ''}\n"
            f"The student's propositions, for context only:\n{props_block(props)}\n\n"
            f"<<<TEXT\n{text}\nTEXT>>>")},
    ]


def verify_claim(claim: str, quote: str) -> list[dict]:
    return [
        {"role": "system", "content": (
            "You are a sceptical verifier. Judge only whether the quote, read on its own, supports the claim exactly "
            "as stated. Answer with one label, then a colon and one short reason: SUPPORTED, OVERSTATED (the claim "
            "goes further than the quote) or NOT_SUPPORTED.")},
        {"role": "user", "content": f"<<<CLAIM\n{claim}\nCLAIM>>>\n<<<QUOTE\n{quote}\nQUOTE>>>"},
    ]


def link_claim(claim: str, quote: str, props: list[dict]) -> list[dict]:
    return [
        {"role": "system", "content": (
            "You map evidence to a doctoral student's propositions. For each proposition the claim bears on, give a "
            "stance: supports, contradicts, qualifies or context. Only include propositions it genuinely bears on; "
            "an empty list is a good answer. Rival explanations are propositions too. Return only a JSON array of "
            "objects with keys code, stance, reason.")},
        {"role": "user", "content": (
            f"{props_block(props)}\n\n<<<CLAIM\n{claim}\nCLAIM>>>\n<<<QUOTE\n{quote}\nQUOTE>>>")},
    ]


def screen_item(title: str, abstract: str, props: list[dict]) -> list[dict]:
    return [
        {"role": "system", "content": (
            "You screen new publications for a doctoral student. Score relevance to the propositions from 0 (none) "
            "to 3 (central). Items that challenge or contradict a proposition are as valuable as items that support "
            "it: list the codes they challenge. Return only JSON: {\"score\": n, \"challenges\": [codes], "
            "\"reason\": \"one line\"}.")},
        {"role": "user", "content": f"{props_block(props)}\n\n<<<ITEM\n{title}\n\n{abstract}\nITEM>>>"},
    ]


MODES = {
    "answer": "Answer the question from the passages.",
    "devil": (
        "Act as a hostile but fair examiner. Make the strongest case AGAINST the position in the question, using "
        "only the passages, including any rival explanations they support."
    ),
    "compare": "Answer as a comparison table (markdown) with one cited cell per comparison point, then two sentences.",
    "notes": "Draft reading notes the student will rewrite in their own words. Label them MODEL-DRAFTED at the top.",
}


def answer(question: str, passages: list[dict], mode: str = "answer", tables: list[dict] | None = None) -> list[dict]:
    blocks = []
    for i, p in enumerate(passages, 1):
        where = f"p. {p['page_from']}" if p.get("page_from") else ""
        blocks.append(f"[{i}] {p['title']} ({p.get('year') or 'n.d.'}) {where} [{p['tier']}]\n{p['text']}")
    fig = ""
    if tables:
        names = "\n".join(f"- {t['name']}: {t.get('description') or ''} ({t['provenance']})" for t in tables)
        fig = ("\n\nIf a chart would help, insert a figure token on its own line, exactly "
               "{{FIG:<table name>:<bar|hbar|line|table>:<title>}}, using ONLY these stored tables:\n" + names)
    return [
        {"role": "system", "content": (
            "You answer a doctoral student's questions strictly from the numbered passages provided. Rules: "
            "cite every factual sentence with [n]; quote exactly when quoting; use no outside knowledge; if the "
            "passages do not answer the question, say plainly that the corpus does not hold it and say what it does "
            "hold; if the passages disagree, say so and say which way the weight lies. " + HOUSE)},
        {"role": "user", "content": (
            f"Mode: {MODES.get(mode, MODES['answer'])}\n\nQuestion: {question}\n\n"
            "<<<PASSAGES\n" + "\n\n".join(blocks) + "\nPASSAGES>>>" + fig)},
    ]


def summarise(text: str) -> list[dict]:
    return [
        {"role": "system", "content": "Summarise the document in three to five plain sentences. No evaluation."},
        {"role": "user", "content": f"<<<TEXT\n{text[:12000]}\nTEXT>>>"},
    ]
