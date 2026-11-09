"""`commons doctor`: one screen that says whether the system is healthy and safe."""

from __future__ import annotations

import datetime as dt
import json
import shutil
from dataclasses import dataclass

from .llm import Router
from .okf import export_claims_register
from .safety import disk_encryption, in_sync_folder

GREEN, AMBER, RED = "GREEN", "AMBER", "RED"


@dataclass
class Check:
    name: str
    level: str
    detail: str
    fix: str = ""


def run_doctor(ws, store, router: Router | None = None, ping: bool = True) -> list[Check]:
    router = router or Router(ws, store)
    out: list[Check] = []

    # models
    roles = ws.cfg.get("roles", {})
    for need in ("author", "worker", "verifier", "embed"):
        if need not in roles:
            out.append(Check(f"role {need}", RED, "not configured", "add it under roles: in commons.yaml"))
    for pname, prov in ws.cfg.get("providers", {}).items():
        if prov.get("locality") == "local" and router.effective_locality(prov) != "local":
            where = prov.get("base_url") or prov.get("kind")
            out.append(Check(f"provider {pname}", RED, f"marked local but {where} is not on this machine or a "
                             "private network; Commons treats it as cloud", "set locality: cloud (or institutional)"))
    for r in router.describe():
        if "SET-ME" in str(r["model"]):
            out.append(Check(f"role {r['role']}", RED, "model not set", "replace SET-ME in commons.yaml"))
            continue
        if ping and r["role"] in ("author", "worker", "verifier", "embed"):
            ok, msg = router.ping(r["role"])
            out.append(Check(f"role {r['role']}", GREEN if ok else RED,
                             f"{r['model']} via {r['provider']} ({r['locality']}): {msg}",
                             "" if ok else "start the model server or fix the provider settings"))
    fam = {r["role"]: r.get("family") for r in router.describe()}
    if fam.get("author") and fam.get("author") == fam.get("verifier"):
        out.append(Check("verifier independence", AMBER, f"author and verifier are both {fam['author']}",
                         "use a different model family for verifier so their errors are not correlated"))
    if roles.get("embed", {}).get("local_fallback"):
        out.append(Check("embedding space", RED, "embed has a local_fallback, which would mix embedding spaces",
                         "use one embedding model for everything (a local one if you hold RESTRICTED material)"))
    if any(p.get("kind") == "fake" for p in ws.cfg["providers"].values()):
        out.append(Check("demo provider", AMBER, "the fake provider is configured; answers are not real",
                         "choose a real preset: commons init <folder> --preset ollama --force"))
    for t in ("RESTRICTED",):
        if not router.can("author", t):
            out.append(Check("restricted processing", AMBER, "no permitted model for RESTRICTED material; it will be "
                             "stored but not analysed", "add a local provider or a local_fallback for author"))

    # store and OKF
    embeds = store.embed_models()
    out.append(Check("embedding index", GREEN if len(embeds) <= 1 else RED,
                     f"models in index: {', '.join(sorted(embeds)) or 'none yet'}",
                     "" if len(embeds) <= 1 else "run commons rebuild"))
    c = store.counts()
    out.append(Check("corpus", GREEN if c["sources"] else AMBER,
                     f"{c['sources']} sources, {c['chunks']} chunks, {c['claims_verified']} verified claims, "
                     f"{c['review_open']} open review items, {c['failed']} failed, {c['quarantined']} quarantined",
                     "" if c["sources"] else "drop documents into inbox/ or run commons sweep"))
    notes = len(list((ws.okf / "sources").glob("*.md"))) + len(list((ws.okf / "restricted" / "sources").glob("*.md")))
    out.append(Check("okf and store agree", GREEN if notes >= c["sources"] else AMBER,
                     f"{notes} source notes for {c['sources']} sources", "" if notes >= c["sources"] else "commons rebuild"))
    export_claims_register(ws, store)
    if not ws.thesis_path().exists() or not store.scalar("SELECT COUNT(*) FROM propositions"):
        out.append(Check("thesis", AMBER, "no propositions loaded", "write thesis.yaml (the setup skill drafts it)"))

    # feed
    ls = ws.data / "last_sweep.json"
    if ls.exists():
        age = (dt.datetime.now() - dt.datetime.fromtimestamp(ls.stat().st_mtime)).total_seconds() / 3600
        rep = json.loads(ls.read_text())
        lvl = GREEN if age < 30 else AMBER
        out.append(Check("daily sweep", lvl, f"last run {age:.0f} h ago; {len(rep.get('failed_feeds', []))} feeds failed",
                         "" if lvl == GREEN else "commons schedule install, or run commons sweep"))
    else:
        out.append(Check("daily sweep", AMBER, "never run", "commons sweep, then commons schedule install"))

    # safety
    host = ws.get("portal.host", "127.0.0.1")
    out.append(Check("portal binding", GREEN if host in ("127.0.0.1", "localhost", "::1") else RED, host,
                     "" if host in ("127.0.0.1", "localhost", "::1") else "set portal.host to 127.0.0.1"))
    sync = in_sync_folder(ws.root)
    out.append(Check("sync folder", AMBER if sync else GREEN, sync or "workspace is not in a synced folder",
                     "move the workspace out of the synced folder" if sync else ""))
    enc = disk_encryption()
    out.append(Check("disk encryption", {"on": GREEN, "off": AMBER}.get(enc, AMBER), enc,
                     "" if enc == "on" else "turn on FileVault (macOS), BitLocker (Windows) or LUKS (Linux) "
                     "before adding RESTRICTED material"))
    cloud_on = [k for k in ("public", "private") if ws.get(f"cloud.{k}")]
    out.append(Check("cloud exposure", GREEN if not cloud_on else AMBER,
                     "cloud providers may see: " + (", ".join(t.upper() for t in cloud_on) or "nothing")))
    free = shutil.disk_usage(ws.root).free / 1e9
    out.append(Check("disk space", GREEN if free > 20 else AMBER, f"{free:.0f} GB free"))
    last_backup = sorted((ws.root.parent / f"{ws.root.name}-backups").glob("*.zip")) if \
        (ws.root.parent / f"{ws.root.name}-backups").exists() else []
    out.append(Check("backup", GREEN if last_backup else AMBER,
                     last_backup[-1].name if last_backup else "no backup yet", "" if last_backup else "commons backup"))
    calls = store.scalar("SELECT COUNT(*) FROM model_calls") or 0
    out.append(Check("audit log", GREEN, f"{calls} model calls recorded"))
    return out


def summary_level(checks: list[Check]) -> str:
    levels = {c.level for c in checks}
    return RED if RED in levels else AMBER if AMBER in levels else GREEN
