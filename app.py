import os
import json
import time
import socket
import psutil
import GPUtil
from flask import Flask, render_template, jsonify

app = Flask(__name__)

def get_system_stats():
    # Hostname & IP
    hostname = socket.gethostname()
    ips = []
    try:
        for interface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    ips.append({'interface': interface, 'ip': addr.address})
    except Exception:
        ips = [{'interface': 'unknown', 'ip': 'N/A'}]

    # CPU — per-core sudah di-request di sini supaya akurat per iterasi
    cpu_percent_total = psutil.cpu_percent(interval=0.1)
    cpu_percent_per_cpu = psutil.cpu_percent(interval=0.1, percpu=True)
    cpu_count = psutil.cpu_count()
    cpu_freq = psutil.cpu_freq()

    # Memory
    mem = psutil.virtual_memory()

    # Disk
    disk = psutil.disk_usage('/')

    # Network I/O (bytes)
    net_io = psutil.net_io_counters()

    # Network I/O per interface
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

    # GPU
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
                'temperature': gpu.temperature
            })
    except Exception as e:
        gpus = [{'error': str(e)}]

    # Top processes
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent']):
        try:
            pinfo = proc.info
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
        'disk': {
            'total': disk.total,
            'used': disk.used,
            'free': disk.free,
            'percent': disk.used / disk.total * 100
        },
        'gpus': gpus,
        'processes': top_processes,
        'timestamp': time.time()
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/data')
def data():
    return jsonify(get_system_stats())

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)