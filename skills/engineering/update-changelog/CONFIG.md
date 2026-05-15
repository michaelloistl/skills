# update-changelog — Configuration Reference

All options can be set in `.claude/changelog.yml` at the project root. Unset keys fall back to the defaults listed here.

## Available keys

| Key | Default | Description |
|-----|---------|-------------|
| `changelog_path` | `CHANGELOG.md` | Path to the changelog file, relative to project root |
| `versioning` | `semver` | Versioning scheme: `semver`, `calver`, or `none` |
| `versioning_spec` | `https://semver.org/` | URL or path to the versioning spec used for guidance |
| `entry_verbs` | `[Added, Changed, Fixed, Removed, Updated, Improved, Renamed]` | Allowed entry prefix verbs |
| `entry_ordering` | `[Added, Changed, Fixed, Removed]` | Order to sort entries within a version block |
| `conventions_doc` | _(none)_ | Path to a project conventions file (e.g. `docs/dev/conventions/changelog.md`). When set, its rules override the defaults in SKILL.md. |
| `unreleased_block` | `true` | Whether to maintain an `[Unreleased]` block at the top |
| `comparison_links` | `true` | Whether to update `[X.Y.Z]: https://...` comparison links at the bottom |

## Versioning schemes

### `semver` (default)
Follows https://semver.org/. Version format: `MAJOR.MINOR.PATCH`.
- `PATCH` — backwards-compatible fixes
- `MINOR` — new backwards-compatible features
- `MAJOR` — breaking changes

### `calver`
Date-based versions. Format: `YYYY.MM.DD` or `YYYY.0M.MICRO` depending on project convention. Check the existing changelog for the format in use.

### `none`
No version numbers. All entries go into a flat chronological log, grouped by date heading `## YYYY-MM-DD`.

---

## Example configs

**Minimal (just a non-default path):**
```yaml
changelog_path: docs/CHANGELOG.md
```

**Full example:**
```yaml
changelog_path: CHANGELOG.md
versioning: semver
versioning_spec: https://semver.org/
entry_verbs: [Added, Changed, Fixed, Removed]
entry_ordering: [Added, Changed, Fixed, Removed]
conventions_doc: docs/dev/conventions/changelog.md
unreleased_block: true
comparison_links: false
```

**CalVer project:**
```yaml
versioning: calver
unreleased_block: false
```
