# Changelog

## 0.1.2 (2026-11-10)

Found by running the full pipeline against a Qwen fleet:

- Claim extraction no longer sees your propositions. Shown them, models kept only claims they judged relevant
  and often returned nothing; relevance is now judged only in the linking step.
- Evidence links returned as a single JSON object, rather than an array, were silently dropped. They are kept.
- `thinking: off` for reasoning models, with a retry when a reply comes back empty.
- Crossref records with no abstract are filled from OpenAlex, including an open-access PDF where one exists.

## 0.1.1 (2026-11-09)

- `commons mcp install claude-desktop | claude-code | print` registers the MCP server with one command.
- New MCP tools: `ask_corpus` (grounded answers from your local author model), `thesis_board`,
  `add_published_work` (by DOI) and `corpus_status`; server instructions tell assistants to cite and to say when
  the corpus does not hold something.
- Fixes from the pre-release review: tier floors, scrubbed backups, safe rebuild, portal origin checks, and more.

## 0.1.0 (2026-11-09)

First public release.

- Workspaces with a plain-Markdown knowledge base (OKF) as the source of truth, and `commons rebuild`.
- Bring your own LLM: role-based router for OpenAI-compatible servers, Anthropic and local sentence-transformers,
  with locality labels (local, institutional, cloud) and enforced tier policy.
- Ingest of PDF, Word, HTML, Markdown and audio (local transcription), with quarantine on protective markings.
- Claims with mechanical quote checks, cross-family verification and a review queue.
- Propositions and rivals, evidence links and the thesis board.
- Daily sweep (OpenAlex, Crossref, arXiv, RSS), relevance screening that keeps challenging work, digests.
- Grounded Ask with citation checks and four modes; Word, Excel, BibTeX and RIS exports.
- Analysis-module contract with stamps; two built-ins.
- Portal, CLI, MCP server, doctor, schedules for macOS, Linux and Windows without admin rights, backup and purge.
- Agent layer: AGENTS.md, CLAUDE.md and setup and analysis skills in every workspace.
