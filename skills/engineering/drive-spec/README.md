# drive-spec

Skill: builds a spec's tracer-bullet issues, each in its own worktree, into one draft PR. Entry point is [`SKILL.md`](SKILL.md).

## status.sh

Writes the run's status file so a dispatcher can watch every drive-spec on the machine without reading transcripts. Contract and states: [`STATUS.md`](STATUS.md).

- State: `$GIT_COMMON_DIR/drive-spec/status/spec-<n>.json`, one file per spec, written only by that spec's run. It sits inside the repo's shared `.git` dir, so every worktree sees it, nothing commits it, and step 9's cleanup leaves it in place.
- Safe without a reader: it always exits 0, and a failed write only prints a warning.
- Needs `git` and `jq`; without `jq` it skips the write.
- `status.sh <n> --inbox` prints the dispatcher's unread notes from `spec-<n>.inbox.md` and moves them to `spec-<n>.inbox-read.md`.

```sh
./status.sh 2983 step=build state=running summary="landed 2/5; building #2990" next="integrate #2990"
```
