import os

from flask import Blueprint, current_app, flash, render_template, request, send_file
from werkzeug.utils import secure_filename

from app import fs_utils
from app.decorators import admin_required, with_server

bp = Blueprint("files", __name__, url_prefix="/servers/<int:server_id>/files")


# Файловый менеджер — целиком только для admin (не admin_write_required):
# даже просмотр содержимого папки сервера может раскрыть чувствительное
# (токены в конфигах плагинов и т.п.), это не то, что стоит давать viewer'у.
#
# Жёстко ограничен папкой сервера (server.path) — ни один путь/имя из
# запроса не должен позволять выйти за её пределы. subpath приходит через
# <path:...> (реальные "/", без старого "+"-хака) и всегда трактуется как
# путь ОТНОСИТЕЛЬНО server.path — поэтому его сначала джойнят с server.path
# в абсолютный путь через fs_utils.under(), и только потом это уходит в
# fs_utils.safe_join (которая для абсолютных путей просто резолвит и
# проверяет containment; для относительных — джойнила бы с корнем всего
# проекта, что тут не нужно).
def _list_dir(server, subpath):
    try:
        dir_list = fs_utils.get_dir(server.path, fs_utils.under(server.path, subpath))
    except (fs_utils.PathEscapeError, FileNotFoundError, NotADirectoryError):
        return None
    return fs_utils.sort_dir(dir_list)


@bp.route("/", defaults={"subpath": ""}, methods=["GET", "POST"])
@bp.route("/<path:subpath>", methods=["GET", "POST"])
@admin_required
@with_server
def server_files_to(server_id, subpath):
    server = current_app.server_registry.get(server_id)
    dir_list = _list_dir(server, subpath)
    if dir_list is None:
        return render_template("error.html", error="Папка не найдена или путь недопустим"), 400
    is_renaming = [None, False]

    if request.method == "POST":
        command = request.form.get("command")
        item = request.form.get("item")
        new_name = request.form.get("new_name")

        if command == "upload":
            uploaded, skipped = [], []
            for file_storage in request.files.getlist("upload_file"):
                filename = secure_filename(file_storage.filename or "")
                if not filename:
                    continue
                try:
                    target = fs_utils.safe_join(server.path, fs_utils.under(server.path, subpath, filename))
                except fs_utils.PathEscapeError:
                    skipped.append(filename)
                    continue
                file_storage.save(target)
                uploaded.append(filename)
            if uploaded:
                flash(f"Загружено: {', '.join(uploaded)}")
            if skipped:
                flash(f"Пропущено (недопустимый путь): {', '.join(skipped)}")
        elif command not in [None, "null", ""] and item:
            item_path = fs_utils.under(server.path, subpath, item)
            try:
                if command == "rename":
                    is_renaming = [item, True]
                    if new_name != "":
                        fs_utils.rename(server.path, item_path, new_name)
                if command == "delete":
                    fs_utils.delete(server.path, item_path)
                if command == "make":
                    is_file = "." in item
                    fs_utils.make(server.path, item_path, not is_file)
            except fs_utils.PathEscapeError:
                return render_template("error.html", error="Путь недопустим"), 400

        dir_list = _list_dir(server, subpath)
        if dir_list is None:
            return render_template("error.html", error="Папка не найдена или путь недопустим"), 400

    return render_template("server_files.html", dir_list=dir_list, subpath=subpath, is_renaming=is_renaming)


# Скачивание одного файла. Отдельный статический префикс ("download/...")
# впереди <path:subpath> — Werkzeug сортирует правила так, что более
# специфичное (со статическим сегментом) проверяется раньше жадного
# "/<path:subpath>" выше, так что коллизии с обзором папки не будет, пока
# внутри сервера не заведут папку/файл верхнего уровня буквально с именем
# "download".
@bp.route("/download/<path:subpath>", methods=["GET"])
@admin_required
@with_server
def download_file(server_id, subpath):
    server = current_app.server_registry.get(server_id)
    try:
        target = fs_utils.safe_join(server.path, fs_utils.under(server.path, subpath))
    except fs_utils.PathEscapeError:
        return render_template("error.html", error="Путь недопустим"), 400
    if not os.path.isfile(target):
        return render_template("error.html", error="Файл не найден"), 404
    return send_file(target, as_attachment=True, download_name=os.path.basename(target))
