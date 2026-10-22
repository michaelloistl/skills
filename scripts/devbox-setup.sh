#!/usr/bin/env bash
# Dev box bootstrap for Ubuntu 24.04 droplet. Either paste into DO "Startup scripts"
# (user-data, runs as root on first boot; log: /var/log/cloud-init-output.log), or run as root:
#   scp devbox-setup.sh root@<ip>:~ && ssh root@<ip> 'bash devbox-setup.sh'
# Idempotent: safe to re-run.
set -euo pipefail

DEV_USER="${DEV_USER:-michael}"
SWAP_SIZE="${SWAP_SIZE:-4G}"
PG_VERSION="${PG_VERSION:-18}"
RUBIES="${RUBIES:-3.4.2 3.3.4}"
NODE_VERSION="${NODE_VERSION:-22}"
TZ_NAME="${TZ_NAME:-Atlantic/Madeira}"
SKILLS_REPO="${SKILLS_REPO:-michaelloistl/skills}"
# subset of mattpocock/skills installed on the Mac (resolving-merge-conflicts comes from SKILLS_REPO)
MATT_SKILLS="${MATT_SKILLS:-ask-matt chief-of-staff claude-handoff code-review codebase-design diagnosing-bugs domain-modeling git-guardrails-claude-code grill-me grill-with-docs grilling handoff implement implement-spec improve-codebase-architecture loop-me migrate-to-shoehorn pr prototype research retro scaffold-exercises setup-matt-pocock-skills setup-pre-commit setup-ts-deep-modules tdd teach to-questionnaire to-spec to-tickets triage wait-what wayfinder wizard writing-beats writing-for-agents writing-fragments writing-shape}"

[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }
export DEBIAN_FRONTEND=noninteractive
export HOME="${HOME:-/root}"  # unset when run as DO user-data
# first boot: wait for unattended-upgrades instead of failing on dpkg lock
echo 'DPkg::Lock::Timeout "600";' > /etc/apt/apt.conf.d/99-lock-timeout

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

log "Base packages"
apt-get update
apt-get upgrade -y
apt-get install -y \
  build-essential git curl wget ca-certificates gnupg unzip zip \
  zsh htop jq ripgrep fd-find tree direnv \
  ufw fail2ban unattended-upgrades \
  libssl-dev libyaml-dev libreadline-dev zlib1g-dev libffi-dev libgmp-dev \
  libpq-dev libvips libvips-dev pkg-config \
  fonts-liberation fonts-noto-color-emoji
timedatectl set-timezone "$TZ_NAME"

log "Swap ($SWAP_SIZE)"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l "$SWAP_SIZE" /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo 'vm.swappiness=10' > /etc/sysctl.d/99-swap.conf
  sysctl -p /etc/sysctl.d/99-swap.conf
fi

log "User $DEV_USER"
if ! id "$DEV_USER" &>/dev/null; then
  adduser --disabled-password --gecos "" --shell /usr/bin/zsh "$DEV_USER"
  usermod -aG sudo "$DEV_USER"
fi
echo "$DEV_USER ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-$DEV_USER"
chmod 440 "/etc/sudoers.d/90-$DEV_USER"
install -d -m 700 -o "$DEV_USER" -g "$DEV_USER" "/home/$DEV_USER/.ssh"
if [ -f /root/.ssh/authorized_keys ]; then
  install -m 600 -o "$DEV_USER" -g "$DEV_USER" /root/.ssh/authorized_keys "/home/$DEV_USER/.ssh/authorized_keys"
fi

log "SSH hardening + firewall"
cat > /etc/ssh/sshd_config.d/99-hardening.conf <<EOF
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
AllowUsers $DEV_USER
EOF
systemctl try-reload-or-restart ssh  # 24.04 socket-activated: may be inactive
ufw allow OpenSSH
ufw allow 41641/udp  # tailscale direct connections
ufw --force enable
systemctl enable --now fail2ban
dpkg-reconfigure -f noninteractive unattended-upgrades

log "PostgreSQL $PG_VERSION + PostGIS"
install -d /usr/share/postgresql-common/pgdg
curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release; echo "$VERSION_CODENAME")-pgdg main" \
  > /etc/apt/sources.list.d/pgdg.list
apt-get update
apt-get install -y "postgresql-$PG_VERSION" "postgresql-$PG_VERSION-postgis-3" "postgresql-contrib"
systemctl enable --now postgresql
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='$DEV_USER'" | grep -q 1 \
  || sudo -u postgres createuser -s "$DEV_USER"

log "Redis"
apt-get install -y redis-server
systemctl enable --now redis-server

log "Google Chrome (Grover/Puppeteer + system deps)"
if ! command -v google-chrome &>/dev/null; then
  curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
  echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google-chrome.list
  apt-get update
  apt-get install -y google-chrome-stable
fi

log "GitHub CLI"
if ! command -v gh &>/dev/null; then
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /usr/share/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list
  apt-get update
  apt-get install -y gh
fi

log "Stripe CLI (gospel-time webhooks)"
if ! command -v stripe &>/dev/null; then
  curl -fsSL https://packages.stripe.dev/api/security/keypair/stripe-cli-gpg/public | gpg --dearmor -o /usr/share/keyrings/stripe.gpg
  echo "deb [signed-by=/usr/share/keyrings/stripe.gpg] https://packages.stripe.dev/stripe-cli-debian-local stable main" \
    > /etc/apt/sources.list.d/stripe.list
  apt-get update
  apt-get install -y stripe
fi

log "Tailscale"
command -v tailscale &>/dev/null || curl -fsSL https://tailscale.com/install.sh | sh

log "User-level toolchain (mise, ruby, node, claude)"
sudo -iu "$DEV_USER" env RUBIES="$RUBIES" NODE_VERSION="$NODE_VERSION" \
  SKILLS_REPO="$SKILLS_REPO" MATT_SKILLS="$MATT_SKILLS" bash <<'USER_EOF'
set -euo pipefail

command -v ~/.local/bin/mise &>/dev/null || curl -fsSL https://mise.run | sh
export PATH="$HOME/.local/bin:$PATH"

mkdir -p ~/.config/mise
cat > ~/.config/mise/config.toml <<EOF
[settings]
idiomatic_version_file_enable_tools = ["ruby", "node"]
experimental = true
node.corepack = true  # yarn shim for every node version, not just the default

[tools]
node = "$NODE_VERSION"
EOF

for v in $RUBIES; do mise install "ruby@$v"; done
mise use -g "ruby@${RUBIES%% *}"
mise install "node@$NODE_VERSION"
mise use -g lazygit@latest  # not in 24.04 apt
eval "$(mise activate bash)"
corepack enable
corepack prepare yarn@1 --activate

command -v ~/.local/bin/claude &>/dev/null || curl -fsSL https://claude.ai/install.sh | bash

# Skills: third-party via `npx skills` into ~/.agents/skills (symlinked into ~/.claude/skills),
# own repo cloned to ~/Development/skills and linked by its link-skills.sh.
# No -a flag: naming a single agent makes the CLI copy instead of symlink.
npx -y skills@latest add mattpocock/skills -g -y -s $MATT_SKILLS </dev/null
npx -y skills@latest add humanlayer/skills -g -y -s show-me </dev/null
npx -y skills@latest add vercel-labs/skills -g -y -s find-skills </dev/null
if [ ! -d ~/Development/skills ]; then
  # https: public, works before gh auth; ssh remote so pushes work after it
  git clone "https://github.com/$SKILLS_REPO" ~/Development/skills
  git -C ~/Development/skills remote set-url origin "git@github.com:$SKILLS_REPO.git"
fi
~/Development/skills/scripts/link-skills.sh

[ -f ~/.ssh/id_ed25519 ] || ssh-keygen -t ed25519 -N "" -C "$(whoami)@$(hostname)" -f ~/.ssh/id_ed25519

# .zshenv is read by non-interactive ssh too (herdr machine, scripted ssh commands)
grep -qs 'local/bin' ~/.zshenv || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshenv
# mise shims: per-dir ruby/node for non-interactive shells (Zed remote server, ruby-lsp)
grep -qs 'mise/shims' ~/.zshenv || echo 'export PATH="$HOME/.local/share/mise/shims:$PATH"' >> ~/.zshenv

[ -d ~/.oh-my-zsh ] || RUNZSH=no CHSH=no KEEP_ZSHRC=yes \
  sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended
[ -f ~/.zshrc ] && ! grep -q oh-my-zsh ~/.zshrc && cp ~/.zshrc ~/.zshrc.pre-omz.bak
cat > ~/.zshrc <<'EOF'
# Mirrors the Mac ~/.zshrc (oh-my-zsh robbyrussell + ai:(...) segment), adapted for the dev box
export ZSH="$HOME/.oh-my-zsh"
ZSH_THEME="robbyrussell"
plugins=(git rails ruby)
source $ZSH/oh-my-zsh.sh

export PATH="$HOME/.local/bin:$PATH"
eval "$(mise activate zsh)"
eval "$(direnv hook zsh)"
export EDITOR=vim
alias fd=fdfind
alias lg=lazygit

alias on-vantage="cd ~/Development/on/on-vantage"
alias on-gospel-time="cd ~/Development/on/gospel-time/web"
alias aplo-skills="cd ~/Development/skills"
alias restart-session="exec zsh"

# Same per-project Claude config switch as the Mac; only switches if ~/.claude-on exists here
typeset -ga CLAUDE_WORK_PATHS=(
  "$HOME/Development/on/on-vantage"
  "$HOME/Development/on/worktrees/on-vantage"
)
_claude_config_dir_update() {
  local dir=${PWD:A}
  local want="$HOME/.claude"
  if [[ $dir == ${HOME:A}/.herdr/worktrees/* ]]; then
    local common
    common=$(git -C "$dir" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
    [[ -n $common ]] && dir=${common:h}
  fi
  local p
  if [[ -d $HOME/.claude-on ]]; then
    for p in $CLAUDE_WORK_PATHS; do
      if [[ $dir == ${p}* ]]; then
        want="$HOME/.claude-on"
        break
      fi
    done
  fi
  export CLAUDE_CONFIG_DIR=$want
  CLAUDE_PROMPT_LABEL=${${want:t}#.}
}
autoload -Uz add-zsh-hook
add-zsh-hook chpwd _claude_config_dir_update
_claude_config_dir_update

# host tag so remote panes are distinguishable from local ones
PROMPT="%{$fg[yellow]%}%m%{$reset_color%} $PROMPT"
PROMPT+='%{$fg_bold[blue]%}ai:(%{$fg[red]%}${CLAUDE_PROMPT_LABEL}%{$fg_bold[blue]%})%{$reset_color%} '
EOF

mkdir -p ~/Development/on
USER_EOF

touch /var/log/devbox-setup.done

cat <<EOF

=============================================================
Done. Next steps (as $DEV_USER — root SSH is now disabled):

  ssh $DEV_USER@<ip>
  sudo tailscale up                 # then reach dev servers at http://<tailscale-name>:4000
  gh auth login                     # pick SSH, upload ~/.ssh/id_ed25519.pub

  # From Mac (needs "Host <name>" in ~/.ssh/config):
  herdr machine add <name>                              # installs herdr on the box
  ~/Development/skills/scripts/devbox-push-claude-config.sh <name>    # ~/.claude + ~/.claude-on, hooks, statusline, dev-up, herdr hook
  # then log in once per config: claude in ~ (personal) and in ~/Development/on/on-vantage (ON)

  # Projects
  cd ~/Development/on
  git clone git@github.com:madebyon/on-vantage.git
  mkdir -p gospel-time && git clone git@github.com:madebyon/gospel-time.git gospel-time/web

  # Secrets (from Mac): config/credentials/{development,test}.key, .env.*.local (no prod/staging keys)
  # e.g. scp ~/Development/on/on-vantage/{.env.development.local,.env.test.local} $DEV_USER@<ip>:~/Development/on/on-vantage/

  # Per project (gospel-time/web connects as "postgres": printf '[env]\nDB_USERNAME = "$DEV_USER"\n' > mise.local.toml)
  mise trust && mise install && bundle install && yarn install && bin/rails db:prepare && bin/dev
  # bind to all interfaces for tailscale access: bin/rails s -b 0.0.0.0
=============================================================
EOF
