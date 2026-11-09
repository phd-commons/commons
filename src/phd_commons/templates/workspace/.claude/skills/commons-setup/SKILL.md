---
name: commons-setup
description: Set up this Commons workspace for a doctoral student's thesis in any field - choose and install models for this machine, draft propositions and rivals from the proposal, configure the daily feed, seed the corpus, plan field-specific analyses, schedule it, and hand over.
argument-hint: "[path to the proposal, optional]"
---

Set up Commons for this student. Work through the steps in order. Keep a task list so the student can see
progress, and write what you decide into `docs/setup-log.md` as you go.

## 0. Five questions, asked once

Ask these together at the start (use AskUserQuestion if you have it), each with the default shown. If the student
has said not to ask, or you are running unattended, use the defaults and say so in `HANDOVER.md`.

1. Where is your research proposal? (default: the newest .docx or .pdf in this folder, `docs/` or `inbox/`)
2. If this machine is too small for good local models, may **published, public** material go to a hosted model
   you have an account with? Your own drafts and any interview data never would. (default: no)
3. Will you hold interview, patient, participant or other ethics-protected data? (default: yes)
4. Do you have access to a university-approved AI service, and does your ethics approval cover it? (default: no)
5. Citation style? (default: APA 7)

## 1. Profile the machine

Record in `docs/setup-log.md`: OS and version; CPU and chip; total RAM; GPU and VRAM (`nvidia-smi` if present;
on Apple Silicon the GPU shares RAM: read `max_recommended_working_set_size` from `mlx.core` if available, else
take 70 per cent of RAM); free disk; disk encryption (`commons doctor` reports it); whether the workspace sits in a
synced folder. Never use sudo.

## 2. Choose the model plan

Budget = 80 per cent of usable GPU memory (unified memory on Apple Silicon, VRAM elsewhere; CPU-only machines use
50 per cent of RAM and expect slow answers). Pick the strongest current open-weight models that fit, from the
newest releases you can find on the Ollama library or the `mlx-community` organisation on Hugging Face. The
examples below were current when this skill was written; prefer newer equivalents.

| Budget | Runtime | author | worker | verifier (different family) | embed |
|---|---|---|---|---|---|
| 250 GB and up | MLX (`mlx_lm.server`) | 235B-class MoE, 4 to 6-bit (e.g. Qwen3-235B-A22B) | 30B-class MoE (e.g. Qwen3-30B-A3B) | gpt-oss-120b | bge-m3 |
| 90 to 250 GB | MLX or Ollama | 80B to 120B-class MoE (e.g. Qwen3-Next-80B, gpt-oss-120b) | 30B-class MoE | a different family of similar size | bge-m3 |
| 24 to 90 GB | Ollama or LM Studio | 30B-class MoE, 4-bit | 8B-class | a different family, 12B-class (e.g. Gemma 3 12B) | bge-m3 |
| 10 to 24 GB | Ollama | 8B to 14B-class | 4B to 8B-class | a different family, 4B to 12B | bge-m3 |
| under 10 GB | Ollama | hosted model for PUBLIC only if question 2 was yes, with a small local fallback; otherwise a 4B-class local model and a warning | 4B-class | a different 4B-class family | a small local embedder |

Rules:
- If question 3 is yes, every role must have a `local` provider or a `local_fallback`, and the embed role must be
  local. If question 4 named an approved service, it may be declared `locality: institutional` with
  `restricted_approval: "<the approval reference>"`.
- The verifier must come from a different model family from the author.
- For reasoning models (Qwen3 and similar), set `thinking: off` on their providers; otherwise short structured
  replies can come back empty. `commons doctor` reports an empty reply as RED.
- One embedding model for the life of the index. Decide it now.
- Write the plan to `MODELS.md`: each role's model, size, quantisation, origin, licence, and why.

## 3. Install and configure

- Install the runtime in user space where possible: Ollama (ollama.com), LM Studio (lmstudio.ai) or
  `pip install mlx-lm` on Apple Silicon. If an installer needs administrator rights, give the student the one
  command to run and wait.
- Pull or download the models. Run large downloads in the background and continue with steps 4 to 6.
- Write `providers:` and `roles:` in `commons.yaml` (start from `commons init . --preset <ollama|mlx|lmstudio|hosted|anthropic> --force`
  if that is quicker, then edit). Set `project:` from the proposal and `citation_style` from question 5.
- On MLX, start one `mlx_lm.server --model <repo> --port <port> --host 127.0.0.1` per resident model, and make them
  persistent with a launchd agent (macOS) or systemd user unit (Linux).
- `commons doctor` until there is no RED. Record generation speed and the time for a 10k-token prompt in `MODELS.md`.

## 4. Read the proposal and draft the thesis

- Ingest it as PRIVATE without claims: `commons ingest <file> --tier PRIVATE --no-claims`. Read its text.
- Draft `thesis.yaml`:
  - the research questions, verbatim;
  - 4 to 8 propositions, each one testable sentence with `supports_if` and `disconfirms_if`;
  - 3 to 5 rivals (family R): the strongest objection an examiner would raise; the null (nothing distinctive is
    happening); an explanation from a neighbouring discipline; and an artefact of method or data if one is plausible;
  - every status `untested`. Put a comment at the top: drafted from the proposal on <date>, for review with
    supervisors.
- Write `docs/proposal-review.md` for the student. Be direct and constructive:
  - what the proposal does well;
  - where it argues a position rather than testing one, with an empirical restatement;
  - **the strategic frame**: who would act on this research, what alternatives they face, and which competing
    framings or actors the proposal leaves out; how the thesis changes if it takes them on;
  - the strongest objection an examiner will raise, met head on;
  - literatures and authors it under-uses, each verified in OpenAlex before you name it;
  - positionality and ethics points the method chapter must handle.
  Never invent a reference. If you cannot verify a work, leave it out.

## 5. Configure the daily feed

- Write 8 to 15 precise `queries` in `sources.yaml` from the propositions and rivals, including at least two aimed
  at disconfirming evidence.
- Add field-specific feeds: arXiv categories, RSS feeds of regulators, statistical agencies, journals, preprint
  servers, saved PubMed searches, institutional repositories. Verify each one live with
  `commons sweep --feed <id> --no-digest`; keep only those that work and note the rest in `docs/setup-log.md`.
- Set `contact_email` only if the student gives you one.

## 6. Seed the corpus

- Resolve every reference in the proposal's bibliography through OpenAlex or Crossref. For each with a lawful
  open-access PDF, download it into `inbox/` with a sidecar `<file>.pdf.json` holding
  `{"tier": "PUBLIC", "title": ..., "authors": [...], "year": ..., "doi": ..., "venue": ...}`.
- Do the same for key primary documents the proposal names (legislation, official reports, dataset documentation).
- List what is paywalled or book-only in `HANDOVER.md` under "Get through your library".
- `commons inbox`, then `commons doctor`.

## 7. Plan and build field-specific analyses

- Write `analyses/PLAN.md`: 3 to 8 modules that turn propositions into measurable tests in this field. For each:
  question, propositions served, data (public and reachable first), method, outputs, known traps, definition of done.
  Include at least one module that could produce evidence against the student's main proposition.
- Build the first one or two whose data is public, with the `commons-analysis` skill. Run `commons analysis` for the
  built-ins too.

## 8. Check it works

- Write `docs/golden.md`: eight questions. Five should be answerable from the seed corpus; three must not be (a
  future fact, an interview that does not exist, a figure the corpus does not hold).
- Run each with `commons ask`. Record pass or fail: every [n] must resolve and every quote must be verbatim;
  the three must abstain. Fix retrieval, models or corpus until they pass. Never edit an answer.
- Export one answer: `commons ask "<question>" --export docx` and `--export xlsx`. Open both to check they work.

## 9. Schedule and hand over

- `commons sweep`, then `commons schedule install`. Confirm the portal answers at http://127.0.0.1:8700.
- Write `HANDOVER.md` for the student (one page): what is set up and why; the daily routine (read the digest,
  clear Review, about ten minutes); how to add documents; how to ask and export; AMBER items with one-line fixes;
  what to read first in `docs/proposal-review.md`; ethics reminders (RESTRICTED stays local; disk encryption on;
  backups of RESTRICTED material only to encrypted storage; `commons purge` for required destruction); and how to
  disclose AI use in the methodology chapter (the audit log in `data/commons.db`, table `model_calls`).
- Finish by telling the student the portal address and the AMBER items, nothing more.
