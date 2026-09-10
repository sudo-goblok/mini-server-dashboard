# Mini Server Dashboard

Lightweight Flask dashboard for monitoring and controlled management of a Linux/GPU server.

## Screenshot

![Mini Server Dashboard overview on gpu-server](docs/dashboard-overview.webp)

*Dashboard overview with live CPU, memory, swap, disk, GPU, network, and process monitoring on `gpu-server`.*

## Features

- Live CPU, per-core usage, memory, swap, disk, GPU and network monitoring
- Persistent drag-and-drop Overview cards
- Sidebar navigation for Overview, Services, Processes, Storage, Network, GPU and System Info
- Storage detail with `df -h` style columns
- systemd service inventory with controlled Start/Stop/Restart allowlist
- Process inventory with same-user SIGTERM management
- NVIDIA GPU telemetry from `nvidia-smi` with GPUtil fallback
- Linux PAM authentication
- CSRF protection for management POST actions

## Universal Linux installer

The recommended installation path is `install.sh`. It detects the package manager, installs Python/PAM/build dependencies, creates a virtual environment, generates a persistent dashboard secret, creates a boot service, starts the dashboard, and performs a local HTTP health check.

Supported package-manager families:

- Debian / Ubuntu and derivatives: `apt`
- Fedora / RHEL / Rocky / Alma / CentOS and derivatives: `dnf`, `yum`, `microdnf`
- Arch / Manjaro and derivatives: `pacman`
- openSUSE / SUSE: `zypper`
- Alpine: `apk`
- Void Linux: `xbps`
- Gentoo: `emerge`
- Other distributions: generic fallback when Python 3, Git and the required PAM/build dependencies are already installed

Supported init/service systems:

- systemd
- OpenRC
- runit
- SysV init with `start-stop-daemon`
- Other init systems fall back to a documented manual start command

### Install from a cloned repository

```bash
sudo sh install.sh
```

When executed from an existing checkout, the installer uses that checkout as the install directory. A clean `master` checkout is updated with a fast-forward only. Local changes are never discarded unless `FORCE_UPDATE=1` is explicitly set.

### One-line fresh install

```bash
curl -fsSL https://raw.githubusercontent.com/sudo-goblok/mini-server-dashboard/master/install.sh | sudo DASHBOARD_USER="$USER" sh
```

Fresh installs default to:

- install directory: `/opt/mini-server-dashboard`
- port: `19090`
- service user: the invoking Linux user when available

The dashboard is then available at:

```text
http://SERVER-IP:19090
```

### Installer options

```bash
sudo env \
  DASHBOARD_USER=myuser \
  INSTALL_DIR=/opt/mini-server-dashboard \
  PORT=19090 \
  OPEN_FIREWALL=0 \
  sh install.sh
```

Options:

- `DASHBOARD_USER`: Linux account used to run the dashboard service
- `INSTALL_DIR`: target checkout/application directory
- `PORT`: listening port, default `19090`
- `OPEN_FIREWALL=1`: optionally open the selected TCP port through firewalld or UFW
- `FORCE_UPDATE=1`: explicitly allow a hard reset of an existing checkout to `origin/master`
- `REPO_URL`: override repository URL

## Manual run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
PORT=19090 .venv/bin/python server.py
```

`server.py` listens on `0.0.0.0` and uses port `19090` by default. Set `PORT` to override it.

## Existing systemd installation

The universal installer can migrate an existing checkout and regenerate the service with the correct user, path, virtualenv and port configuration:

```bash
cd /path/to/mini-server-dashboard
sudo sh install.sh
```

The generated environment file is `.dashboard.env` and contains the persistent Flask secret plus the configured port. Existing additional environment keys are preserved.

## Controlled service management

Service listing is read-only by default. Actions are only exposed for service names configured in `DASHBOARD_MANAGED_SERVICES`.

For a systemd installation, add the variable to `.dashboard.env` or a systemd override, for example:

```text
DASHBOARD_MANAGED_SERVICES=docker.service,nginx.service,ssh.service
```

The application deliberately calls `systemctl --no-ask-password` without embedding or handling sudo credentials. Start/Stop/Restart therefore also depends on the OS policy for the account running the dashboard.

> Note: the dashboard's Services management page currently targets systemd. The dashboard itself can be installed and run under systemd, OpenRC, runit or SysV init, but equivalent OpenRC/runit service-management actions are not yet exposed in the web UI.

## Security notes

- Login uses Linux PAM.
- Management requests require a session CSRF token.
- A login can issue management actions only when the authenticated PAM username matches the OS account running the dashboard process.
- Service names are validated and must be explicitly allowlisted; arbitrary shell commands are not accepted.
- `mini-server-dashboard.service` cannot manage itself from the web UI.
- Process termination is limited to processes owned by the dashboard OS user; PID 1 and the dashboard process are protected.
- Reboot/shutdown and arbitrary terminal execution are intentionally not exposed.
