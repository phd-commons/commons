"""Install the daily schedule and the always-on portal as user services. Never needs admin rights.

macOS: launchd agents in ~/Library/LaunchAgents
Linux: systemd user units in ~/.config/systemd/user
Windows: Task Scheduler entries via schtasks (current user)
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

JOBS = {
    "sweep": ["sweep"],
    "digest": ["digest"],
    "backup": ["backup"],
}


def _exe() -> list[str]:
    """The commons command that belongs to this interpreter, not whichever is first on PATH."""
    bindir = Path(sys.executable).parent
    for name in ("commons", "commons.exe"):
        if (bindir / name).exists():
            return [str(bindir / name)]
    return [sys.executable, "-m", "phd_commons.cli"]


def _sd_quote(v: str) -> str:
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _xml(v: str) -> str:
    return v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _times(ws) -> dict:
    s = ws.get("schedule", {})
    return {"sweep": s.get("sweep", "05:00"), "digest": s.get("digest", "06:30"), "backup": s.get("backup", "02:00")}


def plan(ws) -> list[tuple[Path, str]]:
    system = platform.system()
    exe = _exe()
    root = str(ws.root)
    files = []
    label_base = "org.phdcommons." + ws.root.name.lower().replace(" ", "-")
    if system == "Darwin":
        d = Path.home() / "Library" / "LaunchAgents"
        for job, args in {**JOBS, "serve": ["serve"]}.items():
            prog = "".join(f"<string>{_xml(a)}</string>" for a in exe + args)
            if job == "serve":
                when = "<key>KeepAlive</key><true/><key>RunAtLoad</key><true/>"
            else:
                h, m = _times(ws)[job].split(":")
                when = (f"<key>StartCalendarInterval</key><dict><key>Hour</key><integer>{int(h)}</integer>"
                        f"<key>Minute</key><integer>{int(m)}</integer></dict>")
            xml = (f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                   f'"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>'
                   f"<key>Label</key><string>{label_base}.{job}</string>"
                   f"<key>ProgramArguments</key><array>{prog}</array>"
                   f"<key>WorkingDirectory</key><string>{_xml(root)}</string>"
                   f"<key>EnvironmentVariables</key><dict><key>COMMONS_HOME</key><string>{_xml(root)}</string>"
                   f"<key>PATH</key><string>{_xml(str(Path(exe[0]).parent))}:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>"
                   f"{when}<key>StandardOutPath</key><string>{_xml(root)}/logs/{job}.log</string>"
                   f"<key>StandardErrorPath</key><string>{_xml(root)}/logs/{job}.err</string></dict></plist>\n")
            files.append((d / f"{label_base}.{job}.plist", xml))
    elif system == "Linux":
        d = Path.home() / ".config" / "systemd" / "user"
        name = "phdcommons-" + ws.root.name.lower().replace(" ", "-")
        for job, args in {**JOBS, "serve": ["serve"]}.items():
            unit = (f"[Unit]\nDescription=Commons {job}\n\n[Service]\n"
                    f"Environment={_sd_quote('COMMONS_HOME=' + root)}\nWorkingDirectory={_sd_quote(root)}\n"
                    f"ExecStart={' '.join(_sd_quote(a) for a in exe + args)}\n")
            unit += "Restart=always\n\n[Install]\nWantedBy=default.target\n" if job == "serve" else "Type=oneshot\n"
            files.append((d / f"{name}-{job}.service", unit))
            if job != "serve":
                files.append((d / f"{name}-{job}.timer",
                              f"[Unit]\nDescription=Commons {job} timer\n\n[Timer]\nOnCalendar=*-*-* {_times(ws)[job]}:00\n"
                              f"Persistent=true\n\n[Install]\nWantedBy=timers.target\n"))
    else:
        # One small .cmd wrapper per job avoids nested quoting inside schtasks /TR.
        wrap_dir = ws.root / "ops"
        for job, args in {**JOBS, "serve": ["serve"]}.items():
            wrapper = wrap_dir / f"commons-{job}.cmd"
            body = (f'@echo off\r\nset "COMMONS_HOME={root}"\r\ncd /d "{root}"\r\n'
                    + " ".join(f'"{a}"' for a in exe + args) + f' >> "{root}\\logs\\{job}.log" 2>&1\r\n')
            when = "/SC ONLOGON" if job == "serve" else f"/SC DAILY /ST {_times(ws)[job]}"
            files.append((wrapper, body))
            files.append((Path(f"schtasks-{job}"),
                          f'schtasks /Create /F {when} /TN "PhDCommons {ws.root.name} {job}" /TR "{wrapper}"'))
    return files


def install(ws, dry_run: bool = False) -> list[str]:
    system = platform.system()
    done = []
    for path, content in plan(ws):
        if system == "Windows":
            if content.startswith("schtasks"):
                done.append(content)
                if not dry_run:
                    r = subprocess.run(content, shell=True, capture_output=True, text=True)
                    if r.returncode:
                        done.append(f"  failed: {r.stderr.strip() or r.stdout.strip()}")
            else:
                done.append(str(path))
                if not dry_run:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
            continue
        done.append(str(path))
        if dry_run:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if system == "Darwin":
            subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
            r = subprocess.run(["launchctl", "load", "-w", str(path)], capture_output=True, text=True)
            if r.returncode or r.stderr.strip():
                done.append(f"  launchctl: {r.stderr.strip() or r.returncode}")
    if system == "Linux" and not dry_run:
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        for path, _ in plan(ws):
            if path.suffix == ".timer" or path.name.endswith("-serve.service"):
                r = subprocess.run(["systemctl", "--user", "enable", "--now", path.name], capture_output=True, text=True)
                if r.returncode:
                    done.append(f"  systemctl {path.name}: {r.stderr.strip()}")
    return done


def uninstall(ws) -> list[str]:
    system = platform.system()
    removed = []
    for path, content in plan(ws):
        if system == "Windows":
            if content.startswith("schtasks"):
                job = content.split('/TN "')[1].split('"')[0]
                subprocess.run(f'schtasks /Delete /F /TN "{job}"', shell=True, check=False)
                removed.append(job)
            elif path.exists():
                path.unlink()
            continue
        if system == "Darwin":
            subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
        if system == "Linux":
            subprocess.run(["systemctl", "--user", "disable", "--now", path.name], capture_output=True)
        if path.exists():
            path.unlink()
            removed.append(str(path))
    return removed
