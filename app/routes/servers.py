from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.decorators import admin_required, with_server
from app.extensions import db
from app.models import Server, create_server

bp = Blueprint("servers", __name__, url_prefix="/servers")


# Список серверов — общая точка входа после логина. Создание нового сервера
# доступно только admin; сам список видят все залогиненные (viewer тоже
# должен понимать, какие серверы вообще есть, чтобы зайти в консоль/игроков).
@bp.route("", methods=["GET", "POST"])
@login_required
def list_servers():
    if request.method == "POST":
        if not current_user.is_admin:
            abort(403)
        name = request.form.get("name", "").strip()
        if not name:
            flash("Укажи название сервера")
        else:
            java_xmx = request.form.get("java_xmx") or current_app.config["JAVA_XMX"]
            java_xms = request.form.get("java_xms") or current_app.config["JAVA_XMS"]
            server = create_server(name, java_xmx=java_xmx, java_xms=java_xms)
            return redirect(url_for("console.server_console", server_id=server.id))
    servers = Server.query.order_by(Server.created_at).all()
    # Статус (запущен/нет) — только для уже поднятых в реестре менеджеров, не
    # создаём ServerManager (и папку на диске) для каждого Server просто
    # ради отображения списка — см. ServerRegistry.peek.
    statuses = {s.id: (m.is_server_running() if (m := current_app.server_registry.peek(s.id)) else False)
                for s in servers}
    return render_template("servers_list.html", servers=servers, statuses=statuses,
                            default_xmx=current_app.config["JAVA_XMX"],
                            default_xms=current_app.config["JAVA_XMS"])


@bp.route("/<int:server_id>/delete", methods=["POST"])
@admin_required
@with_server
def delete_server(server_id):
    manager = current_app.server_registry.get(server_id)
    if manager.is_server_running():
        flash("Сначала останови сервер")
        return redirect(url_for("servers.list_servers"))
    row = Server.query.get_or_404(server_id)
    db.session.delete(row)
    db.session.commit()
    current_app.server_registry.forget(server_id)
    flash(f"Сервер «{row.name}» удалён из панели (файлы на диске не тронуты)")
    return redirect(url_for("servers.list_servers"))
