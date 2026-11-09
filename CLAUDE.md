# Developing Commons

This repository is the Commons package. Student workspaces are created from `src/phd_commons/templates/workspace/`
and carry their own AGENTS.md and skills; edit those templates, not a workspace, to change what students get.

- Run `pytest` before and after every change. Tests use the fake provider; keep them offline.
- The method in `docs/method.md` is the specification. Never let model output become evidence, never weaken the
  quote check or the tier policy, never add telemetry or unconfigured network calls.
- Front ends (portal, CLI, MCP) hold no business logic; put it in the core modules.
- Plain sentences in comments and docs.
