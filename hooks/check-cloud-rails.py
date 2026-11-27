#!/usr/bin/env python3
"""SessionStart: in a cloud session, warn when the repo needs Ruby but the environment never ran
scripts/cloud-setup-rails.sh, so `rails-services-up` is missing and the image's own Ruby is on the PATH."""
import json
import os
import shutil
import sys

if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
    sys.exit(0)
try:
    cwd = json.load(sys.stdin).get("cwd") or os.getcwd()
except (ValueError, AttributeError):
    cwd = os.getcwd()
if not os.path.isfile(os.path.join(cwd, ".ruby-version")) or shutil.which("rails-services-up"):
    sys.exit(0)

message = ("This repo pins Ruby in .ruby-version, but `rails-services-up` is not installed: this cloud environment "
           "ran only scripts/cloud-setup.sh, not scripts/cloud-setup-rails.sh, so its Ruby, Postgres and Redis are "
           "the image's own. Tell the operator to point the environment's setup script at cloud-setup-rails.sh, "
           "and wait for their answer before any bundle, rails or test command.")
print(json.dumps({"systemMessage": message,
                  "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": message}}))
