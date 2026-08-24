from flask import Blueprint, jsonify

from app.extensions import db
from app.models import Server

bp = Blueprint("launcher", __name__, url_prefix="/launcher")


# Машиночитаемый аналог public.py — без логина, тот же уровень доверия, что
# и /status: версия/IP/список модов не секрет, игроку они и так нужны, чтобы
# подключиться. Отдаём только серверы с public_visible=True (тот же
# переключатель, что и у публичной страницы статуса) И заполненным
# mc_version — сервер без явно вписанной версии в лаунчере не появляется,
# даже если он публично виден на /status.
def _launcher_ready_servers():
    return Server.query.filter(
        Server.public_visible.is_(True),
        Server.mc_version.isnot(None),
        Server.mc_version != "",
    ).all()


@bp.route("/servers")
def list_servers():
    rows = _launcher_ready_servers()
    return jsonify([
        {"id": s.id, "name": s.public_name or s.name, "ip": s.public_ip}
        for s in rows
    ])


@bp.route("/servers/<int:server_id>/manifest")
def manifest(server_id):
    row = db.session.get(Server, server_id)
    if row is None or not row.public_visible or not row.mc_version:
        return jsonify({"error": "Сервер не найден или не готов для лаунчера"}), 404
    return jsonify({
        "name": row.public_name or row.name,
        "ip": row.public_ip,
        "mc_version": row.mc_version,
        "modloader": row.modloader,
        "modloader_version": row.modloader_version,
        # Пусто в этой версии — поле присутствует с первого дня, чтобы
        # синхронизация модов (следующий этап) не ломала контракт манифеста.
        "mods": [],
    })
