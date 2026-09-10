# Mini Server Dashboard

Lightweight Flask dashboard for monitoring and controlled management of a Linux/GPU server.

## Features

- Live CPU, per-core usage, memory, disk, GPU and network monitoring (2-second refresh)
- Persistent drag-and-drop Overview cards
- Sidebar navigation for Overview, Services, Processes, Storage, Network, GPU and System Info
- systemd service inventory with explicit allowlist-based Start/Stop/Restart actions
- Process inventory with same-user SIGTERM management
- Storage/mount detail similar to `df -h`
- Per-interface network counters and throughput chart
- NVIDIA GPU telemetry from `nvidia-smi` with GPUtil fallback
- Linux PAM authentication
- CSRF protection for management POST actions

## Requirements

```bash
python3 -m pip install -r requirements.txt
```

## Run manually

```bash
python3 app.py
```

Dashboard listens on `0.0.0.0:5000`.

## systemd install

```bash
sudo cp systemd/mini-server-dashboard.service /etc/systemd/system/mini-server-dashboard.service
sudo systemctl daemon-reload
sudo systemctl enable --now mini-server-dashboard.service
sudo systemctl status mini-server-dashboard.service --no-pager
```

The bundled unit assumes:

- app directory: `/Apps/dashboard`
- OS user: `deepuser`
- Python: `/usr/bin/python3`

Adjust the unit if your installation differs.

## Controlled service management

Service listing is read-only by default. Actions are only exposed for service names configured in `DASHBOARD_MANAGED_SERVICES`.

Create a systemd override:

```bash
sudo systemctl edit mini-server-dashboard.service
```

Example:

```ini
[Service]
Environment="DASHBOARD_MANAGED_SERVICES=docker.service,nginx.service,ssh.service"
```

Then reload/restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart mini-server-dashboard.service
```

The application deliberately calls `systemctl --no-ask-password` without embedding or handling sudo credentials. Start/Stop/Restart therefore also depends on the OS policy for the account running the dashboard. Configure systemd/Polkit privileges separately if you want those actions to succeed.

## Security notes

- Login uses Linux PAM.
- Management requests require a session CSRF token.
- A login can issue management actions only when the authenticated PAM username matches the OS account running the dashboard process.
- Service names are validated and must be explicitly allowlisted; arbitrary shell commands are not accepted.
- `mini-server-dashboard.service` cannot manage itself from the web UI.
- Process termination is limited to processes owned by the dashboard OS user; PID 1 and the dashboard process are protected.
- Reboot/shutdown and arbitrary terminal execution are intentionally not exposed.
