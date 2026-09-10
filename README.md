# Mini Server Dashboard
Web-based system monitoring dashboard for GPU servers used in deep learning & LLM training.

## Features

- **Live monitoring** - Updates every 2 seconds
- **CPU** - Usage, cores, frequency
- **Memory** - Usage (used/total), percentage
- **Disk** - Usage (used/total), percentage
- **GPU** - Load, memory usage, temperature (NVIDIA RTX)
- **Network I/O** - Real-time chart showing upload/download rates (MB/s)
- **Top Processes** - Top 10 processes by CPU/memory
- **Hostname & IP** - System hostname and all network interfaces

## Tech Stack

- Python/Flask backend
- psutil (system stats)
- GPUtil (GPU stats)
- Chart.js (network I/O visualization)
- Bootstrap-free vanilla CSS with dark theme

## Setup

```bash
pip install flask psutil gputil
python3 app.py
```

Dashboard accessible at http://localhost:5000 or http://<server-ip>:5000

## Screenshots

Dark-themed dashboard with:
- Gradient header
- Color-coded metrics (blue=CPU, teal=mem, amber=disk, purple=GPU, green/upload, pink/download)
- Smooth progress bars
- Real-time Chart.js line chart for network I/O