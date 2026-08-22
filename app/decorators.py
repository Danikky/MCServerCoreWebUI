"""
Ролевой доступ поверх flask_login.login_required. Роли: admin (полный
доступ) / viewer (только просмотр — без консольных команд, файлов, бекапов,
правки настроек и действий над игроками). Плюс with_server — резолвит
server_id из URL в конкретный ServerManager (см. app/server_registry.py).
"""
from functools import wraps

from flask import abort, current_app, g, request
from flask_login import current_user, login_required


def with_server(view):
    """
    Резолвит <int:server_id> из URL через app.server_registry в ServerManager
    и кладёт его в g.server — дальше в view бери `g.server`, а не лезь в
    реестр напрямую. 404, если такого сервера нет в БД.
    """
    @wraps(view)
    def wrapped(*args, server_id, **kwargs):
        manager = current_app.server_registry.get(server_id)
        if manager is None:
            abort(404)
        g.server = manager
        return view(*args, server_id=server_id, **kwargs)
    return wrapped


def admin_required(view):
    """Весь маршрут (GET и любые другие методы) — только для admin."""
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def admin_write_required(view):
    """
    GET — доступен любому залогиненному пользователю (viewer видит статус/
    консоль/список игроков), но любой не-GET запрос (изменение чего-либо)
    — только для admin.
    """
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if request.method != "GET" and not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapped
