# The method

Commons enforces a way of working with evidence. The software is the easy part; the method is what makes it
useful to a doctoral candidate and defensible to an examiner.

## 1. One knowledge base, in plain text, that you own

Everything lives in the OKF (`okf/` in your workspace): one Markdown note per source, a claim register, daily
digests, your notes and the outputs of your analyses. It is readable without Commons, it diffs cleanly in git,
and it outlives any tool. The database that makes search fast is derived from it; `commons rebuild` recreates
the database from the Markdown and the stored originals and must produce the same counts.

## 2. Claims, not summaries

The unit of evidence is a claim: one statement a source makes, with a verbatim quote and a page number. Commons
extracts candidate claims with a model, then:

1. **Checks the quote mechanically.** After normalising whitespace, ligatures and line-break hyphenation, the quote
   must appear in the source text. If it does not, the claim is rejected. No model vote overrides this.
2. **Has a second model judge it.** A verifier from a different model family decides whether the quote supports
   the claim as stated (SUPPORTED, OVERSTATED, NOT_SUPPORTED). Using a different family means the two models'
   errors are less likely to coincide.
3. **Sends doubt to you.** Sceptical verifiers reject true claims when the supporting quote is short. A claim whose
   quote is verbatim but whose verdict is doubtful goes to your Review queue, not the bin.

Summaries exist, but they are labelled as drafted by a model and are never treated as evidence.

## 3. Propositions and rivals

Write your thesis as propositions that evidence can bear on. For each, state in advance what you would expect to
find if it is right (`supports_if`) and what would count against it (`disconfirms_if`). Then write the rival
explanations an examiner would offer: the obvious alternative account, the null (nothing distinctive is
happening), an explanation from a neighbouring discipline, and an artefact of method or data.

This is pattern matching against rival explanations, the logic of good case-study and mixed-methods research. It
does not turn interpretive work into hypothesis testing, and Commons never declares a proposition proven. It
shows you the evidence each way; the status of each proposition is yours to set.

## 4. Disconfirmation is first class

Every stage looks for evidence against your argument as hard as evidence for it. Claim extraction is asked for
claims that cut against the propositions. The daily screen keeps items that challenge a proposition even when they
score low on relevance. The thesis board shows the strongest evidence against each proposition and flags any
proposition for which none has been found yet. The devil's advocate mode in Ask argues the examiner's case from
your own corpus.

## 5. Provenance on every number

Every figure is labelled:

- **MEASURED**: taken from a source.
- **DERIVED**: computed from measured inputs, with the computation recorded.
- **ASSUMED**: a parameter someone chose, listed with who and why.

Charts in exports are drawn only from data tables registered by analysis modules. A model may write prose around
a chart; it may not supply the numbers in it.

## 6. Loud failure beats synthetic success

A scanned PDF with no text, a paywall stub or a page that will not load is recorded as a failure with its reason.
Commons never fills the gap with generated text, and never invents a citation. A corpus that quietly contains
made-up material is worse than one with visible holes.

## 7. Fix the corpus, never the answer

If an answer is wrong, the fix is in the corpus (a missing or misread source), the retrieval (the right passage was
not found) or the plan (the question was not answerable). Tuning prompts until a preferred conclusion comes out is
the one thing the method forbids.

## 8. Field-specific tests

The thesis board tells you what the literature says. Analysis modules test propositions against data: a time
series, a text-coverage count of legislation, a procurement concentration index, a coded interview set. Each module
states its test before it is run, keeps its raw data, labels its outputs, and writes a stamp so the result can be
reproduced. Replicate a figure from the literature before you extend it.

## 9. Know where your data goes

Material is PUBLIC, PRIVATE or RESTRICTED, and models are local, institutional or cloud. The rules are enforced in
code (see [data-and-ethics.md](data-and-ethics.md)), and every model call is logged with the tier of material it
saw. That log is the basis for an honest AI-use statement.

## 10. The student writes the thesis

Commons retrieves, checks, organises and drafts notes. It does not write thesis prose, and nothing it drafts is
evidence. The judgement, the argument and the words are yours.
