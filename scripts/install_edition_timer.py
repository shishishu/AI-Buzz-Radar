"""Install or update the daily edition's systemd user timer for this checkout."""

import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

NAME = "ai-buzz-radar-edition"
MARKER = "# Managed by AI-Buzz-Radar/scripts/install_edition_timer.py\n"


def unit_value(value):
    # Escape systemd quoting, specifiers, and ExecStart's environment substitution.
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def install():
    project = Path(__file__).resolve().parents[1]
    python = project / ".venv/bin/python"
    codex = shutil.which("codex")
    if not python.is_file() or not codex:
        raise SystemExit("Install the project venv and Codex CLI before enabling daily editions.")
    environment = [str(Path(codex).parent)]
    node = shutil.which("node")
    if node:
        environment.append(str(Path(node).parent))
    environment.extend(("/usr/local/bin", "/usr/bin", "/bin"))
    path = ":".join(dict.fromkeys(environment))
    launcher = project / "scripts/run_scheduled_edition.py"
    service = f"""[Unit]
Description=Generate the Agent developer daily edition
StartLimitIntervalSec=20h
StartLimitBurst=3

[Service]
Type=oneshot
Environment={unit_value("PATH=" + path)}
ExecStart={unit_value(python).replace("$", "$$")} {unit_value(launcher).replace("$", "$$")}
TimeoutStartSec=infinity
Restart=on-failure
RestartSec=15min
"""
    timer = f"""[Unit]
Description=Publish the Agent developer edition daily at 09:00 Asia/Shanghai

[Timer]
OnCalendar=*-*-* 09:00:00 Asia/Shanghai
AccuracySec=1s
Persistent=true
Unit={NAME}.service

[Install]
WantedBy=timers.target
"""
    units = {f"{NAME}.service": MARKER + service, f"{NAME}.timer": MARKER + timer}
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd/user"
    config.mkdir(parents=True, exist_ok=True)
    for name in units:
        existing = config / name
        if existing.is_symlink() or (
            existing.exists() and not existing.read_text().startswith(MARKER)
        ):
            raise SystemExit(f"Existing unit at {existing} belongs to another installation.")
    with TemporaryDirectory(dir=config) as tmp:
        staging = Path(tmp)
        for name, content in units.items():
            (staging / name).write_text(content)
        subprocess.run(
            ["systemd-analyze", "--user", "verify", *(staging / name for name in units)], check=True
        )
        for name, content in units.items():
            target = config / name
            if not target.exists() or target.read_text() != content:
                (staging / name).replace(target)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", f"{NAME}.timer"], check=True)
    subprocess.run(["systemctl", "--user", "list-timers", "--all", f"{NAME}.timer"], check=True)


if __name__ == "__main__":
    install()
