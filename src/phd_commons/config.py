"""Workspace discovery and configuration.

A workspace is a folder holding one student's research: commons.yaml, thesis.yaml, sources.yaml,
the OKF (okf/), originals (library/), the inbox and a derived database. The code never lives there,
and the workspace never lives in the code repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_NAME = "commons.yaml"
TIERS = ("PUBLIC", "PRIVATE", "RESTRICTED")

DEFAULT_CONFIG: dict[str, Any] = {
    "project": {
        "title": "",
        "candidate": "",
        "institution": "",
        "field": "",
        "citation_style": "apa",
    },
    "portal": {"host": "127.0.0.1", "port": 8700},
    # What a provider marked locality: cloud may receive. RESTRICTED never goes to cloud.
    "cloud": {"public": False, "private": False},
    # What the MCP server serves to agent clients (assume they are cloud models).
    "mcp": {"public": True, "private": False},
    "contact_email": "",
    "schedule": {"sweep": "05:00", "digest": "06:30", "backup": "02:00"},
    "retrieval": {"top_k": 10, "per_source_cap": 2, "context_tokens": 10000, "rrf_k": 60, "min_similarity": 0.2},
    "chunking": {"target_tokens": 900, "overlap_tokens": 120},
    "claims": {"max_per_chunk": 3},
    "sweep": {"keep_threshold": 2, "max_items_per_feed": 25},
    "providers": {
        "fake": {"kind": "fake", "locality": "local"},
    },
    "roles": {
        "author": {"provider": "fake", "model": "fake-author"},
        "worker": {"provider": "fake", "model": "fake-worker"},
        "verifier": {"provider": "fake", "model": "fake-verifier"},
        "embed": {"provider": "fake", "model": "fake-embed"},
    },
    "tiers": {
        "quarantine_markings": [
            "OFFICIAL: Sensitive", "OFFICIAL:Sensitive", "PROTECTED", "SECRET", "TOP SECRET",
            "CONFIDENTIAL", "CUI", "RESTRICTED - NOT FOR CIRCULATION",
        ],
        "quarantine_phrases": [
            "Commercial-in-Confidence", "Commercial in Confidence", "Client Confidential",
            "Not for distribution", "Strictly confidential",
        ],
        "blocked_names": [],
    },
    "house_style": {
        "paper": "A4",
        "font": "Arial",
        "heading_colour": "1F3864",
        "justify": True,
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def find_workspace(start: Path | None = None) -> Path | None:
    env = os.environ.get("COMMONS_HOME")
    if env:
        p = Path(env).expanduser().resolve()
        return p if (p / CONFIG_NAME).exists() else None
    cur = (start or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / CONFIG_NAME).exists():
            return p
    return None


@dataclass
class Workspace:
    root: Path
    cfg: dict = field(default_factory=dict)

    # paths
    @property
    def okf(self) -> Path:
        return self.root / "okf"

    @property
    def library(self) -> Path:
        return self.root / "library"

    @property
    def inbox(self) -> Path:
        return self.root / "inbox"

    @property
    def quarantine(self) -> Path:
        return self.root / "quarantine"

    @property
    def exports(self) -> Path:
        return self.root / "exports"

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def db_path(self) -> Path:
        return self.data / "commons.db"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def tables(self) -> Path:
        return self.okf / "tables"

    def thesis_path(self) -> Path:
        return self.root / "thesis.yaml"

    def sources_path(self) -> Path:
        return self.root / "sources.yaml"

    def library_dir(self, tier: str) -> Path:
        return self.library / tier.lower()

    def ensure_layout(self) -> None:
        for p in [
            self.okf / "sources", self.okf / "claims", self.okf / "digests", self.okf / "insights",
            self.okf / "notes", self.okf / "notes" / "journal", self.okf / "analyses", self.okf / "restricted",
            self.tables, self.library_dir("PUBLIC"), self.library_dir("PRIVATE"), self.library_dir("RESTRICTED"),
            self.inbox, self.inbox / "restricted", self.quarantine, self.exports, self.data, self.logs,
        ]:
            p.mkdir(parents=True, exist_ok=True)

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.cfg
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def save_config(self) -> None:
        (self.root / CONFIG_NAME).write_text(yaml.safe_dump(self.cfg, sort_keys=False, allow_unicode=True))

    def load_yaml(self, path: Path) -> dict:
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_workspace(path: Path | str | None = None) -> Workspace:
    root = Path(path).expanduser().resolve() if path else find_workspace()
    if root is None or not (root / CONFIG_NAME).exists():
        raise SystemExit(
            "No Commons workspace found. Run `commons init <folder>` first, or cd into a workspace, "
            "or set COMMONS_HOME."
        )
    user = yaml.safe_load((root / CONFIG_NAME).read_text(encoding="utf-8")) or {}
    cfg = deep_merge(DEFAULT_CONFIG, user)
    # Providers and roles are replaced wholesale when the user defines them, not merged with the fake default.
    if "providers" in user:
        cfg["providers"] = user["providers"]
    if "roles" in user:
        cfg["roles"] = user["roles"]
    ws = Workspace(root=root, cfg=cfg)
    ws.ensure_layout()
    return ws
