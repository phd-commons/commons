"""Create a workspace from the bundled template."""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

import yaml

from .config import CONFIG_NAME, load_workspace
from .presets import PRESETS
from .safety import in_sync_folder


def template_dir() -> Path:
    return Path(resources.files("phd_commons") / "templates" / "workspace")


def init_workspace(target: Path, preset: str = "demo", title: str = "", candidate: str = "",
                   institution: str = "", field: str = "", force: bool = False) -> tuple[Path, list[str]]:
    target = Path(target).expanduser().resolve()
    notes = []
    if (target / CONFIG_NAME).exists() and not force:
        raise SystemExit(f"{target} is already a Commons workspace. Use --force to rewrite its config.")
    target.mkdir(parents=True, exist_ok=True)
    src = template_dir()
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        dest = target / rel
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        elif not dest.exists() or (force and rel.name == CONFIG_NAME):
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
    gi = target / "gitignore.template"
    if gi.exists():
        gi.rename(target / ".gitignore") if not (target / ".gitignore").exists() else gi.unlink()
    cfg = yaml.safe_load((target / CONFIG_NAME).read_text(encoding="utf-8")) or {}
    if preset not in PRESETS:
        raise SystemExit(f"unknown preset '{preset}'. Choose one of: {', '.join(PRESETS)}")
    cfg.update({k: v for k, v in PRESETS[preset].items()})
    cfg.setdefault("project", {})
    for k, v in (("title", title), ("candidate", candidate), ("institution", institution), ("field", field)):
        if v:
            cfg["project"][k] = v
    header = (f"# Commons workspace configuration (preset: {preset}).\n"
              "# Providers and roles are yours to change: see docs/models.md in the Commons repository.\n")
    (target / CONFIG_NAME).write_text(header + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True),
                                      encoding="utf-8")
    ws = load_workspace(target)
    sync = in_sync_folder(target)
    if sync:
        notes.append(f"Warning: this folder is inside a synced location ({sync}). RESTRICTED material will be "
                     "refused here. Move the workspace to a non-synced folder if you will hold interview data.")
    if preset == "demo":
        notes.append("Demo preset: the fake provider stands in for real models. Switch with "
                     "`commons init <folder> --preset ollama --force` or edit commons.yaml.")
    return ws.root, notes
