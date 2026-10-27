# Skills

Personal Claude Code skills, and the hooks and scripts around them. Layout: `README.md`.

## Commands

```sh
scripts/verify.sh   # every test suite; drive-spec's verify gate
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s <dir>   # one suite, e.g. skills/engineering/drive-spec
```

No lint step. The drive-spec suite takes about four minutes: while working, run single tests (`python3 -m unittest test_drive_spec.<Class>.<test>` from its directory).

## Conventions

- A script's tests sit beside it as `test_<name>.py`: Python 3 `unittest`, standard library only.
- A skill's `SKILL.md`, `README.md` and contract docs describe what its script does: change them in the same commit as the behaviour. Follow the `writing-for-agents` skill when editing them.
- Commit messages are a subject line only, imperative present tense.

## Agent skills

### Issue tracker

GitHub Issues on `michaelloistl/skills`, via `gh`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

`/drive-spec` sets `agent:in-progress` while it works an issue and `agent:blocked` when a run fails. `needs:rex` marks a slice only a local Rex session can prove: `docs/agents/rex-proof.md`.

### Domain docs

Single-context: root `GLOSSARY.md` and `docs/adr/`. See `docs/agents/domain.md`.
