"""Register the Commons MCP server with an agent client.

  claude-desktop   writes an entry into Claude Desktop's claude_desktop_config.json (a backup is kept)
  claude-code      runs `claude mcp add` at user scope
  print            prints the JSON entry for any other MCP client (Cursor, Windsurf, Continue, VS Code, ...)
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .schedule import _exe


def server_entry(ws) -> dict:
    exe = _exe()
    return {"command": exe[0], "args": exe[1:] + ["mcp", "-w", str(ws.root)]}


def server_name(ws) -> str:
    return "commons" if ws.root.name.lower() in ("commons", "") else f"commons-{ws.root.name.lower().replace(' ', '-')}"


def claude_desktop_config_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if system == "Windows":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def install_claude_desktop(ws, path: Path | None = None) -> str:
    path = path or claude_desktop_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = {}
    if path.exists():
        raw = path.read_text(encoding="utf-8").strip()
        cfg = json.loads(raw) if raw else {}
        shutil.copy2(path, path.with_suffix(f".json.bak-{time.strftime('%Y%m%d-%H%M%S')}"))
    cfg.setdefault("mcpServers", {})[server_name(ws)] = server_entry(ws)
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return f"Added '{server_name(ws)}' to {path}. Quit and reopen Claude Desktop to load it."


def install_claude_code(ws) -> str:
    claude = shutil.which("claude")
    if not claude:
        return "The claude command is not on PATH. Install Claude Code, or run:\n  " + manual_claude_code(ws)
    e = server_entry(ws)
    cmd = [claude, "mcp", "add", "--scope", "user", server_name(ws), "--", e["command"], *e["args"]]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        return f"claude mcp add failed: {r.stderr.strip() or r.stdout.strip()}\nRun it yourself:\n  {manual_claude_code(ws)}"
    return f"Added '{server_name(ws)}' to Claude Code (user scope). Check with: claude mcp list"


def manual_claude_code(ws) -> str:
    e = server_entry(ws)
    quote = (lambda a: f'"{a}"' if " " in a else a)
    return " ".join(["claude", "mcp", "add", "--scope", "user", server_name(ws), "--", quote(e["command"]),
                     *(quote(a) for a in e["args"])])


def snippet(ws) -> str:
    return json.dumps({"mcpServers": {server_name(ws): server_entry(ws)}}, indent=2)


def python_executable() -> str:
    return sys.executable
