from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from app.decorators import admin_required, with_server
from app.extensions import db
from app.models import Server

bp = Blueprint("core", __name__, url_prefix="/servers/<int:server_id>/core")


# Ядро сервера (.jar) — вся страница только для admin, как и файловый
# менеджер: тут можно подложить что угодно, что потом исполнится как java
# процесс. Два способа завести ядро: обычная загрузка файла и скачивание по
# прямой ссылке на сборку (Paper/Purpur/Fabric/...). Плюс здесь же — публичная
# информация для страницы /status (название/версия/IP игроки видят ровно то,
# что тут вписано, никакого автоопределения).
@bp.route("", methods=["GET"])
@admin_required
@with_server
def core_page(server_id):
    server = current_app.server_registry.get(server_id)
    row = Server.query.get_or_404(server_id)
    return render_template("server_core.html", core_files=server.list_core_files(), row=row)


@bp.route("/upload", methods=["POST"])
@admin_required
@with_server
def upload(server_id):
    server = current_app.server_registry.get(server_id)
    file_storage = request.files.get("corefile")
    if not file_storage or not file_storage.filename:
        flash("Файл не выбран")
        return redirect(url_for("core.core_page", server_id=server_id))
    try:
        filename = server.save_uploaded_core(file_storage)
        flash(f"Загружено: {filename}")
    except ValueError as e:
        flash(f"Ошибка: {e}")
    return redirect(url_for("core.core_page", server_id=server_id))


@bp.route("/fetch", methods=["POST"])
@admin_required
@with_server
def fetch(server_id):
    server = current_app.server_registry.get(server_id)
    url = request.form.get("url", "").strip()
    filename = request.form.get("filename", "").strip() or None
    if not url:
        flash("Укажи ссылку на .jar")
        return redirect(url_for("core.core_page", server_id=server_id))
    try:
        name = server.fetch_core_from_url(url, filename=filename)
        flash(f"Скачано: {name}")
    except Exception as e:
        flash(f"Не удалось скачать: {e}")
    return redirect(url_for("core.core_page", server_id=server_id))


@bp.route("/<string:filename>/delete", methods=["POST"])
@admin_required
@with_server
def delete(server_id, filename):
    server = current_app.server_registry.get(server_id)
    server.delete_core_file(filename)
    flash(f"Удалено: {filename}")
    return redirect(url_for("core.core_page", server_id=server_id))


@bp.route("/public", methods=["POST"])
@admin_required
@with_server
def update_public(server_id):
    row = Server.query.get_or_404(server_id)
    row.public_visible = request.form.get("public_visible") == "on"
    row.public_name = request.form.get("public_name", "").strip() or None
    row.public_version = request.form.get("public_version", "").strip() or None
    row.public_ip = request.form.get("public_ip", "").strip() or None
    row.public_description = request.form.get("public_description", "").strip() or None
    row.public_contact = request.form.get("public_contact", "").strip() or None
    db.session.commit()
    flash("Публичная информация обновлена")
    return redirect(url_for("core.core_page", server_id=server_id))
