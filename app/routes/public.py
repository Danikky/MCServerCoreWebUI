import datetime as dt

from flask import Blueprint, current_app, render_template

from app.models import Server

bp = Blueprint("public", __name__)


def _days_word(n: int) -> str:
    """Русское склонение "день/дня/дней" по числу n."""
    if 11 <= n % 100 <= 14:
        return "дней"
    last = n % 10
    if last == 1:
        return "день"
    if 2 <= last <= 4:
        return "дня"
    return "дней"


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
        online_mode = manager.get_properties_bool("online-mode")

        days_running = None
        if row.first_started_at is not None:
            days_running = (dt.datetime.utcnow() - row.first_started_at).days

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
            # None, если ещё нет server.properties (сервер ни разу не стартовал) —
            # тогда просто не показываем бейдж, а не гадаем.
            "cracked": (not online_mode) if online_mode is not None else None,
            # Тоже None, пока сервер ни разу не поднимался — first_started_at
            # пишется в ServerManager._record_first_start() при первом "Done (".
            "days_running": days_running,
            "days_word": _days_word(days_running) if days_running is not None else None,
        })
    return render_template("public_status.html", servers=servers)
