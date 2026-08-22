from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.decorators import with_server

bp = Blueprint("misc", __name__)


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("servers.list_servers"))
    return render_template("index.html")


@bp.route("/about")
def about():
    return render_template("about.html")


# Заглушки — см. REVIEW.md, раздел 🟢 «Можно добавить»
@bp.route("/servers/<int:server_id>/sqltables")
@login_required
@with_server
def server_sql_tables(server_id):
    return render_template("server_sql.html")


@bp.route("/servers/<int:server_id>/map")
@login_required
@with_server
def server_map(server_id):
    return render_template("server_map.html")
