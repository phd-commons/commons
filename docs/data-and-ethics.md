# Data and ethics

Read this before you add interview recordings, participant data or anything your ethics approval covers.

## Tiers

| Tier | What | Default for |
|---|---|---|
| PUBLIC | Published literature, legislation, official reports, public datasets, news | Items from the daily sweep; files you mark public |
| PRIVATE | Your notes, drafts, proposal, supervisor feedback | Anything you add without saying otherwise |
| RESTRICTED | Interview recordings and transcripts, consent forms, participant details, anything under ethics approval | Audio files; anything in `inbox/restricted/` |

What each kind of model may see is set out in [models.md](models.md). RESTRICTED material only ever reaches a
local model, or an institutional service that your approval names.

## What Commons does to protect RESTRICTED material

- Refuses it while the workspace sits in a synced folder (iCloud Drive, Dropbox, OneDrive, Google Drive, or
  Desktop and Documents on a Mac with iCloud sync).
- Refuses it while disk encryption is off. Commons checks FileVault itself on macOS. On Linux and Windows it
  cannot check, so it refuses RESTRICTED material until you turn on LUKS or BitLocker and set
  `restricted: {encryption_confirmed: true}` in `commons.yaml`.
- Keeps the originals, the extracted text, the source notes and the claim register for it in
  `library/restricted/` and `okf/restricted/`. The workspace's `.gitignore` excludes both.
- Leaves participant file names out of the shared log, which records RESTRICTED sources by number only.
- Never serves it through the MCP server or to a cloud model.
- Leaves it out of ordinary backups, including the copy of the database inside them, which is scrubbed of every
  RESTRICTED row before it is zipped. `commons backup --restricted-to <encrypted volume>` copies it separately.
- Deletes it on request: `commons purge <source id>` removes the original, the extracted text, the chunks, the
  claims, any review items quoting it and the note, after you type the source's name to confirm, then compacts the
  database so the deleted text does not linger. Older backups and anything you exported still hold it; delete
  those too.
- The database (`data/commons.db`) and anything you export (`exports/`) can contain RESTRICTED text, because they
  serve your own questions. They stay on your machine; treat them as you treat the originals.

## What never goes in

- Documents carrying a protective marking (for example OFFICIAL: Sensitive, PROTECTED, SECRET, CONFIDENTIAL, CUI).
  Commons quarantines them on sight and asks you.
- Commercial-in-confidence or client material from an employer. Add your employer's and clients' names to
  `tiers.blocked_names` so their documents are quarantined too.
- Anything you are not entitled to hold on a personal machine.

## Coding agents are cloud models

If you use Claude Code or another coding agent to set up or run Commons, the agent itself runs in the cloud. The
workspace's agent settings deny it the RESTRICTED folders, the database and your exports, and `AGENTS.md` tells it
not to read them. Those are guard rails, not a guarantee: an agent that can run shell commands can still be
pointed at a file. Keep interview data out of any folder you ask an agent to work on, and do not ask an agent to
look at it. Point it only at what you are happy to share: your proposal and published material are usually fine;
transcripts are not.

## De-identification

Transcripts can be de-identified before analysis. Use participant codes (P01, P02) in anything you export, and
check de-identification by hand on every transcript before relying on it.

## Your ethics application

Describe the system accurately: where data is stored (your machine, encrypted), which models process it and where
they run (local, or a named institutional service), what leaves the machine (nothing RESTRICTED), how long data is
kept and how it is destroyed (`commons purge`). The audit log (`model_calls` in `data/commons.db`) records every
model call with the tier of material it saw.
