from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import login_required

from app.decorators import admin_write_required, with_server
from app.models import ConsoleLine

bp = Blueprint("console", __name__, url_prefix="/servers/<int:server_id>")


# Консоль (GET — доступна viewer'ам на просмотр, POST — только admin, см.
# admin_write_required)
@bp.route("/console", methods=["POST", "GET"])
@admin_write_required
@with_server
def server_console(server_id):
    server = current_app.server_registry.get(server_id)
    # Ресурсы (CPU/RAM/диск) на этой странице подгружаются отдельно через
    # /api/servers/<id>/stats поллингом из JS — см. control_panel.html.
    if request.method == "POST":
        console_input = request.form.get("console_input")
        command = request.form.get("command")
        if console_input not in [None, "null", ""]:
            server.send_command_direct(console_input)
        if command not in [None, "null", ""]:
            if command == "start":
                if not server.is_server_running():
                    server.start_server()
            elif command == "stop":
                if server.is_server_running():
                    server.send_command_direct("stop")
            elif command == "kill":
                try:
                    server.kill_server()
                except Exception as e:
                    print(f"Ошибка при убийстве сервера: {e}")
                    server._log(f"Ошибка при убийстве сервера: {e}")
            elif command == "restart":
                server.restart_server()
            else:
                server.send_command_direct(command)

    is_server_run = server.is_server_running()
    if is_server_run:
        online = [len(server.online), server.get_properties_value("max-players")]
    else:
        online = [0, server.get_properties_value("max-players")]
    return render_template("control_panel.html", is_server_run=is_server_run, status=server.status, online=online)


@bp.route("/console/history")
@login_required
@with_server
def get_console_history(server_id):
    """Пагинированная история — раньше отдавала всю таблицу разом (растёт
    без ограничения за время жизни сервера, см. REVIEW.md), теперь только
    страницу вокруг before_id. Без before_id — последние limit строк
    (обычный первый заход на страницу); с ним — limit строк старше него
    (подгрузка при прокрутке вверх, см. control_panel.html). Всегда отдаём
    в хронологическом порядке (старые → новые), чтобы фронт мог просто
    рендерить/приклеивать без пересортировки."""
    limit = min(request.args.get("limit", 80, type=int) or 80, 500)
    before_id = request.args.get("before_id", type=int)

    query = ConsoleLine.query.filter_by(server_id=server_id)
    if before_id is not None:
        query = query.filter(ConsoleLine.id < before_id)
    # limit+1 — узнать, есть ли ещё более старые строки, без отдельного COUNT(*)
    rows = query.order_by(ConsoleLine.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    rows.reverse()

    return jsonify({
        'lines': [{'id': r.id, 'line': r.line} for r in rows],
        'has_more': has_more,
    })
