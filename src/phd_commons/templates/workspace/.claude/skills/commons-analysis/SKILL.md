---
name: commons-analysis
description: Build a field-specific analysis module in this Commons workspace that turns a thesis proposition into a reproducible, provenance-labelled test with registered output tables.
argument-hint: "[module code and the question it answers]"
---

An analysis module is a small Python file at `analyses/<code>/run.py` that pulls data, computes something that
bears on one or more propositions, and registers its output tables so the chat and the Word reports can chart
them. Read `analyses/PLAN.md` first if it exists.

## Contract

```python
def run(ctx):
    # ctx.ws, ctx.store, ctx.router, ctx.http (an httpx client), ctx.params
    rows = [...]  # list of dicts; first column is the label, numeric columns follow
    ctx.table("my_table", rows, provenance="MEASURED", description="What this is, its source and as-at date")
    return "one-line summary of what was found"
```

`commons analysis <code>` runs it and writes a stamp (as-at time, code hash, params, outputs) under
`okf/analyses/<code>/`.

## Rules

1. **State the test before you compute it.** Write `analyses/<code>/README.md` first: question, propositions served,
   data source with URL and terms, method, what result would support and what would count against, known traps,
   definition of done.
2. **Provenance on every table.** MEASURED (taken from a source), DERIVED (computed from measured inputs, method in
   the README), ASSUMED (a parameter someone chose; list it and who chose it).
3. **Keep the raw pull.** Save what you downloaded under `analyses/<code>/raw/` with the date, so a rerun on the same
   stamp reproduces the result.
4. **Replicate before you extend.** If the proposal or the literature states a figure the module can check,
   reproduce it first and report any difference and why.
5. **Report nulls and against-results as prominently as for-results.**
6. **No model-typed numbers.** A model may classify or extract (record precision on a hand-checked sample of at least
   50 rows, and put that sample in the student's Review queue); it may not supply figures.
7. **Restricted data stays local.** A module that reads RESTRICTED material must use only `local` providers, and must
   not write identifying details into any table.
8. If the data source cannot be reached, build the module anyway, record the failure in its README, and stop. Never
   substitute invented or remembered data.

## Done

The README is complete, `commons analysis <code>` runs cleanly, the tables appear in `okf/tables/`, and
`commons ask "make a chart of <table>" --export docx` produces a figure from them.
