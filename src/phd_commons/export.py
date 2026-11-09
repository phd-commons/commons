"""Exports: Word reports, Excel workbooks, BibTeX and RIS.

Figures render only from registered data tables (CSV files under okf/tables with provenance), never from
numbers a model typed. A figure that names an unknown table is an error.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
from pathlib import Path

from . import __version__

FIG_TOKEN = re.compile(r"\{\{FIG:([A-Za-z0-9_.-]+):(bar|hbar|line|table):([^}]*)\}\}")


# ---------- data tables
def register_table(ws, store, name: str, rows: list[dict], module: str, provenance: str, description: str = "") -> Path:
    if provenance not in ("MEASURED", "DERIVED", "ASSUMED"):
        raise ValueError("provenance must be MEASURED, DERIVED or ASSUMED")
    path = ws.tables / f"{name}.csv"
    if rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    with store.tx() as c:
        c.execute("INSERT INTO data_tables (name, module, as_at, path, provenance, description) VALUES (?,?,?,?,?,?) "
                  "ON CONFLICT(name) DO UPDATE SET module=excluded.module, as_at=excluded.as_at, path=excluded.path, "
                  "provenance=excluded.provenance, description=excluded.description",
                  (name, module, dt.date.today().isoformat(), str(path.relative_to(ws.root)), provenance, description))
    return path


def read_table(ws, store, name: str) -> tuple[list[dict], dict]:
    meta = store.one("SELECT * FROM data_tables WHERE name=?", (name,))
    if meta is None:
        raise KeyError(f"no registered data table '{name}'")
    with open(ws.root / meta["path"], encoding="utf-8") as f:
        return list(csv.DictReader(f)), dict(meta)


def chart_png(rows: list[dict], kind: str, title: str, out: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    keys = list(rows[0].keys())
    labels = [r[keys[0]] for r in rows]
    series = [k for k in keys[1:] if all(_num(r[k]) is not None for r in rows)]
    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=200)
    for s in series:
        vals = [_num(r[s]) for r in rows]
        if kind == "line":
            ax.plot(labels, vals, marker="o", label=s)
        elif kind == "hbar":
            ax.barh(labels, vals, label=s)
        else:
            ax.bar(labels, vals, label=s)
    ax.set_title(title, fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    if len(series) > 1:
        ax.legend(frameon=False, fontsize=8)
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


# ---------- references
def _authors(s) -> list[str]:
    try:
        return json.loads(s["authors_json"] or "[]")
    except (TypeError, ValueError):
        return []


def apa_reference(s) -> str:
    authors = _authors(s)
    if not authors:
        who = s["title"]
    elif len(authors) == 1:
        who = authors[0]
    elif len(authors) <= 20:
        who = ", ".join(authors[:-1]) + ", & " + authors[-1]
    else:
        who = ", ".join(authors[:19]) + ", ... " + authors[-1]
    year = s["year"] or "n.d."
    venue = f" {s['venue']}." if s["venue"] else ""
    link = f" https://doi.org/{s['doi']}" if s["doi"] else (f" {s['url']}" if s["url"] else "")
    title = "" if not authors else f" {s['title']}."
    return f"{who} ({year}).{title}{venue}{link}".replace("..", ".")


def bibtex(sources) -> str:
    out = []
    for s in sources:
        key = re.sub(r"[^a-z0-9]", "", ((_authors(s) or ["anon"])[0].split(",")[0]).lower()) + str(s["year"] or "")
        fields = {"title": s["title"], "author": " and ".join(_authors(s)), "year": s["year"], "journal": s["venue"],
                  "doi": s["doi"], "url": s["url"]}
        body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
        out.append(f"@article{{{key}{s['id']},\n{body}\n}}")
    return "\n\n".join(out) + "\n"


def ris(sources) -> str:
    out = []
    for s in sources:
        lines = ["TY  - JOUR", f"TI  - {s['title']}"] + [f"AU  - {a}" for a in _authors(s)]
        if s["year"]:
            lines.append(f"PY  - {s['year']}")
        if s["venue"]:
            lines.append(f"JO  - {s['venue']}")
        if s["doi"]:
            lines.append(f"DO  - {s['doi']}")
        if s["url"]:
            lines.append(f"UR  - {s['url']}")
        lines.append("ER  - ")
        out.append("\n".join(lines))
    return "\n\n".join(out) + "\n"


# ---------- Word
def _style_doc(doc, ws):
    from docx.shared import Pt, RGBColor, Mm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    hs = ws.get("house_style", {})
    sec = doc.sections[0]
    if hs.get("paper", "A4") == "A4":
        sec.page_width, sec.page_height = Mm(210), Mm(297)
    for m in ("left_margin", "right_margin"):
        setattr(sec, m, Mm(25))
    normal = doc.styles["Normal"]
    normal.font.name = hs.get("font", "Arial")
    normal.font.size = Pt(11)
    if hs.get("justify", True):
        normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    colour = RGBColor.from_string(hs.get("heading_colour", "1F3864"))
    for name in ("Title", "Heading 1", "Heading 2", "Heading 3"):
        st = doc.styles[name]
        st.font.name = hs.get("font", "Arial")
        st.font.color.rgb = colour
        st.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT


def _add_markdownish(doc, text: str):
    for block in re.split(r"\n\s*\n", text.strip()):
        b = block.strip()
        if not b:
            continue
        if b.startswith("|"):
            rows = [[c.strip() for c in r.strip().strip("|").split("|")] for r in b.splitlines()
                    if not re.match(r"^\|?\s*-{2,}", r.strip())]
            rows = [r for r in rows if any(c for c in r)]
            if rows:
                t = doc.add_table(rows=len(rows), cols=max(len(r) for r in rows))
                t.style = "Table Grid"
                for i, r in enumerate(rows):
                    for j, c in enumerate(r):
                        t.cell(i, j).text = c
            continue
        if b.startswith("#"):
            level = min(len(b) - len(b.lstrip("#")), 3)
            doc.add_heading(b.lstrip("# ").strip(), level=level)
            continue
        if all(line.strip().startswith(("-", "*")) for line in b.splitlines()):
            for line in b.splitlines():
                doc.add_paragraph(line.strip()[1:].strip(), style="List Bullet")
            continue
        p = doc.add_paragraph()
        for part in re.split(r"(\*\*[^*]+\*\*)", b.replace("\n", " ")):
            run = p.add_run(part[2:-2] if part.startswith("**") else part)
            run.bold = part.startswith("**")


def answer_report(ws, store, answer, title: str | None = None, out: Path | None = None) -> Path:
    from docx import Document
    from docx.shared import Mm
    doc = Document()
    _style_doc(doc, ws)
    title = title or answer.question
    doc.add_heading(title, level=0)
    proj = ws.get("project.title") or ""
    meta = doc.add_paragraph(f"{proj}  ·  {dt.date.today().isoformat()}  ·  mode: {answer.mode}")
    meta.runs[0].italic = True
    doc.add_heading("Question", level=1)
    doc.add_paragraph(answer.question)
    doc.add_heading("Answer", level=1)
    body = answer.text
    figures = FIG_TOKEN.findall(body)
    body = FIG_TOKEN.sub("", body)
    _add_markdownish(doc, body)
    for n, (table, kind, ftitle) in enumerate(figures, 1):
        rows, tmeta = read_table(ws, store, table)  # KeyError if the model invented a table
        img = ws.exports / f"fig-{dt.datetime.now():%Y%m%d%H%M%S}-{n}.png"
        if kind == "table":
            _add_markdownish(doc, "| " + " | ".join(rows[0].keys()) + " |\n" +
                             "\n".join("| " + " | ".join(str(v) for v in r.values()) + " |" for r in rows))
        else:
            chart_png(rows, kind, ftitle, img)
            doc.add_picture(str(img), width=Mm(150))
        doc.add_paragraph(f"Figure {n}. {ftitle}. Source: table {table} ({tmeta['provenance']}, as at {tmeta['as_at']}).")
    if answer.problems:
        doc.add_heading("Checks that did not pass", level=1)
        for pr in answer.problems:
            doc.add_paragraph(pr, style="List Bullet")
    doc.add_heading("Sources cited", level=1)
    cited = sorted(answer.cited_numbers())
    seen = set()
    for n in cited:
        if 1 <= n <= len(answer.passages):
            p = answer.passages[n - 1]
            s = store.one("SELECT * FROM sources WHERE id=?", (p["source_id"],))
            page = f", p. {p['page_from']}" if p.get("page_from") else ""
            doc.add_paragraph(f"[{n}] {apa_reference(s)}{page}")
            seen.add(s["id"])
    doc.add_heading("Provenance", level=1)
    tiers = sorted({p["tier"] for p in answer.passages})
    calls = store.q("SELECT role, provider, model, locality FROM model_calls WHERE app LIKE 'ask/%' "
                    "ORDER BY id DESC LIMIT 2")
    models = "; ".join(f"{c['role']}: {c['model']} ({c['locality']})" for c in calls)
    doc.add_paragraph(f"Generated by Commons {__version__} on {dt.datetime.now():%Y-%m-%d %H:%M}. "
                      f"Passages retrieved: {len(answer.passages)}. Tiers present: {', '.join(tiers) or 'none'}. "
                      f"Models: {models or 'n/a'}. This text is MODEL-DRAFTED from cited passages; it is not evidence "
                      "in itself and must be checked against the sources before use.")
    out = out or ws.exports / f"report-{dt.datetime.now():%Y%m%d-%H%M%S}.docx"
    doc.save(str(out))
    if seen:
        srcs = store.q(f"SELECT * FROM sources WHERE id IN ({','.join('?' for _ in seen)})", list(seen))
        out.with_suffix(".bib").write_text(bibtex(srcs), encoding="utf-8")
        out.with_suffix(".ris").write_text(ris(srcs), encoding="utf-8")
    return out


# ---------- Excel
def workbook(ws, store, tables: list[str], out: Path | None = None, extra_rows: dict | None = None) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    wb.remove(wb.active)
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor=ws.get("house_style.heading_colour", "1F3864"))
    prov = wb.create_sheet("Provenance")
    prov.append(["table", "module", "as_at", "provenance", "description"])
    def put(name, rows):
        sh = wb.create_sheet(name[:31])
        if not rows:
            return
        sh.append(list(rows[0].keys()))
        for cell in sh[1]:
            cell.font, cell.fill = head_font, head_fill
        for r in rows:
            sh.append([_num(v) if _num(v) is not None else v for v in r.values()])
    for t in tables:
        rows, meta = read_table(ws, store, t)
        put(t, rows)
        prov.append([t, meta["module"], meta["as_at"], meta["provenance"], meta["description"]])
    for name, rows in (extra_rows or {}).items():
        put(name, rows)
    for cell in prov[1]:
        cell.font, cell.fill = head_font, head_fill
    out = out or ws.exports / f"workbook-{dt.datetime.now():%Y%m%d-%H%M%S}.xlsx"
    wb.save(str(out))
    return out


def answer_workbook(ws, store, answer, out: Path | None = None) -> Path:
    rows = []
    for i, p in enumerate(answer.passages, 1):
        rows.append({"n": i, "title": p["title"], "year": p.get("year"), "page": p.get("page_from"), "tier": p["tier"],
                     "cited": "yes" if i in answer.cited_numbers() else "no", "passage": p["text"][:2000]})
    tables = [t for t, *_ in FIG_TOKEN.findall(answer.text)]
    return workbook(ws, store, tables, out, extra_rows={"Passages": rows,
                                                        "Answer": [{"question": answer.question, "answer": answer.text}]})
