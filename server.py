"""Extended entrypoint for Mini Server Dashboard resource details.

Keeps the core application in app.py stable while adding swap telemetry and
loading focused UI enhancements for memory/storage details.
"""
import psutil
from flask import render_template

import app as core


_original_get_system_stats = core.get_system_stats


def get_system_stats_with_swap():
    stats = _original_get_system_stats()
    swap = psutil.swap_memory()
    stats.setdefault("memory", {})["swap"] = {
        "total": swap.total,
        "used": swap.used,
        "free": swap.free,
        "percent": swap.percent,
        "sin": swap.sin,
        "sout": swap.sout,
    }
    return stats


@core.login_required
def enhanced_index():
    html = render_template("index.html", csrf_token=core.csrf_token())
    html = html.replace(
        "</head>",
        '<link rel="stylesheet" href="/static/resource-details.css">\n</head>',
    )
    html = html.replace(
        "</body>",
        '<script src="/static/resource-details.js"></script>\n</body>',
    )
    return html


# The /data endpoint resolves get_system_stats from the app module at request
# time, so replacing this symbol extends the existing endpoint without cloning
# its authentication/session logic.
core.get_system_stats = get_system_stats_with_swap
core.app.view_functions["index"] = enhanced_index

app = core.app


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
