"""Ingest: hash, classify the tier, extract text with page numbers, chunk, embed, write the source note.

Failures are loud: a document with no extractable text is recorded as failed with the reason, never padded.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from .okf import write_source_note, append_log, slugify

TEXT_EXT = {".md", ".txt", ".markdown", ".rst"}
DOC_EXT = {".pdf", ".docx", ".html", ".htm"} | TEXT_EXT
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".mp4", ".webm"}
MIN_CHARS = 400


@dataclass
class IngestResult:
    status: str
    source_id: int | None
    slug: str | None
    message: str
    chunks: int = 0


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---------- text extraction: returns list of (page_number or None, text)
def extract_pages(path: Path) -> list[tuple[int | None, str]]:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _pdf(path)
    if ext == ".docx":
        return _docx(path)
    if ext in (".html", ".htm"):
        return [(None, _html(_read_text(path)))]
    if ext in TEXT_EXT:
        return [(None, _read_text(path))]
    if ext in AUDIO_EXT:
        return [(None, _transcribe(path))]
    raise ValueError(f"unsupported file type {ext}")


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _pdf(path: Path):
    try:
        from docling.document_converter import DocumentConverter  # optional, better layout and OCR
        doc = DocumentConverter().convert(str(path)).document
        pages: dict[int, list[str]] = {}
        for item, _ in doc.iterate_items():
            text = getattr(item, "text", "") or ""
            prov = getattr(item, "prov", None) or []
            pg = prov[0].page_no if prov else None
            if text:
                pages.setdefault(pg, []).append(text)
        out = [(pg, "\n".join(t)) for pg, t in sorted(pages.items(), key=lambda kv: kv[0] or 0)]
        if sum(len(t) for _, t in out) >= MIN_CHARS:
            return out
    except Exception:  # noqa: BLE001 - docling is optional; fall through
        pass
    import pymupdf
    with pymupdf.open(path) as doc:
        return [(i + 1, page.get_text("text")) for i, page in enumerate(doc)]


def _docx(path: Path):
    import docx
    d = docx.Document(str(path))
    paras = [p.text for p in d.paragraphs if p.text.strip()]
    for table in d.tables:
        for row in table.rows:
            paras.append(" | ".join(c.text.strip() for c in row.cells))
    return [(None, "\n\n".join(paras))]


def _html(html: str) -> str:
    try:
        import trafilatura
        text = trafilatura.extract(html, include_tables=True) or ""
        if len(text) >= MIN_CHARS:
            return text
    except Exception:  # noqa: BLE001
        pass
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n"))


def _transcribe(path: Path) -> str:
    """Local transcription only. Audio is treated as RESTRICTED by the caller unless told otherwise."""
    try:
        import mlx_whisper
        return mlx_whisper.transcribe(str(path), path_or_hf_repo="mlx-community/whisper-large-v3-turbo")["text"]
    except ImportError:
        pass
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("large-v3", device="auto", compute_type="auto")
        segments, _ = model.transcribe(str(path))
        return "\n".join(s.text.strip() for s in segments)
    except ImportError as e:
        raise RuntimeError("No local transcriber: install 'phd-commons[audio]' or 'phd-commons[audio-mac]'") from e


# ---------- normalisation and chunking
def normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("­", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # line-break hyphenation
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def approx_tokens(text: str) -> int:
    return int(len(text.split()) * 1.3) + 1


def chunk_pages(pages: list[tuple[int | None, str]], target: int = 900, overlap: int = 120) -> list[dict]:
    """Paragraph-aware chunks of about `target` tokens that remember the pages they span."""
    paras: list[tuple[int | None, str]] = []
    for pg, text in pages:
        for para in re.split(r"\n\s*\n", normalise(text)):
            para = para.strip()
            if para:
                paras.append((pg, para))
    chunks, cur, cur_pages, cur_tok = [], [], [], 0
    for pg, para in paras:
        t = approx_tokens(para)
        if cur and cur_tok + t > target:
            chunks.append({"text": "\n\n".join(cur), "page_from": cur_pages[0], "page_to": cur_pages[-1]})
            tail, tail_tok = [], 0
            for p in reversed(cur):  # overlap: carry trailing paragraphs
                tail_tok += approx_tokens(p)
                if tail_tok > overlap:
                    break
                tail.insert(0, p)
            cur, cur_pages, cur_tok = tail, cur_pages[-len(tail):] if tail else [], sum(approx_tokens(p) for p in tail)
        if t > target * 1.5:  # very long paragraph: split by sentences
            for piece in _split_long(para, target):
                chunks.append({"text": piece, "page_from": pg, "page_to": pg})
            continue
        cur.append(para)
        cur_pages.append(pg)
        cur_tok += t
    if cur:
        chunks.append({"text": "\n\n".join(cur), "page_from": cur_pages[0], "page_to": cur_pages[-1]})
    return chunks


def _split_long(text: str, target: int) -> list[str]:
    sents = re.split(r"(?<=[.!?])\s+", text)
    out, cur = [], []
    for s in sents:
        if cur and approx_tokens(" ".join(cur + [s])) > target:
            out.append(" ".join(cur))
            cur = []
        cur.append(s)
    if cur:
        out.append(" ".join(cur))
    return out


# ---------- tier classification
def scan_markings(ws, text: str) -> list[str]:
    hits = []
    head_tail = text[:6000] + "\n" + text[-3000:]
    for m in ws.get("tiers.quarantine_markings", []):
        if re.search(r"(^|\W)" + re.escape(m) + r"(\W|$)", head_tail):
            hits.append(m)
    lowered = text.lower()
    for p in ws.get("tiers.quarantine_phrases", []) + ws.get("tiers.blocked_names", []):
        if p and p.lower() in lowered:
            hits.append(p)
    return hits


VALID_TIERS = ("PUBLIC", "PRIVATE", "RESTRICTED")
RANK = {t: i for i, t in enumerate(VALID_TIERS)}


def tier_floor(ws, path: Path) -> str:
    """The lowest tier a file may have, from where it sits and what it is. Explicit choices cannot go below it."""
    restricted_dir = os.path.abspath(ws.inbox / "restricted")
    if os.path.abspath(path).startswith(restricted_dir + os.sep):
        return "RESTRICTED"
    if path.suffix.lower() in AUDIO_EXT:
        return "RESTRICTED"
    return "PUBLIC"


def default_tier(ws, path: Path, explicit: str | None) -> str:
    if explicit is not None and str(explicit).upper() not in VALID_TIERS:
        raise ValueError(f"invalid tier '{explicit}': use PUBLIC, PRIVATE or RESTRICTED")
    chosen = str(explicit).upper() if explicit else "PRIVATE"
    floor = tier_floor(ws, path)
    return chosen if RANK[chosen] >= RANK[floor] else floor


def _label(slug: str, sid, tier: str) -> str:
    """What goes in the shared log: never a RESTRICTED file's name."""
    return f"source {sid} (RESTRICTED)" if tier == "RESTRICTED" else slug


# ---------- main entry
def ingest_file(ws, store, router, path: Path, tier: str | None = None, meta: dict | None = None,
                move: bool = False, extract_claims: bool = True, min_chars: int = MIN_CHARS,
                source_id: int | None = None) -> IngestResult:
    from .claims import process_source_claims
    from .safety import restricted_blocked_reason

    path = Path(path)
    meta = dict(meta or {})
    if not path.exists():
        return IngestResult("failed", None, None, f"not found: {path}")
    if path.is_symlink():
        return IngestResult("refused", None, None, "symbolic links are not ingested; copy the file in instead")
    try:
        tier = default_tier(ws, path, tier)
    except ValueError as e:
        return IngestResult("refused", None, None, str(e))
    digest = sha256_file(path)
    existing = store.one("SELECT id, slug, status FROM sources WHERE sha256=?", (digest,))
    if existing and existing["status"] in ("failed",):
        with store.tx() as c:  # a retry of a failed ingest replaces the failure record
            c.execute("DELETE FROM sources WHERE id=?", (existing["id"],))
        existing = None
    if existing:
        if move:
            path.unlink(missing_ok=True)
        return IngestResult("duplicate", existing["id"], existing["slug"], f"already {existing['status']}")

    if tier == "RESTRICTED":
        reason = restricted_blocked_reason(ws)
        if reason:
            return IngestResult("refused", None, None, f"RESTRICTED material refused: {reason}")

    title = meta.get("title") or path.stem.replace("_", " ").replace("-", " ").strip()
    year = meta.get("year")
    slug = slugify(f"{(meta.get('authors') or ['x'])[0].split(',')[0] if meta.get('authors') else ''}-{year or ''}-{title}")
    n = 1
    base_slug = slug
    while store.one("SELECT 1 FROM sources WHERE slug=?", (slug,)):
        n += 1
        slug = f"{base_slug}-{n}"

    # store the original, content-addressed
    dest_dir = ws.library_dir(tier)
    dest = dest_dir / f"{digest[:16]}{path.suffix.lower()}"
    if not dest.exists():
        shutil.copy2(path, dest)

    common = dict(slug=slug, kind=meta.get("kind", _guess_kind(path)), title=title, authors=meta.get("authors", []),
                  year=year, venue=meta.get("venue"), doi=meta.get("doi"), url=meta.get("url"),
                  licence=meta.get("licence"), tier=tier, sha256=digest, path_original=str(dest.relative_to(ws.root)),
                  published_at=meta.get("published_at"), origin_feed=meta.get("origin_feed"),
                  abstract=meta.get("abstract"))
    if source_id is not None:
        common["id"] = source_id
    try:
        pages = extract_pages(path)
    except Exception as e:  # noqa: BLE001
        sid = store.add_source(**common, status="failed", fail_reason=f"extraction error: {e}")
        append_log(ws, f"ingest FAILED {_label(slug, sid, tier)}: extraction error: {e}")
        return IngestResult("failed", sid, slug, str(e))

    full = normalise("\n\n".join(t for _, t in pages))
    hits = scan_markings(ws, full)
    if hits:
        qdest = ws.quarantine / f"{digest[:8]}-{path.name}"
        shutil.move(str(dest), qdest) if dest.exists() else None
        common["path_original"] = str(qdest.relative_to(ws.root))
        sid = store.add_source(**common, status="quarantined", fail_reason="markings: " + ", ".join(hits))
        store.add_review("quarantine", sid, {"file": path.name if tier != "RESTRICTED" else f"source {sid}",
                                             "markings": hits}, tier=tier)
        append_log(ws, f"ingest QUARANTINED {_label(slug, sid, tier)}: {', '.join(hits)}")
        if move:
            path.unlink(missing_ok=True)
        return IngestResult("quarantined", sid, slug, "protective markings found: " + ", ".join(hits))

    if len(full) < min_chars:
        sid = store.add_source(**common, status="failed",
                               fail_reason=f"thin text ({len(full)} chars): scanned, empty or a script-only page")
        append_log(ws, f"ingest FAILED {_label(slug, sid, tier)}: thin text")
        return IngestResult("failed", sid, slug, "too little extractable text; try OCR (docling extra) or another copy")

    text_dir = ws.okf / "restricted" / "text" if tier == "RESTRICTED" else ws.data / "text"
    text_path = text_dir / f"{digest[:16]}.txt"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(full, encoding="utf-8")
    common["path_text"] = str(text_path.relative_to(ws.root))

    chunks = chunk_pages(pages, ws.get("chunking.target_tokens", 900), ws.get("chunking.overlap_tokens", 120))
    vectors = router.embed([c["text"] for c in chunks], app="ingest/embed", tier=tier)
    sid = store.add_source(**common, status="ingested")
    store.add_chunks(sid, tier, chunks, router.embed_model_id(tier), vectors)

    msg = "ok"
    if extract_claims:
        st = process_source_claims(ws, store, router, sid)
        if st.get("failed_chunks"):
            msg = f"ok, but claim extraction failed on {st['failed_chunks']} chunks (see Review; retry with commons claims {sid})"
    write_source_note(ws, store, sid)
    append_log(ws, f"ingest {_label(slug, sid, tier)}: {len(chunks)} chunks, tier {tier}")
    if move:
        path.unlink(missing_ok=True)
    return IngestResult("ingested", sid, slug, msg, len(chunks))


def _guess_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in AUDIO_EXT:
        return "interview"
    if ext in (".html", ".htm"):
        return "web"
    if ext in TEXT_EXT:
        return "note"
    return "document"


def ingest_inbox(ws, store, router) -> list[IngestResult]:
    results = []
    for p in sorted(ws.inbox.rglob("*")):
        if p.is_file() and not p.name.startswith(".") and (p.suffix.lower() in DOC_EXT | AUDIO_EXT):
            sidecar = p.with_suffix(p.suffix + ".json")
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}
            except (ValueError, OSError):
                meta = {}
            res = ingest_file(ws, store, router, p, tier=meta.pop("tier", None), meta=meta, move=True)
            results.append(res)
            if res.status != "refused":
                sidecar.unlink(missing_ok=True)
        elif p.is_file() and p.suffix.lower() not in (".json",) and not p.name.startswith("."):
            shutil.move(str(p), ws.quarantine / f"{int(time.time())}-{p.name}")
            store.add_review("unsupported_file", None, {"file": p.name})
            results.append(IngestResult("failed", None, None, f"unsupported file type, moved to quarantine: {p.name}"))
    if results:
        append_log(ws, f"inbox run {time.strftime('%Y-%m-%d %H:%M')}: {len(results)} files")
    return results
