# Architecture

```
            portal (FastAPI, 127.0.0.1:8700)    commons CLI    MCP server (stdio)
                              \                     |               /
                               +----------- phd_commons -----------+
   ingest · claims · thesis · ask · sweep · export · analysis · doctor · schedule · maintenance
                                            |
        +------------------+----------------+-----------------+------------------------+
        |                  |                                  |                        |
   okf/ (Markdown,    library/ (originals,           data/commons.db            model router
   source of truth)   content-addressed)             SQLite: FTS5 + vectors,    roles → providers,
                                                     registers, audit log       tier policy enforced
```

## Code and data are separate

The package (`src/phd_commons`) holds no research data. A workspace holds one thesis: `commons.yaml`,
`thesis.yaml`, `sources.yaml`, `okf/`, `library/`, `inbox/`, `analyses/` and the derived `data/`. Upgrading Commons
never touches a workspace. `commons rebuild` recreates the database from the Markdown and the originals into a new
file and swaps it in only if no source or verified claim would be lost; the audit log, review queue, data tables
and feed state are carried over from the old database. Keep backups of `data/` all the same: the audit log lives
only there.

## Modules

| Module | Does |
|---|---|
| `config.py` | Finds and loads the workspace; defaults |
| `llm.py` | The router: roles, providers, locality policy, audit logging, OpenAI-compatible and Anthropic wire formats |
| `store.py` | SQLite schema, FTS5, vector search (numpy over a cached matrix), counts |
| `ingest.py` | Hashing, tier rules, text extraction with pages (PyMuPDF, optional Docling), chunking, quarantine |
| `claims.py` | Extraction, mechanical quote check, verification, linking, review resolution |
| `thesis.py` | Loads `thesis.yaml`, the evidence board |
| `ask.py` | Hybrid retrieval (BM25 and vectors fused by reciprocal rank), grounded answers, citation checks |
| `sweep.py` | Feed adapters (OpenAlex, Crossref, arXiv, RSS), screening, digests |
| `export.py` | Data tables, Word, Excel, BibTeX, RIS |
| `analysis.py` | The analysis-module contract, built-ins, stamps |
| `okf.py` | Source notes, the claim register, the log, the index |
| `doctor.py`, `safety.py` | Health and safety checks |
| `schedule.py` | launchd, systemd and Task Scheduler entries, no admin rights |
| `maintenance.py` | Rebuild, backup, purge |
| `portal/`, `cli.py`, `mcp_server.py` | Front ends, with no business logic of their own |

## Scale

Vector search is a scan over an in-memory matrix: comfortably fast for a doctoral corpus of tens of thousands of
chunks, and it works on every platform without SQLite extensions. Past a few hundred thousand chunks, a dedicated
vector index would be the next step.

## Tests

`pytest` runs the whole pipeline with the deterministic fake provider and mock HTTP transports: no network, no
GPU, no models.
