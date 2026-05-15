---
name: update-changelog
description: Updates a project changelog file with new entries derived from recent git changes. Handles version detection, entry formatting, and release cutting. Use when the user asks to update the changelog, add a changelog entry, document changes, or bump a version in the changelog. Reads project config from .claude/changelog.yml if present.
---

# Update Changelog

## Quick start

1. Load config: check `.claude/changelog.yml` → fall back to [CONFIG.md](CONFIG.md) defaults
2. Read the existing changelog to understand version structure and current entries
3. Inspect recent changes (`git log`, `git diff`, or user description)
4. Determine target version block (see **Version detection** below)
5. Draft new entries following the entry format
6. Show the proposed additions to the user and confirm before writing

---

## Version detection

After reading the changelog, check the most recent dated version block:

- **Today's date matches** → add entries to that existing version block
- **No match / no dated versions** → ask user whether to add to `[Unreleased]` or cut a new version

When cutting a new version:
1. Confirm bump type with the user (major / minor / patch), explaining the reasoning
2. Suggest the next version number based on the current latest
3. Create `## [X.Y.Z] - YYYY-MM-DD` with today's date
4. If an `[Unreleased]` block exists and has content, absorb it into the new version

---

## Entry format

- Start with one of: `Added`, `Changed`, `Fixed`, `Removed`, `Updated`, `Improved`, `Renamed`
- Past tense, capitalised, no trailing period
- Describe what the user sees or experiences — not implementation details
- One line per entry; use an indented `>` block for extra context if needed
- Omit purely internal changes (dev tooling, seed data, refactors) unless operator-relevant

**Example entries:**

```
- Added dark mode toggle to the settings page
- Fixed sign-in redirect looping after password reset
- Removed legacy CSV export endpoint
```

Ordering within a version: `Added` → `Changed` → `Fixed` → `Removed`

---

## Workflow

### Adding entries

1. `git log --oneline -20` to see recent commits
2. `git diff [base]..[head] --stat` or read changed files for scope
3. Filter out internal/tooling changes
4. Apply version detection logic above
5. Confirm with user, then write

### Cutting a release

1. Run version detection — propose the next version number
2. Replace or create the version block with today's date
3. If `[Unreleased]` existed with content, absorb it; leave an empty `## [Unreleased]` at the top
4. Update comparison links at the bottom if present
5. Confirm and write

---

## Project-specific config

Check for `.claude/changelog.yml` in the project root before doing anything. If found, it overrides all defaults. See [CONFIG.md](CONFIG.md) for all available keys and their defaults.

Example `.claude/changelog.yml`:

```yaml
changelog_path: docs/CHANGELOG.md
versioning: calver          # semver | calver | none
entry_verbs: [Added, Changed, Fixed, Removed]
entry_ordering: [Added, Changed, Fixed, Removed]
conventions_doc: docs/dev/conventions/changelog.md
```

If `conventions_doc` is set, read that file and apply its rules — it takes precedence over the entry format in this skill.
