#!/usr/bin/env python3
# PreToolUse/Bash guard: block piping a drive-spec command's output (`drive-spec open … | tail`). Its exit code is
# the verdict (2 refused, 3 conflict, 4 red, 5 inbox notes), and a pipe hands the shell the last stage's exit
# instead, so a refusal reads as success and the next command runs on. Piping into it (`… | drive-spec integrate`)
# stays allowed: that is its stdin.
import json
import re
import sys

COMMANDS = ("plan|gate|verify|integrate|land|progress|frontier|start|halt|open|preview|explored|reviewed|confirm"
            "|cleanup|finish|ask|answered")

cmd = json.load(sys.stdin).get("tool_input", {}).get("command") or ""
# A heredoc's body is text fed to a command, not shell: drop it, keeping the line that opens it.
cmd = re.sub(r"(<<-?\s*(['\"]?)(\w+)\2[^\n]*\n).*?\n\s*\3[ \t]*(?=\n|$)", r"\1", cmd, flags=re.S)
names = re.findall(r"\b([A-Za-z_]\w*)=[\"']?[^\s;\"']*drive-spec[\"']?(?=[\s;]|$)", cmd)
callee = r"\S*drive-spec" + "".join(rf"|\$\{{?{n}\}}?" for n in names)


def pipes_out(rest):
    """True when the rest of this command, up to where it ends, pipes its output on."""
    quote, i = None, 0
    while i < len(rest):
        c = rest[i]
        if quote:
            quote = None if c == quote else quote
        elif c in "'\"":
            quote = c
        elif c in ";\n" or rest.startswith("&&", i) or rest.startswith("||", i):
            return False
        elif c == "|":
            return True
        i += 1
    return False


# Only where a command starts (a line, or after `;`, `&`, `|`, `(`, `$(`, past any VAR=value prefixes), so a
# mention inside text, such as a heredoc or a commit message, is not read as a call.
START = r"(?:^|[;&|(\n])\s*(?:[A-Za-z_]\w*=\S*\s+)*"
for m in re.finditer(rf"{START}(?:{callee})\s+(?:{COMMANDS})\b", cmd, re.M):
    if pipes_out(cmd[m.end():]):
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": (
                "This pipes a drive-spec command's output, so the shell reports the last stage's exit code instead "
                "of drive-spec's, and that code is the verdict: 2 refused, 3 conflict, 4 red, 5 inbox notes to act "
                "on. Run it bare, with nothing piped after it: its output is short. Feeding it stdin "
                "(`… | drive-spec integrate … --deviations -`) stays allowed.")}}))
        break
