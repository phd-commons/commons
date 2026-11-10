# Commons Lite: plan

A free, browser-only version of Commons for a student who cannot install anything and cannot pay for
a model API. One static site. No server, no account, no telemetry. Everything stays in the browser.

## Who it is for

A doctoral student on a locked-down or shared machine, or on a Chromebook, who wants the Commons
method (claims tied to verbatim quotes, citations on every answer, disconfirming evidence kept) without
the Python install.

## What it does

1. **Drop in PDFs and notes.** Text is extracted in the browser (pdf.js). Originals and extracted text
   live in IndexedDB. The page states plainly: your library lives in this browser, on this machine, only.
2. **Claims with verbatim quotes.** The model reads each source and proposes claims, each with a quote.
   A claim is kept only if its quote appears word for word in the extracted text. That check is code,
   not a model, same as full Commons.
3. **Ask with citations.** Answers are retrieval-first: relevant passages are pulled by local embeddings
   (a small model in WebGPU, or BM25 where WebGPU is absent), the answer must cite [n], and each [n] is
   checked against the passages. No citation, no answer.
4. **Model drafts are labelled.** Anything the model writes is marked as a draft, never evidence.
5. **Export.** The library, claims and answers export to Markdown and BibTeX, as files the student keeps.

## Models, in order of preference

- Chrome built-in AI (Prompt API, Summarizer API) when present: free, on-device, no download.
- WebLLM with a small open-weight model (WebGPU) for everything else, downloaded once and cached.
- Where neither runs (old browser), the page still works as a reader and quote-checker, and says so.

## What it does not do (compared with full Commons)

- No daily sweep, no thesis board, no Word/Excel exports, no cross-family verification (one model only),
  no audio, no tier policy for ethics-protected material. The page says this and points to full Commons
  for those.

## Build

- Single static app under `lite/` in the repo: `index.html`, one JS bundle, vendored pdf.js and WebLLM.
  No build step needed to serve it; any static host works.
- Published at commons.acokovaceski.com/lite by adding `deploy/commons/lite/` to the site deploy.
- Tested in Chrome and Edge on Windows, Chrome on Android. WebGPU absence is a first-class path, not an
  error.

## Risks

- WebLLM model download is 1 to 2 GB. Show size before downloading and cache it.
- pdf.js text extraction quality varies; the verbatim-quote check makes extraction failures loud, not silent.
- IndexedDB quotas: warn when the library passes about 500 MB.
