"""Tests for check-cloud-rails.py. Run: python3 -m unittest discover -s hooks"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).with_name("check-cloud-rails.py")


class CheckCloudRails(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.bin = Path(self.tmp.name) / "bin"
        self.repo.mkdir()
        self.bin.mkdir()
        (self.repo / ".ruby-version").write_text("3.4.13\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, remote="true"):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", **({"CLAUDE_CODE_REMOTE": remote} if remote else {})}
        out = subprocess.run([str(HOOK)], input=json.dumps({"cwd": str(self.repo)}), capture_output=True, text=True,
                             check=True, env=env).stdout
        return json.loads(out)["systemMessage"] if out else None

    def test_warns_in_a_cloud_session_without_rails_services_up(self):
        self.assertIn("cloud-setup-rails.sh", self.run_hook())

    def test_quiet_once_rails_services_up_is_installed(self):
        tool = self.bin / "rails-services-up"
        tool.write_text("#!/bin/sh\n")
        tool.chmod(0o755)
        self.assertIsNone(self.run_hook())

    def test_quiet_outside_a_ruby_repo_or_a_cloud_session(self):
        self.assertIsNone(self.run_hook(remote=None))
        (self.repo / ".ruby-version").unlink()
        self.assertIsNone(self.run_hook())


if __name__ == "__main__":
    unittest.main()
