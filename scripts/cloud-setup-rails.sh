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

# Versions from the projects' .ruby-version files.
RUBIES=(3.3.10 3.3.11 3.4.2)
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

# Prebuilt Rubies via rv (seconds, not minutes), linked into rbenv so the
# repos' .ruby-version files resolve through the preinstalled shims.
(
  curl --proto '=https' --tlsv1.2 -LsSf \
    https://github.com/spinel-coop/rv/releases/latest/download/rv-installer.sh | sh >/dev/null
  rv=$HOME/.cargo/bin/rv
  for v in "${RUBIES[@]}"; do "$rv" ruby install "$v"; done
  versions="$(rbenv root)/versions"
  mkdir -p "$versions"
  for v in "${RUBIES[@]}"; do
    ln -sfn "$HOME/.local/share/rv/rubies/ruby-$v" "$versions/$v"
    "$versions/$v/bin/ruby" -ropenssl -rpsych -e '' # fail now, not mid-session
  done
  rbenv rehash
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
# Idempotent: start Postgres and Redis for this session.
service postgresql status >/dev/null 2>&1 || service postgresql start >/dev/null
redis-cli ping >/dev/null 2>&1 || redis-server --daemonize yes >/dev/null
EOF
chmod +x /usr/local/bin/rails-services-up

cat >> ~/.claude/CLAUDE.md <<'EOF'

## Rails in cloud sessions

Before `bundle install`, `bin/rails db:prepare`, or any test run, run `rails-services-up` (starts Postgres and Redis; safe to repeat). Postgres accepts the `root` role without a password. Rubies come from rbenv and match each repo's `.ruby-version`; if a version is missing, say so instead of switching versions.
EOF
