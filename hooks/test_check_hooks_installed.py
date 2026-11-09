"""Tests for check-hooks-installed.py. Run: python3 -m unittest discover -s hooks"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).with_name("check-hooks-installed.py")


class CheckHooksInstalled(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.config = self.home / ".claude"
        (self.config / "hooks").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def script(self, name, executable=True):
        path = self.config / "hooks" / name
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755 if executable else 0o644)

    def run_with(self, *commands):
        hooks = [{"type": "command", "command": c} for c in commands]
        (self.config / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": hooks}]}}))
        env = {**os.environ, "HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.config)}
        out = subprocess.run([str(HOOK)], input="{}", capture_output=True, text=True, check=True, env=env).stdout
        return json.loads(out)["systemMessage"] if out else None

    def test_warns_on_a_missing_or_unexecutable_script(self):
        self.script("plain.sh", executable=False)
        message = self.run_with("~/.claude/hooks/gone.py", "~/.claude/hooks/plain.sh")
        self.assertIn("gone.py (not found)", message)
        self.assertIn("plain.sh (not executable)", message)

    def test_quiet_when_every_script_is_there(self):
        self.script("ok.sh")
        self.script("run-by-bash.sh", executable=False)
        self.assertIsNone(self.run_with(
            "~/.claude/hooks/ok.sh",
            f"bash '{self.config}/hooks/run-by-bash.sh' session",
            f"(nohup bash '{self.config}/hooks/ok.sh' \"$X\" >/dev/null 2>&1 &) ; true",
            "/bin/sh -c 'rex start 2>/dev/null || true'",
            '[ -n "${X:-}" ] && printf x',
            "rex-claude-track start",
        ))

    def test_quiet_without_settings(self):
        env = {**os.environ, "HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.config)}
        out = subprocess.run([str(HOOK)], input="{}", capture_output=True, text=True, check=True, env=env).stdout
        self.assertEqual(out, "")
