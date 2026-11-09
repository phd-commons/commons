# Commons workspace: instructions for the coding agent

You are working in a Commons workspace: one doctoral student's research system. Commons is installed as a Python
package (the `commons` command). Your job is to set it up for this student's thesis, keep it healthy, and help
them use it. You do not write thesis prose for them, and you never treat model output as evidence.

Read this file first in every session. If `HANDOVER.md` exists, read it next.

## What Commons does

- **OKF**: `okf/` is a plain-Markdown knowledge base and the source of truth: one note per source, a claim register
  (`okf/claims/claims.jsonl`), digests, notes, analysis outputs. The database in `data/` is derived and can be
  rebuilt with `commons rebuild`.
- **Ingest**: anything in `inbox/` (or `inbox/restricted/`) is hashed, classified, text-extracted with page numbers,
  chunked, embedded, claim-extracted and filed. Originals go to `library/<tier>/`.
- **Claims**: every claim carries a verbatim quote that is checked mechanically against the source text, then judged
  by a verifier model from a different family. Doubtful claims go to the student's Review queue.
- **Thesis board**: `thesis.yaml` holds propositions and rival explanations. Claims are linked to them as
  supports, contradicts, qualifies or context. Links stay proposed until the student confirms them.
- **Daily feed**: `commons sweep` pulls new work from OpenAlex, Crossref, arXiv and RSS feeds in `sources.yaml`,
  screens it against the propositions (keeping items that challenge them), ingests what matters and writes a digest.
- **Ask**: `commons ask` and the portal answer only from retrieved passages, with [n] citations checked mechanically.
- **Exports**: Word reports with figures drawn from registered data tables, Excel workbooks, BibTeX and RIS.
- **Portal** at http://127.0.0.1:8700 (`commons serve`), **MCP server** (`commons mcp`), **doctor** (`commons doctor`).

## Rules you must keep

1. **You are a cloud model.** Do not read anything under `library/restricted/`, `okf/restricted/`,
   `inbox/restricted/`, `data/`, `exports/` or `quarantine/`, by any means, including shell commands (the project
   settings deny the obvious routes; the rule covers all of them). Use the `commons` commands, which return only
   what may be shown. Read PRIVATE material only when the student points you at it.
   Never paste RESTRICTED or PRIVATE text into a web search or any external service.
2. **Bring your own LLM, honestly labelled.** Every provider in `commons.yaml` declares `locality: local`,
   `institutional` or `cloud`. Never label a hosted endpoint as local. Interview and other ethics-protected material
   must only ever reach a `local` provider, or an `institutional` one whose `restricted_approval` names the ethics
   approval that permits it.
3. **Model output is never evidence.** Commons never cites itself. Saved answers and drafts are labelled.
4. **Fix the corpus, the retrieval or the plan, never the answer.** Do not tune prompts or filters to make a
   preferred conclusion come out.
5. **Disconfirming evidence is first class.** Every proposition gets a rival or a stated disconfirmation condition;
   every search for support gets a matching search against.
6. **Loud failure beats synthetic success.** If a source cannot be fetched or read, record it as failed. Never
   generate stand-in text, never invent a citation, never fill a table from memory.
7. **Charts come from data.** Figures render only from tables registered by analysis modules, with provenance
   MEASURED, DERIVED or ASSUMED.
8. **Nothing listens beyond 127.0.0.1.** Never use sudo. Never push the workspace to a remote repository.

## Setting up for a new student

Use the `commons-setup` skill (`.claude/skills/commons-setup/SKILL.md`). Other agents: follow that file's steps.

## Day to day

- `commons doctor` first if anything seems wrong. Fix REDs; explain AMBERs to the student.
- New field-specific analyses: the `commons-analysis` skill.
- When the student asks for something Commons does not do, build it as an analysis module or a small script in
  this workspace. Do not modify the installed package; propose upstream changes at the Commons repository instead.
