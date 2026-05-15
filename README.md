# Skills

Personal Claude Code skills.

## Install

```bash
npx skills@latest add michaelloistl/skills
```

## Local development

Clone and link skills into `~/.agents/skills/` (visible to both `~/.claude` and `~/.claude-on`):

```bash
git clone https://github.com/michaelloistl/skills ~/Development/aplo/skills
bash ~/Development/aplo/skills/scripts/link-skills.sh
```

Re-run `link-skills.sh` whenever you add a new skill folder. Changes to existing skills are live immediately via the symlinks.

## Structure

```
skills/
├── engineering/   # Development workflow skills
├── personal/      # Personal / domain-specific skills
└── wip/           # Drafts — not listed in plugin.json
```
