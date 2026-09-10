#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="mini-server-dashboard"
REPO_URL="${REPO_URL:-https://github.com/sudo-goblok/mini-server-dashboard.git}"
INSTALL_DIR="${INSTALL_DIR:-/opt/mini-server-dashboard}"
PORT="${PORT:-5000}"
DASHBOARD_USER="${DASHBOARD_USER:-${SUDO_USER:-}}"

log() { printf '\033[1;34m[mini-dashboard]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warning]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
      exec sudo -E bash "$0" "$@"
    fi
    die "Installer membutuhkan akses root. Jalankan sebagai root atau pasang sudo."
  fi
}

require_root "$@"

if [ -z "$DASHBOARD_USER" ] || [ "$DASHBOARD_USER" = "root" ]; then
  if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
    DASHBOARD_USER="$SUDO_USER"
  else
    candidate="$(awk -F: '$3 >= 1000 && $3 < 65534 && $7 !~ /(nologin|false)$/ {print $1; exit}' /etc/passwd || true)"
    [ -n "$candidate" ] || die "Tidak menemukan user Linux normal. Jalankan dengan DASHBOARD_USER=<user> sudo -E ./install.sh"
    DASHBOARD_USER="$candidate"
    warn "DASHBOARD_USER tidak diberikan; memakai user '$DASHBOARD_USER'."
  fi
fi
id "$DASHBOARD_USER" >/dev/null 2>&1 || die "User '$DASHBOARD_USER' tidak ditemukan."

OS_ID="unknown"
OS_LIKE=""
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  OS_ID="${ID:-unknown}"
  OS_LIKE="${ID_LIKE:-}"
fi

install_packages() {
  log "Mendeteksi distro: ${PRETTY_NAME:-$OS_ID}"
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y python3 python3-pip python3-venv python3-dev build-essential libpam0g-dev git curl ca-certificates
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y python3 python3-pip python3-devel gcc make pam-devel git curl ca-certificates
  elif command -v yum >/dev/null 2>&1; then
    yum install -y python3 python3-pip python3-devel gcc make pam-devel git curl ca-certificates
  elif command -v pacman >/dev/null 2>&1; then
    pacman -Sy --noconfirm --needed python python-pip base-devel pam git curl ca-certificates
  elif command -v zypper >/dev/null 2>&1; then
    zypper --non-interactive refresh
    zypper --non-interactive install python3 python3-pip python3-devel gcc make pam-devel git curl ca-certificates
  elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache python3 py3-pip python3-dev build-base linux-headers pam-dev git curl ca-certificates
  else
    die "Package manager tidak dikenali. Didukung otomatis: apt, dnf, yum, pacman, zypper, apk."
  fi
}

install_packages

log "Menyiapkan aplikasi di $INSTALL_DIR"
if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" fetch --all --prune
  git -C "$INSTALL_DIR" reset --hard origin/master
elif [ -e "$INSTALL_DIR" ] && [ "$(find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | head -n1)" ]; then
  die "$INSTALL_DIR sudah ada dan bukan checkout git. Pindahkan/hapus folder itu atau set INSTALL_DIR lain."
else
  rm -rf "$INSTALL_DIR"
  git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

chown -R "$DASHBOARD_USER":"$(id -gn "$DASHBOARD_USER")" "$INSTALL_DIR"
chmod 0755 "$INSTALL_DIR"

SECRET_FILE="$INSTALL_DIR/.dashboard.env"
if [ ! -f "$SECRET_FILE" ]; then
  SECRET="$($INSTALL_DIR/.venv/bin/python - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
  cat > "$SECRET_FILE" <<EOF
DASHBOARD_SECRET_KEY=$SECRET
PORT=$PORT
EOF
fi
chown "$DASHBOARD_USER":"$(id -gn "$DASHBOARD_USER")" "$SECRET_FILE"
chmod 0600 "$SECRET_FILE"

install_systemd() {
  log "Memasang systemd service"
  cat > /etc/systemd/system/${APP_NAME}.service <<EOF
[Unit]
Description=Mini Server Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$DASHBOARD_USER
Group=$(id -gn "$DASHBOARD_USER")
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$SECRET_FILE
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now ${APP_NAME}.service
  systemctl restart ${APP_NAME}.service
}

install_openrc() {
  log "Memasang OpenRC service"
  cat > /etc/init.d/${APP_NAME} <<EOF
#!/sbin/openrc-run
name="Mini Server Dashboard"
description="Mini Server Dashboard"
command="$INSTALL_DIR/.venv/bin/python"
command_args="$INSTALL_DIR/server.py"
command_user="$DASHBOARD_USER:$(id -gn "$DASHBOARD_USER")"
directory="$INSTALL_DIR"
pidfile="/run/${APP_NAME}.pid"
command_background="yes"
output_log="/var/log/${APP_NAME}.log"
error_log="/var/log/${APP_NAME}.log"
depend() { need net; }
start_pre() { export \$(grep -v '^#' '$SECRET_FILE' | xargs); }
EOF
  chmod +x /etc/init.d/${APP_NAME}
  rc-update add ${APP_NAME} default || true
  rc-service ${APP_NAME} restart || rc-service ${APP_NAME} start
}

if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  install_systemd
  INIT_KIND="systemd"
elif command -v rc-service >/dev/null 2>&1; then
  install_openrc
  INIT_KIND="openrc"
else
  warn "Init system tidak didukung otomatis. Aplikasi terpasang, tetapi service belum dibuat."
  warn "Jalankan manual: sudo -u $DASHBOARD_USER env PORT=$PORT $INSTALL_DIR/.venv/bin/python $INSTALL_DIR/server.py"
  INIT_KIND="manual"
fi

IP_ADDR="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
log "Instalasi selesai."
printf '\nUser service : %s\nInstall dir  : %s\nInit system  : %s\nPort         : %s\n' "$DASHBOARD_USER" "$INSTALL_DIR" "$INIT_KIND" "$PORT"
[ -n "$IP_ADDR" ] && printf 'Dashboard    : http://%s:%s\n' "$IP_ADDR" "$PORT"
printf 'Local check  : http://127.0.0.1:%s\n\n' "$PORT"

if [ "$INIT_KIND" = "systemd" ]; then
  systemctl --no-pager --full status ${APP_NAME}.service || true
elif [ "$INIT_KIND" = "openrc" ]; then
  rc-service ${APP_NAME} status || true
fi
