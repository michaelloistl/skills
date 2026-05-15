# Skills

Personal Claude Code skills.

## Install

```bash
npx skills@latest add michaelloistl/skills
```

## Local development

Clone the repo and run `scripts/link-skills.sh` to symlink skills into your local skills directory. Re-run it whenever you add a new skill folder — changes to existing skills are live immediately via the symlinks.

## Structure

```
skills/
├── engineering/   # Development workflow skills
├── personal/      # Personal / domain-specific skills
└── wip/           # Drafts — not listed in plugin.json
```
