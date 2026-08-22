import psutil
from flask import Blueprint, current_app, jsonify
from flask_login import login_required

from app.decorators import with_server

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.route("/stats")
@login_required
def api_stats():
    cpu = psutil.cpu_percent(interval=0.2)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    return jsonify({
        "cpu_percent": round(cpu, 1),
        "ram_used": f"{round(mem.used / (1024 ** 3), 1)} GB",
        "ram_total": f"{round(mem.total / (1024 ** 3), 1)} GB",
        "ram_percent": round(mem.percent, 1),
        "disk_used": f"{round(disk.used / (1024 ** 3), 1)} GB",
        "disk_total": f"{round(disk.total / (1024 ** 3), 1)} GB",
        "disk_percent": round(disk.percent, 1),
    })


@bp.route("/servers/<int:server_id>/status")
@login_required
@with_server
def api_status(server_id):
    server = current_app.server_registry.get(server_id)
    return jsonify({
        "running": server.is_server_running(),
        "status": server.status,  # offline / starting / running / restarting
        "online": len(server.online),
        "max": server.get_properties_value("max-players"),
    })
