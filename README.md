# Commons

**A local-first research system for doctoral students. Bring your own LLM.**

A doctorate asks you to read more than you can hold in your head, to keep track of what every source actually
says, and to test your argument against the evidence that cuts against it. General-purpose chatbots make this
harder, not easier: they paraphrase loosely, invent citations, and cannot be trusted with interview data or other
material your ethics approval protects.

Commons is built for that work. It runs on your own computer, with whichever models you choose, and it keeps
every claim tied to a verbatim quote and a page number.

## What it does

- **Keeps a knowledge base you own.** Every paper, report, Act, dataset and note you add becomes a plain-Markdown
  source note with its verified claims. The Markdown is the source of truth; the search index is rebuilt from it.
- **Checks every claim mechanically.** A claim enters the record only if its quote appears word for word in the
  source. A second model from a different family then judges whether the quote supports the claim. Doubtful
  claims go to a review queue for you, not into your evidence.
- **Tests your thesis.** You state your propositions and the rival explanations an examiner would offer. Commons
  links each claim to them as supporting, contradicting or qualifying, and shows the strongest evidence each way.
  It looks for evidence against your argument as hard as evidence for it.
- **Reads the literature every morning.** A daily sweep of OpenAlex, Crossref, arXiv and the feeds you choose
  screens new work against your propositions, keeps what matters (including what challenges you), and leaves a
  digest.
- **Answers from your corpus only.** Ask a question and get an answer with numbered citations, checked against the
  passages, or a plain statement that your corpus does not hold the answer.
- **Exports what you need.** Word reports with figures drawn from your data tables and a reference list, Excel
  workbooks, BibTeX and RIS.
- **Takes your own documents.** Drop files into a folder or upload them in the portal. Interview recordings are
  transcribed locally and never leave the machine.
- **Works with your agent.** A local web portal, a `commons` command line and an MCP server, plus setup skills
  that let a coding agent such as Claude Code tailor the whole system to your proposal.

## Bring your own LLM

Commons talks to models by role (author, worker, verifier, embedder), and each role points at a provider you
declare. Anything with an OpenAI-compatible endpoint works: Ollama, LM Studio, llama.cpp, vLLM, MLX on Apple
Silicon, a university AI gateway, or a hosted API. Anthropic's API is supported natively.

Every provider is labelled `local`, `institutional` or `cloud`, and Commons enforces what each may see:

| Material | Local model | Institutional service | Cloud API |
|---|---|---|---|
| Published literature (PUBLIC) | yes | yes | only if you switch it on |
| Your drafts and notes (PRIVATE) | yes | yes | only if you switch it on |
| Interviews and ethics-protected data (RESTRICTED) | yes | only with a named ethics approval | never |

Start from a preset that suits your machine:

| Your machine | Preset |
|---|---|
| No models yet, just looking | `demo` |
| Any laptop or desktop with 16 GB or more | `ollama` |
| Apple Silicon with 64 GB or more | `mlx` |
| Prefer LM Studio | `lmstudio` |
| Small machine, happy for published material to use a hosted model | `hosted` or `anthropic` |

[docs/models.md](docs/models.md) has the sizing table and model suggestions.

## Quick start

You need Python 3.11 or later.

```bash
pip install "phd-commons @ git+https://github.com/phd-commons/commons"
commons init ~/Commons --preset ollama --title "My thesis"
cd ~/Commons
commons doctor
```

Then either let a coding agent set it up for your thesis:

```bash
claude            # or another coding agent, opened in ~/Commons
> /commons-setup
```

or do it by hand: write your propositions in `thesis.yaml`, your search queries in `sources.yaml`, drop papers
into `inbox/`, and run:

```bash
commons inbox                 # ingest what you dropped in
commons sweep                 # today's research feed and digest
commons ask "What evidence is there against P1?" --export docx
commons serve                 # portal at http://127.0.0.1:8700
commons schedule install      # daily sweep, digest and backup
```

To see it work with no models installed at all, use `--preset demo` and one of the worked examples:
[heat and hospital admissions](examples/heat-health) (public health, quantitative) or
[early-career teachers in remote schools](examples/remote-teaching) (education, interviews). Both theses are
invented. The demo provider is a deterministic stand-in, not a model.

## Keeping you honest

The method behind Commons is set out in [docs/method.md](docs/method.md). In short:

- Model output is never evidence. Commons never cites itself.
- Every number is labelled MEASURED, DERIVED or ASSUMED. Charts are drawn only from stored data, never from
  figures a model typed.
- A source that cannot be read is recorded as a failure, never filled in.
- Your propositions' status is yours to set. Commons shows the evidence; you judge it.
- Every model call is logged, which gives you what you need for the AI-use statement in your methodology chapter.
  [docs/ai-use-statement.md](docs/ai-use-statement.md) has a template.

## Your data

Commons keeps everything in one workspace folder on your machine. It refuses ethics-protected material while the
workspace sits in a synced folder or until disk encryption is on (checked automatically on macOS, confirmed by you
on Linux and Windows), quarantines documents carrying protective or commercial-in-confidence markings, and answers
only requests from your own computer. Read
[docs/data-and-ethics.md](docs/data-and-ethics.md) before you add interview data.

## Status

Version 0.1. The full pipeline runs and is covered by tests that need no network and no models. The pattern has
been used in earnest on one doctoral project; this release turns it into reusable code for any field. Expect
rough edges, and please report them.

## Documentation

- [docs/method.md](docs/method.md): the research method the system enforces
- [docs/models.md](docs/models.md): bring your own LLM, sizing and providers
- [docs/data-and-ethics.md](docs/data-and-ethics.md): tiers, ethics approval and what never to put in
- [docs/agents.md](docs/agents.md): using Commons with Claude Code and other coding agents
- [docs/architecture.md](docs/architecture.md): how it fits together
- [docs/ai-use-statement.md](docs/ai-use-statement.md): a template for your methodology chapter

## Contributing, licence and citation

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). The code is licensed under Apache 2.0 and the
documentation under CC BY 4.0. If Commons helps your research, please cite it using [CITATION.cff](CITATION.cff).

Commons began as a research system built for a doctoral candidate in Canberra, Australia, and is maintained by
Aco Kovaceski.
