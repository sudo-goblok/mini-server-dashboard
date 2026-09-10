#!/bin/sh
set -eu

APP_NAME="${APP_NAME:-mini-server-dashboard}"
REPO_URL="${REPO_URL:-https://github.com/sudo-goblok/mini-server-dashboard.git}"
PORT="${PORT:-19090}"
DASHBOARD_USER="${DASHBOARD_USER:-${SUDO_USER:-}}"
FORCE_UPDATE="${FORCE_UPDATE:-0}"
OPEN_FIREWALL="${OPEN_FIREWALL:-0}"

log() { printf '\033[1;34m[mini-dashboard]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warning]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        if command -v sudo >/dev/null 2>&1; then
            exec sudo -E sh "$0" "$@"
        fi
        die "Installer membutuhkan akses root. Jalankan sebagai root atau pasang sudo."
    fi
}

require_root "$@"

case "$PORT" in
    ''|*[!0-9]*) die "PORT harus berupa angka 1-65535." ;;
esac
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
    die "PORT harus berada pada rentang 1-65535."
fi

SCRIPT_DIR=""
case "$0" in
    */*) SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || true) ;;
    *) [ -f "./$0" ] && SCRIPT_DIR=$(pwd) || true ;;
esac

if [ -z "${INSTALL_DIR:-}" ]; then
    if [ -n "$SCRIPT_DIR" ] && [ -d "$SCRIPT_DIR/.git" ] && [ -f "$SCRIPT_DIR/server.py" ]; then
        INSTALL_DIR="$SCRIPT_DIR"
    else
        INSTALL_DIR="/opt/mini-server-dashboard"
    fi
fi

case "$INSTALL_DIR" in
    *" "*) die "INSTALL_DIR tidak boleh mengandung spasi." ;;
esac

if [ -z "$DASHBOARD_USER" ] || [ "$DASHBOARD_USER" = "root" ]; then
    candidate=$(awk -F: '$3 >= 1000 && $3 < 65534 && $7 !~ /(nologin|false)$/ {print $1; exit}' /etc/passwd 2>/dev/null || true)
    [ -n "$candidate" ] || die "Tidak menemukan user Linux normal. Gunakan DASHBOARD_USER=<user> sudo -E sh install.sh"
    DASHBOARD_USER="$candidate"
    warn "DASHBOARD_USER tidak diberikan; memakai user '$DASHBOARD_USER'."
fi
id "$DASHBOARD_USER" >/dev/null 2>&1 || die "User '$DASHBOARD_USER' tidak ditemukan."
DASHBOARD_GROUP=$(id -gn "$DASHBOARD_USER")

OS_ID="unknown"
PRETTY_NAME_LOCAL="Linux"
if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    OS_ID="${ID:-unknown}"
    PRETTY_NAME_LOCAL="${PRETTY_NAME:-$OS_ID}"
fi

install_packages() {
    log "Mendeteksi distro: $PRETTY_NAME_LOCAL"
    if command -v apt-get >/dev/null 2>&1; then
        export DEBIAN_FRONTEND=noninteractive
        apt-get update
        apt-get install -y python3 python3-pip python3-venv python3-dev build-essential libpam0g-dev git curl ca-certificates
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y python3 python3-pip python3-devel gcc make pam-devel git curl ca-certificates
    elif command -v yum >/dev/null 2>&1; then
        yum install -y python3 python3-pip python3-devel gcc make pam-devel git curl ca-certificates
    elif command -v microdnf >/dev/null 2>&1; then
        microdnf install -y python3 python3-pip python3-devel gcc make pam-devel git curl ca-certificates
    elif command -v pacman >/dev/null 2>&1; then
        pacman -Sy --noconfirm --needed python python-pip base-devel pam git curl ca-certificates
    elif command -v zypper >/dev/null 2>&1; then
        zypper --non-interactive refresh
        zypper --non-interactive install python3 python3-pip python3-devel gcc make pam-devel git curl ca-certificates
    elif command -v apk >/dev/null 2>&1; then
        apk add --no-cache python3 py3-pip python3-dev build-base linux-headers linux-pam linux-pam-dev git curl ca-certificates
    elif command -v xbps-install >/dev/null 2>&1; then
        xbps-install -Sy python3 python3-pip python3-devel base-devel pam pam-devel git curl ca-certificates
    elif command -v emerge >/dev/null 2>&1; then
        emerge --noreplace dev-lang/python dev-python/pip sys-libs/pam dev-vcs/git net-misc/curl app-misc/ca-certificates
    else
        warn "Package manager tidak dikenali; mencoba memakai dependency yang sudah tersedia."
    fi
}

install_packages
command -v python3 >/dev/null 2>&1 || die "python3 tidak tersedia setelah instalasi dependency."
command -v git >/dev/null 2>&1 || die "git tidak tersedia setelah instalasi dependency."

log "Menyiapkan aplikasi di $INSTALL_DIR"
if [ -d "$INSTALL_DIR/.git" ]; then
    if [ "$FORCE_UPDATE" != "1" ]; then
        if ! git -C "$INSTALL_DIR" diff --quiet || ! git -C "$INSTALL_DIR" diff --cached --quiet; then
            die "Repository memiliki perubahan lokal. Commit/stash dulu atau jalankan FORCE_UPDATE=1."
        fi
    fi
    git -C "$INSTALL_DIR" fetch origin master
    if [ "$FORCE_UPDATE" = "1" ]; then
        git -C "$INSTALL_DIR" reset --hard origin/master
    else
        current_branch=$(git -C "$INSTALL_DIR" rev-parse --abbrev-ref HEAD)
        [ "$current_branch" = "master" ] || die "Checkout lokal berada di branch '$current_branch'. Pindah ke master atau gunakan FORCE_UPDATE=1."
        git -C "$INSTALL_DIR" merge --ff-only origin/master
    fi
elif [ -e "$INSTALL_DIR" ] && [ -n "$(find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | head -n 1)" ]; then
    die "$INSTALL_DIR sudah ada dan bukan checkout git. Gunakan INSTALL_DIR lain."
else
    rm -rf "$INSTALL_DIR"
    git clone --depth 1 --branch master "$REPO_URL" "$INSTALL_DIR"
fi

log "Membuat Python virtual environment"
if ! python3 -m venv "$INSTALL_DIR/.venv"; then
    die "Gagal membuat virtualenv. Pastikan modul venv/ensurepip tersedia pada distro ini."
fi
"$INSTALL_DIR/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

SECRET_FILE="$INSTALL_DIR/.dashboard.env"
SECRET=""
if [ -r "$SECRET_FILE" ]; then
    SECRET=$(sed -n 's/^DASHBOARD_SECRET_KEY=//p' "$SECRET_FILE" | head -n 1 || true)
fi
if [ -z "$SECRET" ]; then
    SECRET=$("$INSTALL_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))')
fi

TMP_ENV=$(mktemp)
if [ -r "$SECRET_FILE" ]; then
    grep -Ev '^(DASHBOARD_SECRET_KEY|PORT)=' "$SECRET_FILE" > "$TMP_ENV" || true
fi
{
    printf 'DASHBOARD_SECRET_KEY=%s\n' "$SECRET"
    printf 'PORT=%s\n' "$PORT"
    cat "$TMP_ENV"
} > "$SECRET_FILE"
rm -f "$TMP_ENV"

chown -R "$DASHBOARD_USER:$DASHBOARD_GROUP" "$INSTALL_DIR"
chmod 0755 "$INSTALL_DIR"
chmod 0600 "$SECRET_FILE"

install_systemd() {
    log "Memasang systemd service"
    cat > "/etc/systemd/system/$APP_NAME.service" <<EOF_SYSTEMD
[Unit]
Description=Mini Server Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$DASHBOARD_USER
Group=$DASHBOARD_GROUP
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$SECRET_FILE
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF_SYSTEMD
    systemctl daemon-reload
    systemctl enable "$APP_NAME.service" >/dev/null 2>&1 || true
    systemctl restart "$APP_NAME.service"
}

install_openrc() {
    log "Memasang OpenRC service"
    cat > "/etc/init.d/$APP_NAME" <<EOF_OPENRC
#!/sbin/openrc-run
name="Mini Server Dashboard"
description="Mini Server Dashboard"
command="$INSTALL_DIR/.venv/bin/python"
command_args="$INSTALL_DIR/server.py"
command_user="$DASHBOARD_USER:$DASHBOARD_GROUP"
directory="$INSTALL_DIR"
pidfile="/run/$APP_NAME.pid"
command_background="yes"
output_log="/var/log/$APP_NAME.log"
error_log="/var/log/$APP_NAME.log"

depend() {
    need net
}

start_pre() {
    set -a
    . "$SECRET_FILE"
    set +a
}
EOF_OPENRC
    chmod 0755 "/etc/init.d/$APP_NAME"
    rc-update add "$APP_NAME" default >/dev/null 2>&1 || true
    rc-service "$APP_NAME" restart || rc-service "$APP_NAME" start
}

install_runit() {
    log "Memasang runit service"
    SERVICE_DIR="/etc/sv/$APP_NAME"
    mkdir -p "$SERVICE_DIR"
    cat > "$SERVICE_DIR/run" <<EOF_RUNIT
#!/bin/sh
set -a
. "$SECRET_FILE"
set +a
cd "$INSTALL_DIR"
exec chpst -u "$DASHBOARD_USER:$DASHBOARD_GROUP" "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/server.py"
EOF_RUNIT
    chmod 0755 "$SERVICE_DIR/run"
    if [ -d /var/service ]; then
        ln -sfn "$SERVICE_DIR" "/var/service/$APP_NAME"
    elif [ -d /etc/service ]; then
        ln -sfn "$SERVICE_DIR" "/etc/service/$APP_NAME"
    else
        die "runit terdeteksi tetapi direktori service aktif tidak ditemukan."
    fi
    sv up "$APP_NAME" >/dev/null 2>&1 || true
}

install_sysv() {
    log "Memasang SysV init service"
    cat > "/etc/init.d/$APP_NAME" <<EOF_SYSV
#!/bin/sh
### BEGIN INIT INFO
# Provides:          $APP_NAME
# Required-Start:    \$network
# Required-Stop:     \$network
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: Mini Server Dashboard
### END INIT INFO
PIDFILE=/run/$APP_NAME.pid
APPDIR="$INSTALL_DIR"
PYTHON="$INSTALL_DIR/.venv/bin/python"
USER="$DASHBOARD_USER"
ENVFILE="$SECRET_FILE"
case "\${1:-}" in
  start)
    set -a; . "\$ENVFILE"; set +a
    start-stop-daemon --start --background --make-pidfile --pidfile "\$PIDFILE" --chuid "\$USER" --chdir "\$APPDIR" --startas "\$PYTHON" -- "\$APPDIR/server.py"
    ;;
  stop)
    start-stop-daemon --stop --pidfile "\$PIDFILE" --remove-pidfile || true
    ;;
  restart)
    "\$0" stop
    sleep 1
    "\$0" start
    ;;
  status)
    if [ -r "\$PIDFILE" ] && kill -0 "\$(cat "\$PIDFILE")" 2>/dev/null; then exit 0; else exit 3; fi
    ;;
  *) echo "Usage: \$0 {start|stop|restart|status}"; exit 2 ;;
esac
EOF_SYSV
    chmod 0755 "/etc/init.d/$APP_NAME"
    if command -v update-rc.d >/dev/null 2>&1; then
        update-rc.d "$APP_NAME" defaults
    elif command -v chkconfig >/dev/null 2>&1; then
        chkconfig --add "$APP_NAME"
        chkconfig "$APP_NAME" on
    fi
    "/etc/init.d/$APP_NAME" restart
}

if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    install_systemd
    INIT_KIND="systemd"
elif command -v rc-service >/dev/null 2>&1 && command -v rc-update >/dev/null 2>&1; then
    install_openrc
    INIT_KIND="openrc"
elif command -v sv >/dev/null 2>&1 && command -v chpst >/dev/null 2>&1; then
    install_runit
    INIT_KIND="runit"
elif command -v start-stop-daemon >/dev/null 2>&1 && [ -d /etc/init.d ]; then
    install_sysv
    INIT_KIND="sysv"
else
    warn "Init system tidak didukung otomatis. Aplikasi tetap terpasang."
    warn "Jalankan manual: set -a; . $SECRET_FILE; set +a; sudo -u $DASHBOARD_USER $INSTALL_DIR/.venv/bin/python $INSTALL_DIR/server.py"
    INIT_KIND="manual"
fi

if [ "$OPEN_FIREWALL" = "1" ]; then
    if command -v firewall-cmd >/dev/null 2>&1; then
        firewall-cmd --permanent --add-port="$PORT/tcp"
        firewall-cmd --reload
    elif command -v ufw >/dev/null 2>&1; then
        ufw allow "$PORT/tcp"
    else
        warn "OPEN_FIREWALL=1 tetapi firewalld/ufw tidak ditemukan."
    fi
fi

HTTP_CODE=""
i=0
while [ "$i" -lt 12 ]; do
    HTTP_CODE=$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/" 2>/dev/null || true)
    case "$HTTP_CODE" in
        200|301|302|303|307|308) break ;;
    esac
    i=$((i + 1))
    sleep 1
done

IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
log "Instalasi selesai."
printf '\nDistro       : %s\nUser service : %s\nInstall dir  : %s\nInit system  : %s\nPort         : %s\n' \
    "$PRETTY_NAME_LOCAL" "$DASHBOARD_USER" "$INSTALL_DIR" "$INIT_KIND" "$PORT"
[ -n "$IP_ADDR" ] && printf 'Dashboard    : http://%s:%s\n' "$IP_ADDR" "$PORT"
printf 'Local check  : http://127.0.0.1:%s (HTTP %s)\n\n' "$PORT" "${HTTP_CODE:-unreachable}"

case "$HTTP_CODE" in
    200|301|302|303|307|308) ;;
    *)
        warn "Health check belum berhasil. Cek status/log service."
        if [ "$INIT_KIND" = "systemd" ]; then
            systemctl --no-pager --full status "$APP_NAME.service" || true
            journalctl -u "$APP_NAME.service" -n 30 --no-pager || true
        fi
        exit 1
        ;;
esac
