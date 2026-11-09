# Use your corpus from Claude or any other assistant

Commons includes an MCP server, so any assistant that speaks the Model Context Protocol can search your corpus,
ask it questions, read your thesis board and add published work, while Commons keeps control of what it is shown.

## Register it

From your workspace:

```bash
commons mcp install claude-desktop    # Claude Desktop: writes the entry, keeps a backup of your config
commons mcp install claude-code       # Claude Code: runs `claude mcp add` at user scope
commons mcp install print             # anything else: prints the JSON entry to paste in
```

Then restart the client. In Claude Desktop the tools appear under the connectors menu; in Claude Code, `claude mcp
list` shows `commons`.

For Cursor, Windsurf, VS Code, Continue, Zed, or any other MCP client, paste the printed entry into its MCP settings.
The server runs over stdio: the client starts `commons mcp -w <your workspace>` itself.

## What the assistant can do

| Tool | Does |
|---|---|
| `search_corpus` | Hybrid search; returns passages with source, year, page and tier |
| `ask_corpus` | A grounded answer written by your own local author model, with [n] citations, or "the corpus does not hold this". Modes: answer, devil, compare, notes |
| `read_source` | The extracted text and metadata of one source |
| `thesis_board` | Evidence for and against each proposition and rival (only if you allow PRIVATE) |
| `list_propositions`, `evidence` | Your propositions, and the verified claims linked to one |
| `latest_digest` | This morning's research digest (only if you allow PRIVATE) |
| `add_published_work` | Add a paper by DOI: open-access full text where a lawful copy exists, otherwise the abstract; claims are extracted and verified |
| `add_note` | Save a note to `okf/notes/`, labelled as agent-written; never treated as evidence |
| `corpus_status` | Counts, and which tiers this client may see |

The server also tells the assistant how to behave: cite what Commons returns, say when the corpus does not hold
something, and never pass off its own knowledge as coming from your corpus.

## What it is allowed to see

Treat every MCP client as a cloud model, because most are. By default the server serves **PUBLIC** material only:
published literature, legislation and public data. Your propositions, notes and drafts are PRIVATE, and are served
only if you set `mcp: {private: true}` in `commons.yaml`. Interview data and anything else RESTRICTED is never
served, whatever the setting.

`ask_corpus` answers with your local author model, so the passages it reads never leave your machine; only the
finished answer goes back to the client, built from material the client is allowed to see.

## Using Commons with no local models at all

If your machine is small, you can let a hosted model do the reading for published material and keep everything
else local: see the `hosted` and `anthropic` presets in [models.md](models.md).
