import re

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from app.decorators import admin_write_required, with_server
from app.models import PlayerEvent

bp = Blueprint("players", __name__, url_prefix="/servers/<int:server_id>")

# Последние N событий входа/выхода — история переживает рестарт/офлайн
# сервера (см. ServerManager._log_player_event), в отличие от online-списка.
# Без пагинации — этого достаточно, чтобы увидеть "кто заходил недавно",
# а не растить ещё один бесконечно листаемый лог рядом с консольным.
PLAYER_HISTORY_LIMIT = 50


def _get_player_history(server_id):
    return (
        PlayerEvent.query.filter_by(server_id=server_id)
        .order_by(PlayerEvent.id.desc())
        .limit(PLAYER_HISTORY_LIMIT)
        .all()
    )

# Ровно те значения, что реально шлют кнопки в server_players.html. Раньше
# command/username из формы уходили в консоль вообще без проверки — POST
# сюда с произвольным command де-факто был бы способом выполнить любую
# консольную команду в обход страницы "Консоль". Не то чтобы это давало
# лишние права (маршрут и так только для admin, у которого и так есть
# консоль), но ограничение вида "эта форма может сделать ровно вот это"
# — независимая гарантия того, что действие применяется к тому, к чему
# должно, а не к тому, что случайно/специально просочилось в поле формы.
ALLOWED_COMMANDS = {"op", "deop", "kick", "ban", "pardon", "whitelist remove"}

# Ник Minecraft: буквы/цифры/подчёркивание, до 16 символов. Главное, что
# заведомо исключено — пробелы и переносы строк: username подставляется в
# "<command> <username>" и уходит одной строкой в stdin процесса; перенос
# строки внутри username превратился бы в отдельную вторую команду консоли
# (стдин читается построчно). Настоящие ники Mojang под это ограничение и
# так подпадают — проверка отсекает только заведомо не-ники.
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")

COMMAND_LABELS = {
    "op": "Оператор выдан",
    "deop": "Оператор снят",
    "kick": "Игрок кикнут",
    "ban": "Игрок забанен",
    "pardon": "Бан снят",
    "whitelist remove": "Убран из вайтлиста",
}


# Кто играет realtime, кто заходил, права, баны, вайтлист. GET — viewer,
# действия над игроками (op/kick/ban/...) — только admin.
@bp.route("/players", methods=["POST", "GET"])
@admin_write_required
@with_server
def server_players(server_id):
    server = current_app.server_registry.get(server_id)
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        command = request.form.get("command")
        if command not in ALLOWED_COMMANDS:
            flash("Неизвестное действие")
        elif not USERNAME_RE.match(username):
            flash(f"Некорректное имя игрока: «{username}»")
        else:
            confirmed, message = server.run_player_command(command, username)
            label = COMMAND_LABELS.get(command, command)
            flash(f"{label} ({username}): {message}" if not confirmed else f"{label}: {username}")
        # Redirect, а не прямой рендер — иначе обновление страницы (F5)
        # после действия переспрашивает браузер "отправить форму ещё раз?"
        # и рискует продублировать команду.
        return redirect(url_for("players.server_players", server_id=server_id))

    player_history = _get_player_history(server_id)

    if server.is_server_running():
        online = [len(server.online), server.get_properties_value("max-players")]
        players_data = server.update_players_data()
        return render_template("server_players.html", players_data=players_data, online=online, player_history=player_history)

    online = [0, server.get_properties_value("max-players")]
    if server.core:
        players_data = server.update_players_data()
        return render_template("server_players.html", players_data=players_data, online=online, player_history=player_history)
    return render_template("error.html", error="Сервер ещё ни разу не запускался"), 404
