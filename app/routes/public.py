from flask import Blueprint, current_app, render_template

from app.models import Server

bp = Blueprint("public", __name__)


# Публичная страница статуса — без логина, для игроков. Показывает только
# серверы с public_visible=True и только то, что admin явно вписал на
# странице "Ядро" (public_name/public_version/public_ip/public_description/
# public_contact) — никогда внутренние name/slug/пути. Статус, число онлайн
# и сам список ников — единственное, что берётся из реального состояния
# процесса (ServerManager.status/online).
@bp.route("/status")
def status_page():
    rows = Server.query.filter_by(public_visible=True).order_by(Server.created_at).all()
    servers = []
    for row in rows:
        manager = current_app.server_registry.get(row.id)
        with manager.online_lock:
            online_players = list(manager.online)
        servers.append({
            "name": row.public_name or row.name,
            "version": row.public_version,
            "ip": row.public_ip,
            "description": row.public_description,
            "contact": row.public_contact,
            "status": manager.status,
            "online": len(online_players),
            "online_players": online_players,
            "max_players": manager.get_properties_value("max-players"),
        })
    return render_template("public_status.html", servers=servers)
