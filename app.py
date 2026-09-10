import os
import platform
import pwd
import re
import secrets
import socket
import subprocess
import time
from functools import wraps

import GPUtil
import pam
import psutil
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("DASHBOARD_SECRET_KEY") or os.urandom(32)

SERVICE_RE = re.compile(r"^[A-Za-z0-9_.@:-]+\.service$")
SERVICE_ACTIONS = {"start", "stop", "restart"}
SELF_SERVICE = "mini-server-dashboard.service"


def current_os_user():
    try:
        return pwd.getpwuid(os.geteuid()).pw_name
    except Exception:
        return None


def authenticated_user_can_manage():
    """Only let the PAM user matching the dashboard OS user issue management actions."""
    return bool(session.get("username") and session.get("username") == current_os_user())


def managed_services():
    raw = os.environ.get("DASHBOARD_MANAGED_SERVICES", "")
    return {
        item.strip()
        for item in raw.split(",")
        if item.strip() and SERVICE_RE.fullmatch(item.strip())
    }


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def check_csrf():
    supplied = request.headers.get("X-CSRF-Token", "")
    return bool(supplied and secrets.compare_digest(supplied, session.get("csrf_token", "")))


def check_auth(username, password):
    try:
        p = pam.pam()
        return p.authenticate(username, password)
    except Exception:
        return False


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/") or request.path == "/data":
                return jsonify({"ok": False, "error": "authentication required"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated


def management_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not check_csrf():
            return jsonify({"ok": False, "error": "invalid CSRF token"}), 403
        if not authenticated_user_can_manage():
            return jsonify({"ok": False, "error": "management is limited to the dashboard OS user"}), 403
        return f(*args, **kwargs)

    return decorated


def parse_nvidia_smi():
    result = []
    try:
        cmd = [
            "nvidia-smi",
            "--query-gpu=name,temperature.gpu,utilization.gpu,utilization.memory,"
            "clocks.current.sm,clocks.current.memory,clocks.current.video,"
            "clocks.current.graphics,power.draw,power.limit,"
            "memory.total,memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=5).decode("utf-8").strip()
        if not out:
            return result
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 13:
                continue
            try:
                result.append(
                    {
                        "name": parts[0],
                        "temperature": float(parts[1]) if parts[1] != "N/A" else None,
                        "gpu_util": float(parts[2]) if parts[2] != "N/A" else None,
                        "mem_util": float(parts[3]) if parts[3] != "N/A" else None,
                        "sm_clock": float(parts[4]) if parts[4] != "N/A" else None,
                        "mem_clock": float(parts[5]) if parts[5] != "N/A" else None,
                        "video_clock": float(parts[6]) if parts[6] != "N/A" else None,
                        "graphics_clock": float(parts[7]) if parts[7] != "N/A" else None,
                        "power_draw": float(parts[8]) if parts[8] != "N/A" else None,
                        "power_limit": float(parts[9]) if parts[9] != "N/A" else None,
                        "memory_total": float(parts[10]) if parts[10] != "N/A" else None,
                        "memory_used": float(parts[11]) if parts[11] != "N/A" else None,
                        "memory_free": float(parts[12]) if parts[12] != "N/A" else None,
                        "source": "nvidia-smi",
                    }
                )
            except (ValueError, IndexError):
                continue
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError):
        pass
    return result


def get_gputil_gpus():
    gpus = []
    try:
        for gpu in GPUtil.getGPUs():
            gpus.append(
                {
                    "id": gpu.id,
                    "name": gpu.name,
                    "load": gpu.load * 100,
                    "memoryTotal": gpu.memoryTotal,
                    "memoryUsed": gpu.memoryUsed,
                    "memoryFree": gpu.memoryFree,
                    "temperature": gpu.temperature,
                    "source": "gputil",
                }
            )
    except Exception:
        pass
    return gpus


def merge_gpu_data(smi_gpus, gputil_gpus):
    merged = []
    smi_by_name = {g["name"]: g for g in smi_gpus}
    for gputil_gpu in gputil_gpus:
        name = gputil_gpu["name"]
        smi = smi_by_name.get(name)
        if smi:
            merged.append(
                {
                    "id": gputil_gpu["id"],
                    "name": name,
                    "load": smi.get("gpu_util"),
                    "mem_util": smi.get("mem_util"),
                    "temperature": smi.get("temperature"),
                    "sm_clock": smi.get("sm_clock"),
                    "mem_clock": smi.get("mem_clock"),
                    "graphics_clock": smi.get("graphics_clock"),
                    "video_clock": smi.get("video_clock"),
                    "power_draw": smi.get("power_draw"),
                    "power_limit": smi.get("power_limit"),
                    "memoryTotal": smi.get("memory_total"),
                    "memoryUsed": smi.get("memory_used"),
                    "memoryFree": smi.get("memory_free"),
                    "source": "nvidia-smi+gputil",
                }
            )
        else:
            merged.append(
                {
                    "id": gputil_gpu["id"],
                    "name": name,
                    "load": gputil_gpu["load"],
                    "mem_util": None,
                    "temperature": gputil_gpu["temperature"],
                    "sm_clock": None,
                    "mem_clock": None,
                    "graphics_clock": None,
                    "video_clock": None,
                    "power_draw": None,
                    "power_limit": None,
                    "memoryTotal": gputil_gpu["memoryTotal"],
                    "memoryUsed": gputil_gpu["memoryUsed"],
                    "memoryFree": gputil_gpu["memoryFree"],
                    "source": "gputil-only",
                }
            )
    if not merged:
        for i, smi in enumerate(smi_gpus):
            merged.append(
                {
                    "id": i,
                    "name": smi["name"],
                    "load": smi.get("gpu_util"),
                    "mem_util": smi.get("mem_util"),
                    "temperature": smi.get("temperature"),
                    "sm_clock": smi.get("sm_clock"),
                    "mem_clock": smi.get("mem_clock"),
                    "graphics_clock": smi.get("graphics_clock"),
                    "video_clock": smi.get("video_clock"),
                    "power_draw": smi.get("power_draw"),
                    "power_limit": smi.get("power_limit"),
                    "memoryTotal": smi.get("memory_total"),
                    "memoryUsed": smi.get("memory_used"),
                    "memoryFree": smi.get("memory_free"),
                    "source": "nvidia-smi-only",
                }
            )
    return merged


def get_disk_detail():
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            device = part.device
            disks.append(
                {
                    "filesystem": os.path.basename(device) if device else device,
                    "device": device,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "opts": part.opts,
                    "total": usage.total,
                    "used": usage.used,
                    "available": usage.free,
                    "percent": usage.percent,
                }
            )
        except (PermissionError, OSError):
            continue
    return disks


def get_top_processes(limit=10):
    processes = []
    for proc in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_percent", "status"]):
        try:
            info = proc.info
            cpu = float(info.get("cpu_percent") or 0)
            mem = float(info.get("memory_percent") or 0)
            if cpu > 0 or mem > 0:
                processes.append(info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    processes.sort(key=lambda item: (item.get("cpu_percent") or 0, item.get("memory_percent") or 0), reverse=True)
    return processes[:limit]


def get_process_table(limit=100):
    processes = []
    for proc in psutil.process_iter(
        ["pid", "name", "username", "cpu_percent", "memory_percent", "status", "create_time", "cmdline"]
    ):
        try:
            info = proc.info
            cmdline = info.get("cmdline") or []
            processes.append(
                {
                    "pid": info["pid"],
                    "name": info.get("name") or "?",
                    "username": info.get("username") or "?",
                    "cpu_percent": float(info.get("cpu_percent") or 0),
                    "memory_percent": float(info.get("memory_percent") or 0),
                    "status": info.get("status") or "?",
                    "create_time": info.get("create_time"),
                    "command": " ".join(cmdline[:6])[:240],
                    "manageable": bool(
                        authenticated_user_can_manage()
                        and info.get("username") == current_os_user()
                        and info["pid"] not in (1, os.getpid())
                    ),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    processes.sort(key=lambda item: (item["cpu_percent"], item["memory_percent"]), reverse=True)
    return processes[:limit]


def get_system_info():
    boot = psutil.boot_time()
    try:
        load1, load5, load15 = os.getloadavg()
    except (AttributeError, OSError):
        load1 = load5 = load15 = None

    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "boot_time": boot,
        "uptime_seconds": max(0, time.time() - boot),
        "load_average": [load1, load5, load15],
        "cpu_physical": psutil.cpu_count(logical=False),
        "cpu_logical": psutil.cpu_count(logical=True),
        "dashboard_user": current_os_user(),
        "management_allowed": authenticated_user_can_manage(),
        "managed_services": sorted(managed_services()),
    }


def get_system_stats():
    hostname = socket.gethostname()
    ips = []
    try:
        for interface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    ips.append({"interface": interface, "ip": addr.address})
    except Exception:
        ips = [{"interface": "unknown", "ip": "N/A"}]

    cpu_percent_total = psutil.cpu_percent(interval=0.1)
    cpu_percent_per_cpu = psutil.cpu_percent(interval=0.1, percpu=True)
    cpu_count = psutil.cpu_count()
    cpu_freq = psutil.cpu_freq()
    mem = psutil.virtual_memory()

    disks = get_disk_detail()
    default_disk = next((d for d in disks if d["mountpoint"] == "/"), disks[0] if disks else None)

    net_io = psutil.net_io_counters()
    net_per_interface = {}
    pernic = psutil.net_io_counters(pernic=True)
    for ifname in psutil.net_if_addrs().keys():
        io = pernic.get(ifname)
        if io:
            net_per_interface[ifname] = {
                "bytes_sent": io.bytes_sent,
                "bytes_recv": io.bytes_recv,
                "packets_sent": io.packets_sent,
                "packets_recv": io.packets_recv,
                "errin": io.errin,
                "errout": io.errout,
                "dropin": io.dropin,
                "dropout": io.dropout,
            }

    gpus = merge_gpu_data(parse_nvidia_smi(), get_gputil_gpus())

    return {
        "hostname": hostname,
        "ips": ips,
        "net_io": {
            "bytes_sent": net_io.bytes_sent,
            "bytes_recv": net_io.bytes_recv,
            "packets_sent": net_io.packets_sent,
            "packets_recv": net_io.packets_recv,
        },
        "net_per_interface": net_per_interface,
        "cpu": {
            "percent": cpu_percent_total,
            "per_cpu": cpu_percent_per_cpu,
            "count": cpu_count,
            "frequency": cpu_freq.current if cpu_freq else None,
        },
        "memory": {
            "total": mem.total,
            "available": mem.available,
            "percent": mem.percent,
            "used": mem.used,
            "free": mem.free,
        },
        "disks": disks,
        "disk_default": default_disk,
        "gpus": gpus,
        "processes": get_top_processes(10),
        "system": get_system_info(),
        "timestamp": time.time(),
    }


def list_services():
    allowed = managed_services()
    try:
        proc = subprocess.run(
            [
                "systemctl",
                "list-units",
                "--type=service",
                "--all",
                "--no-legend",
                "--no-pager",
                "--plain",
                "--full",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return [], str(exc)

    services = []
    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        if line.startswith("●"):
            line = line[1:].strip()
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        name, load, active, sub = parts[:4]
        description = parts[4] if len(parts) > 4 else ""
        if not SERVICE_RE.fullmatch(name):
            continue
        services.append(
            {
                "name": name,
                "load": load,
                "active": active,
                "sub": sub,
                "description": description,
                "manageable": bool(authenticated_user_can_manage() and name in allowed and name != SELF_SERVICE),
            }
        )

    services.sort(key=lambda item: (item["active"] != "active", item["name"]))
    error = proc.stderr.strip() if proc.returncode != 0 else None
    return services, error


@app.route("/")
@login_required
def index():
    return render_template("index.html", csrf_token=csrf_token())


@app.route("/data")
@login_required
def data():
    stats = get_system_stats()
    stats["user"] = session.get("username")
    return jsonify(stats)


@app.route("/api/services")
@login_required
def api_services():
    services, error = list_services()
    return jsonify(
        {
            "ok": error is None,
            "services": services,
            "error": error,
            "managed_services": sorted(managed_services()),
            "management_allowed": authenticated_user_can_manage(),
        }
    )


@app.route("/api/services/<service>/<action>", methods=["POST"])
@management_required
def api_service_action(service, action):
    if not SERVICE_RE.fullmatch(service):
        return jsonify({"ok": False, "error": "invalid service name"}), 400
    if action not in SERVICE_ACTIONS:
        return jsonify({"ok": False, "error": "unsupported action"}), 400
    if service == SELF_SERVICE:
        return jsonify({"ok": False, "error": "the dashboard service is protected from self-management"}), 400
    if service not in managed_services():
        return jsonify({"ok": False, "error": "service is not in DASHBOARD_MANAGED_SERVICES"}), 403

    try:
        proc = subprocess.run(
            ["systemctl", "--no-ask-password", action, service],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "systemctl action failed").strip()
        return jsonify({"ok": False, "error": message}), 403

    return jsonify({"ok": True, "service": service, "action": action})


@app.route("/api/processes")
@login_required
def api_processes():
    try:
        limit = int(request.args.get("limit", 100))
    except ValueError:
        limit = 100
    limit = min(max(limit, 10), 250)
    return jsonify({"ok": True, "processes": get_process_table(limit), "management_allowed": authenticated_user_can_manage()})


@app.route("/api/processes/<int:pid>/terminate", methods=["POST"])
@management_required
def api_process_terminate(pid):
    if pid <= 1 or pid == os.getpid():
        return jsonify({"ok": False, "error": "protected process"}), 400
    try:
        proc = psutil.Process(pid)
        owner = proc.username()
        if owner != current_os_user():
            return jsonify({"ok": False, "error": "only processes owned by the dashboard OS user can be terminated"}), 403
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except psutil.TimeoutExpired:
            return jsonify({"ok": True, "pid": pid, "message": "SIGTERM sent; process is still exiting"})
        return jsonify({"ok": True, "pid": pid, "message": "process terminated"})
    except psutil.NoSuchProcess:
        return jsonify({"ok": True, "pid": pid, "message": "process already exited"})
    except psutil.AccessDenied:
        return jsonify({"ok": False, "error": "permission denied"}), 403


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if check_auth(username, password):
            session.clear()
            session["logged_in"] = True
            session["username"] = username
            csrf_token()
            return redirect(url_for("index"))
        error = "Username atau password salah"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
