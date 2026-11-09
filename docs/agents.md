# Using Commons with a coding agent

Commons works on its own from the command line and the portal. A coding agent makes setup much faster: it can read
your proposal, draft your propositions and rivals, pick models that fit your machine, configure the feed, seed the
corpus from your bibliography and build field-specific analyses.

Every workspace created by `commons init` includes:

- `AGENTS.md`: instructions any coding agent should read first (rules, what Commons does, how to operate it);
- `CLAUDE.md`: imports `AGENTS.md` for Claude Code;
- `.claude/skills/commons-setup/`: the full setup procedure;
- `.claude/skills/commons-analysis/`: how to build an analysis module;
- `.claude/settings.json`: forbids sudo, pushing, and reading RESTRICTED folders;
- `.mcp.json`: registers the `commons` MCP server, which serves PUBLIC material only by default.

## Claude Code

Install the Claude Code CLI, then from a terminal:

```bash
cd ~/Commons
claude
```

and type `/commons-setup`. The skill asks five questions up front (where your proposal is, whether published
material may go to a hosted model, whether you will hold ethics-protected data, whether you have an approved
institutional AI service, and your citation style), then works through setup and leaves a `HANDOVER.md`.

To run setup unattended, answer the five questions in your first message, say not to ask anything else, and use
`/goal` so the agent keeps going until it is done:

```
/goal Run the commons-setup skill to completion without asking me anything. My proposal is proposal.docx.
Published material may not go to a hosted model. I will hold interview data. No institutional AI service.
APA 7. Done means commons doctor shows no RED and HANDOVER.md exists.
```

Use the most capable model and a high reasoning effort available on your plan; setup involves judgement about your
field. Auto mode lets the agent work without stopping for every approval.

## Other agents

Codex, Cursor, Gemini CLI, Aider and others read `AGENTS.md`. Ask them to follow
`.claude/skills/commons-setup/SKILL.md` step by step.

## What the agent produces

- `thesis.yaml`: propositions and rivals drafted from your proposal, for you and your supervisors to edit.
- `docs/proposal-review.md`: a candid review of the proposal: where it argues rather than tests, the strategic
  frame (who would act on the research and what alternatives they face), the strongest examiner objection met head
  on, and literatures it under-uses, each verified.
- `sources.yaml`: precise queries and field-specific feeds, each checked live.
- `analyses/PLAN.md` and the first analysis modules.
- `MODELS.md`: the model plan for your machine, with measured speeds.
- `HANDOVER.md`: what is set up and the daily routine.
