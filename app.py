import os
import json
import time
import socket
import subprocess
import re
import psutil
import GPUtil
from functools import wraps
import pam
from flask import Flask, render_template, jsonify, request, session, redirect, url_for

app = Flask(__name__)
app.secret_key = os.urandom(24)

def check_auth(username, password):
    """Verify Linux user credentials using PAM."""
    try:
        p = pam.pam()
        return p.authenticate(username, password)
    except Exception:
        return False

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def parse_nvidia_smi():
    result = []
    try:
        cmd = [
            'nvidia-smi',
            '--query-gpu=name,temperature.gpu,utilization.gpu,utilization.memory,'
            'clocks.current.sm,clocks.current.memory,clocks.current.video,'
            'clocks.current.graphics,power.draw,power.limit,'
            'memory.total,memory.used,memory.free',
            '--format=csv,noheader,nounits'
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=5).decode('utf-8').strip()
        if not out:
            return result
        for line in out.split('\n'):
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(',')]
            if len(parts) < 13:
                continue
            try:
                gpu = {
                    'name': parts[0],
                    'temperature': float(parts[1]) if parts[1] != 'N/A' else None,
                    'gpu_util': float(parts[2]) if parts[2] != 'N/A' else None,
                    'mem_util': float(parts[3]) if parts[3] != 'N/A' else None,
                    'sm_clock': float(parts[4]) if parts[4] != 'N/A' else None,
                    'mem_clock': float(parts[5]) if parts[5] != 'N/A' else None,
                    'video_clock': float(parts[6]) if parts[6] != 'N/A' else None,
                    'graphics_clock': float(parts[7]) if parts[7] != 'N/A' else None,
                    'power_draw': float(parts[8]) if parts[8] != 'N/A' else None,
                    'power_limit': float(parts[9]) if parts[9] != 'N/A' else None,
                    'memory_total': float(parts[10]) if parts[10] != 'N/A' else None,
                    'memory_used': float(parts[11]) if parts[11] != 'N/A' else None,
                    'memory_free': float(parts[12]) if parts[12] != 'N/A' else None,
                    'source': 'nvidia-smi'
                }
                result.append(gpu)
            except (ValueError, IndexError):
                continue
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError):
        pass
    return result

def get_gputil_gpus():
    gpus = []
    try:
        gpu_list = GPUtil.getGPUs()
        for gpu in gpu_list:
            gpus.append({
                'id': gpu.id,
                'name': gpu.name,
                'load': gpu.load * 100,
                'memoryTotal': gpu.memoryTotal,
                'memoryUsed': gpu.memoryUsed,
                'memoryFree': gpu.memoryFree,
                'temperature': gpu.temperature,
                'source': 'gputil'
            })
    except Exception:
        pass
    return gpus

def merge_gpu_data(smi_gpus, gputil_gpus):
    merged = []
    smi_by_name = {g['name']: g for g in smi_gpus}
    for gputil_gpu in gputil_gpus:
        name = gputil_gpu['name']
        smi = smi_by_name.get(name)
        if smi:
            entry = {
                'id': gputil_gpu['id'],
                'name': name,
                'load': smi.get('gpu_util'),
                'mem_util': smi.get('mem_util'),
                'temperature': smi.get('temperature'),
                'sm_clock': smi.get('sm_clock'),
                'mem_clock': smi.get('mem_clock'),
                'graphics_clock': smi.get('graphics_clock'),
                'video_clock': smi.get('video_clock'),
                'power_draw': smi.get('power_draw'),
                'power_limit': smi.get('power_limit'),
                'memoryTotal': smi.get('memory_total'),
                'memoryUsed': smi.get('memory_used'),
                'memoryFree': smi.get('memory_free'),
                'source': 'nvidia-smi+gputil'
            }
        else:
            entry = {
                'id': gputil_gpu['id'],
                'name': name,
                'load': gputil_gpu['load'],
                'mem_util': None,
                'temperature': gputil_gpu['temperature'],
                'sm_clock': None,
                'mem_clock': None,
                'graphics_clock': None,
                'video_clock': None,
                'power_draw': None,
                'power_limit': None,
                'memoryTotal': gputil_gpu['memoryTotal'],
                'memoryUsed': gputil_gpu['memoryUsed'],
                'memoryFree': gputil_gpu['memoryFree'],
                'source': 'gputil-only'
            }
        merged.append(entry)
    if not merged and smi_gpus:
        for i, smi in enumerate(smi_gpus):
            merged.append({
                'id': i,
                'name': smi['name'],
                'load': smi.get('gpu_util'),
                'mem_util': smi.get('mem_util'),
                'temperature': smi.get('temperature'),
                'sm_clock': smi.get('sm_clock'),
                'mem_clock': smi.get('mem_clock'),
                'graphics_clock': smi.get('graphics_clock'),
                'video_clock': smi.get('video_clock'),
                'power_draw': smi.get('power_draw'),
                'power_limit': smi.get('power_limit'),
                'memoryTotal': smi.get('memory_total'),
                'memoryUsed': smi.get('memory_used'),
                'memoryFree': smi.get('memory_free'),
                'source': 'nvidia-smi-only'
            })
    return merged

def get_disk_detail():
    """Get disk info similar to df -h output."""
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            # device: use the device path (e.g., /dev/nvme0n1p2)
            device = part.device
            # filesystem: take the last component of device path, or device itself
            filesystem = os.path.basename(device) if device else device
            disks.append({
                'filesystem': filesystem,   # /dev/nvme0n1p2 -> nvme0n1p2, but keep full for clarity
                'device': device,
                'mountpoint': part.mountpoint,
                'fstype': part.fstype,
                'opts': part.opts,
                'total': usage.total,
                'used': usage.used,
                'available': usage.free,
                'percent': usage.percent
            })
        except PermissionError:
            continue
        except Exception:
            continue
    return disks

def get_system_stats():
    hostname = socket.gethostname()
    ips = []
    try:
        for interface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    ips.append({'interface': interface, 'ip': addr.address})
    except Exception:
        ips = [{'interface': 'unknown', 'ip': 'N/A'}]

    cpu_percent_total = psutil.cpu_percent(interval=0.1)
    cpu_percent_per_cpu = psutil.cpu_percent(interval=0.1, percpu=True)
    cpu_count = psutil.cpu_count()
    cpu_freq = psutil.cpu_freq()

    mem = psutil.virtual_memory()

    # Disk: full detail like df -h
    disks = get_disk_detail()
    default_disk = None
    for d in disks:
        if d['mountpoint'] == '/':
            default_disk = d
            break
    if not default_disk and disks:
        default_disk = disks[0]

    net_io = psutil.net_io_counters()
    net_per_interface = {}
    for ifname, addrs in psutil.net_if_addrs().items():
        try:
            io = psutil.net_io_counters(pernic=True).get(ifname)
            if io:
                net_per_interface[ifname] = {
                    'bytes_sent': io.bytes_sent,
                    'bytes_recv': io.bytes_recv,
                    'packets_sent': io.packets_sent,
                    'packets_recv': io.packets_recv
                }
        except Exception:
            pass

    smi_gpus = parse_nvidia_smi()
    gputil_gpus = get_gputil_gpus()
    gpus = merge_gpu_data(smi_gpus, gputil_gpus)

    EXCLUDE_PROCS = {'ollama', 'hermes', 'tailscaled', 'cloudflared'}
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent']):
        try:
            pinfo = proc.info
            if pinfo['name'] and pinfo['name'].lower() in EXCLUDE_PROCS:
                continue
            if (pinfo['cpu_percent'] and pinfo['cpu_percent'] > 0.0) or (pinfo['memory_percent'] and pinfo['memory_percent'] > 0.0):
                processes.append(pinfo)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    processes.sort(key=lambda x: x['cpu_percent'] if x['cpu_percent'] is not None else 0, reverse=True)
    top_processes = processes[:10]

    return {
        'hostname': hostname,
        'ips': ips,
        'net_io': {
            'bytes_sent': net_io.bytes_sent,
            'bytes_recv': net_io.bytes_recv,
            'packets_sent': net_io.packets_sent,
            'packets_recv': net_io.packets_recv
        },
        'net_per_interface': net_per_interface,
        'cpu': {
            'percent': cpu_percent_total,
            'per_cpu': cpu_percent_per_cpu,
            'count': cpu_count,
            'frequency': cpu_freq.current if cpu_freq else None
        },
        'memory': {
            'total': mem.total,
            'available': mem.available,
            'percent': mem.percent,
            'used': mem.used,
            'free': mem.free
        },
        'disks': disks,
        'disk_default': default_disk,
        'gpus': gpus,
        'processes': top_processes,
        'timestamp': time.time()
    }

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/data')
@login_required
def data():
    return jsonify(get_system_stats())

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        if check_auth(username, password):
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('index'))
        else:
            error = 'Username atau password salah'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)