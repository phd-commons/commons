"""Machine-level safety checks that gate RESTRICTED material."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

SYNC_MARKERS = ["Library/Mobile Documents", "Library/CloudStorage", "Dropbox", "OneDrive", "Google Drive", "iCloud"]


def in_sync_folder(path: Path) -> str | None:
    p = str(Path(path).resolve())
    for m in SYNC_MARKERS:
        if m in p:
            return m
    home = Path.home()
    if platform.system() == "Darwin":
        for d in ("Documents", "Desktop"):
            if p.startswith(str(home / d)):
                return f"~/{d} (synced when iCloud Desktop & Documents is on)"
    return None


def disk_encryption() -> str:
    """Return 'on', 'off' or 'unknown'. Never needs admin rights."""
    system = platform.system()
    try:
        if system == "Darwin":
            out = subprocess.run(["fdesetup", "status"], capture_output=True, text=True, timeout=10).stdout
            return "on" if "On" in out else "off" if "Off" in out else "unknown"
        if system == "Linux":
            out = subprocess.run(["lsblk", "-o", "TYPE"], capture_output=True, text=True, timeout=10).stdout
            return "on" if "crypt" in out else "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"
    return "unknown"


def restricted_blocked_reason(ws) -> str | None:
    if os.environ.get("COMMONS_ALLOW_RESTRICTED_UNENCRYPTED") == "1":
        return None
    sync = in_sync_folder(ws.root)
    if sync:
        return f"the workspace is inside a synced folder ({sync}); move it before adding RESTRICTED material"
    enc = disk_encryption()
    if enc == "off":
        return "disk encryption is off (turn on FileVault, BitLocker or LUKS first)"
    if enc == "unknown" and not ws.get("restricted.encryption_confirmed", False):
        return ("Commons cannot check disk encryption on this system. Turn on BitLocker or LUKS, then set "
                "restricted: {encryption_confirmed: true} in commons.yaml")
    return None
