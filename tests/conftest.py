"""Test fixtures: a demo workspace (fake provider) and synthetic documents. All text below is invented."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "heat-health"

DOC_A = """Heat and emergency admissions in three cities (synthetic test document)

Emergency hospital admissions rose by 7 per cent on days above the city heat threshold after adjusting for season and air pollution.

The largest relative risks were found among people over 75 and among people living alone, who accounted for most excess admissions.

Admissions fell below the seasonal baseline in the week after each heatwave, which suggests some harvesting of admissions that would have occurred anyway.
"""

DOC_B = """Evaluating heat health warnings (synthetic test document)

Cities that introduced heat health warning systems showed a flatter dose response curve in the five years after introduction.

However the same flattening appeared in comparison cities without warning systems, which points to general adaptation rather than the warnings themselves.

Tree canopy was not protective once household income and housing quality were controlled in the small area models.
"""

DOC_MARKED = """PROTECTED

Internal briefing on hospital capacity planning. This text is synthetic and exists only to test quarantine rules.
It contains enough words to pass the minimum length check for extraction so that the marking scan is what stops it.
""" + ("Additional filler sentence for length. " * 20)


def make_pdf(path: Path, text: str) -> Path:
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=10)
    doc.save(str(path))
    doc.close()
    return path


def make_docx(path: Path, text: str) -> Path:
    import docx
    d = docx.Document()
    for para in text.split("\n\n"):
        d.add_paragraph(para.strip())
    d.save(str(path))
    return path


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    from phd_commons.config import load_workspace
    from phd_commons.workspace import init_workspace
    monkeypatch.setenv("COMMONS_ALLOW_RESTRICTED_UNENCRYPTED", "1")
    monkeypatch.delenv("COMMONS_HOME", raising=False)
    root, _ = init_workspace(tmp_path / "ws", preset="demo", title="Test thesis")
    shutil.copy(EXAMPLE / "thesis.yaml", root / "thesis.yaml")
    shutil.copy(EXAMPLE / "sources.yaml", root / "sources.yaml")
    return load_workspace(root)


@pytest.fixture()
def ctx(ws):
    from phd_commons.llm import Router
    from phd_commons.store import open_store
    store = open_store(ws)
    return ws, store, Router(ws, store)


@pytest.fixture()
def docs(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    return {
        "a": make_pdf(d / "heat-admissions.pdf", DOC_A),
        "b": make_docx(d / "warnings.docx", DOC_B),
        "marked": make_pdf(d / "briefing.pdf", DOC_MARKED),
    }
