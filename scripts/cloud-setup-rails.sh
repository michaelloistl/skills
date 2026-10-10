#!/usr/bin/env bash
# Setup script for the "Rails" Claude Code cloud environment.
# Runs as root on Ubuntu before Claude Code launches. The result is cached for
# ~7 days and rebuilt only when the pasted script changes, so paste this loader
# pinned to a commit, and bump SKILLS_REF to roll out a change:
#
#   #!/bin/bash
#   set -euo pipefail
#   export SKILLS_REF=<commit sha>
#   f=$(mktemp)
#   curl -fsSL "https://raw.githubusercontent.com/michaelloistl/skills/$SKILLS_REF/scripts/cloud-setup-rails.sh" -o "$f"
#   bash "$f" </dev/null
#
# Also set in the environment's "Environment variables" field:
#   LANG=C.UTF-8
#   LC_ALL=C.UTF-8

set -euo pipefail

# SKILLS_REF pins the base script to the same commit as this one.
SCRIPTS=https://raw.githubusercontent.com/michaelloistl/skills/${SKILLS_REF:-main}/scripts

pids=()

base=$(mktemp)
curl -fsSL "$SCRIPTS/cloud-setup.sh" -o "$base"
bash "$base" </dev/null &
pids+=($!)

(
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    libvips42 libvips-dev imagemagick libpq-dev xz-utils >/dev/null
) &
pids+=($!)

# Rubies come from each repo's .ruby-version: ruby-up installs whichever are
# missing, as rv prebuilts (seconds, not minutes) linked into rbenv.
cat > /usr/local/bin/ruby-up <<'EOF'
#!/usr/bin/env bash
# Idempotent: install the Rubies this repo's .ruby-version files ask for.
set -euo pipefail
versions="$(rbenv root)/versions"
mkdir -p "$versions"
for v in $(git ls-files 2>/dev/null | grep -E '(^|/)\.ruby-version$' | xargs -r cat | sed 's/^ruby-//' | sort -u); do
  [ -x "$versions/$v/bin/ruby" ] && continue
  "$HOME/.cargo/bin/rv" ruby install "$v" >/dev/null
  ln -sfn "$HOME/.local/share/rv/rubies/ruby-$v" "$versions/$v"
  "$versions/$v/bin/ruby" -ropenssl -rpsych -e '' # fail now, not mid-test
done
rbenv rehash
EOF
chmod +x /usr/local/bin/ruby-up

(
  curl --proto '=https' --tlsv1.2 -LsSf \
    https://github.com/spinel-coop/rv/releases/latest/download/rv-installer.sh | sh >/dev/null
  ruby-up # warms the cache when the setup runs inside the repo; no-op otherwise
  # The image puts another Ruby ahead of rbenv on PATH; put the shims first
  # in every session shell. Top of .bashrc, before its non-interactive return.
  line="export PATH=\"$(rbenv root)/shims:\$PATH\""
  echo "$line" > /etc/profile.d/rbenv-shims.sh
  touch ~/.bashrc
  grep -qxF "$line" ~/.bashrc || { echo "$line"; cat ~/.bashrc; } > ~/.bashrc.new
  [ ! -f ~/.bashrc.new ] || mv ~/.bashrc.new ~/.bashrc
) &
pids+=($!)

# Bare `wait` swallows a failed job; wait on each so one fails the script.
for pid in "${pids[@]}"; do wait "$pid"; done

# The cache keeps files, not processes: create the role now (it persists in
# the data directory), start the services per session with rails-services-up.
service postgresql start
su postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='root'\"" | grep -q 1 \
  || su postgres -c "psql -c 'CREATE ROLE root SUPERUSER LOGIN'"
service postgresql stop

cat > /usr/local/bin/rails-services-up <<'EOF'
#!/usr/bin/env bash
# Idempotent: install the repo's Rubies, start Postgres and Redis.
ruby-up
service postgresql status >/dev/null 2>&1 || service postgresql start >/dev/null
redis-cli ping >/dev/null 2>&1 || redis-server --daemonize yes >/dev/null
EOF
chmod +x /usr/local/bin/rails-services-up

cat >> ~/.claude/CLAUDE.md <<'EOF'

## Rails in cloud sessions

Before `bundle install`, `bin/rails db:prepare`, or any test run, run `rails-services-up` (installs the repo's Rubies, starts Postgres and Redis; safe to repeat). Postgres accepts the `root` role without a password. If `ruby -v` still disagrees with `.ruby-version`, say so instead of switching versions.
EOF
