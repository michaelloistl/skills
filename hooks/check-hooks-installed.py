#!/usr/bin/env python3
import json
import os
import shlex
import sys
from pathlib import Path

PREFIXES = {"(", "nohup", "exec", "env", "bash", "sh", "zsh", "python", "python3", "ruby", "node"}
INTERPRETERS = PREFIXES - {"(", "nohup", "exec", "env"}


def script_of(command):
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None, False
    interpreted = False
    for token in tokens:
        token = token.lstrip("(")
        if not token:
            continue
        name = os.path.basename(token)
        if name in PREFIXES:
            interpreted = interpreted or name in INTERPRETERS
            continue
        if token.startswith("-") or "=" in token:
            return None, False
        path = os.path.expandvars(os.path.expanduser(token))
        return (path, interpreted) if "/" in path else (None, False)
    return None, False


def missing(settings):
    found = []
    for event, groups in (settings.get("hooks") or {}).items():
        for group in groups:
            for hook in group.get("hooks", []):
                if hook.get("type") != "command":
                    continue
                path, interpreted = script_of(hook.get("command", ""))
                if path is None:
                    continue
                if not os.path.isfile(path):
                    found.append(f"{event}: {path} (not found)")
                elif not interpreted and not os.access(path, os.X_OK):
                    found.append(f"{event}: {path} (not executable)")
    return found


config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
try:
    settings = json.loads((config_dir / "settings.json").read_text())
except (OSError, ValueError):
    sys.exit(0)

problems = missing(settings)
if problems:
    message = (f"Hooks in {config_dir}/settings.json will not run, and a missing guard lets every command through: "
               + "; ".join(problems)
               + ". Run ~/Development/skills/scripts/link-skills.sh to relink the repo's hooks.")
    print(json.dumps({"systemMessage": message,
                      "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": message}}))
