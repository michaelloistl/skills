# Skills

Personal Claude Code skills.

## Install

```bash
npx skills@latest add michaelloistl/skills
```

## Local development

Clone the repo and run `scripts/link-skills.sh` to symlink skills into your local skills directory and hooks into each `~/.claude*/hooks/`. Re-run it whenever you add a new skill folder or hook — changes to existing skills are live immediately via the symlinks.

## Structure

```
skills/
├── engineering/   # Development workflow skills
├── personal/      # Personal / domain-specific skills
└── wip/           # Drafts
hooks/             # Claude Code hooks, see hooks/README.md
```
