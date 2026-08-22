import os

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from app import fs_utils
from app.decorators import admin_required, with_server

bp = Blueprint("editor", __name__, url_prefix="/servers/<int:server_id>/edit")


# Просмотр/правка текстовых файлов внутри папки сервера — только admin
# (тот же уровень риска, что и файловый менеджер вообще). subpath — полный
# путь к файлу относительно server.path (тот же el_subpath, что строит
# server_files.html для ссылок на подпапки).
@bp.route("/<path:subpath>", methods=["GET", "POST"])
@admin_required
@with_server
def edit_file(server_id, subpath):
    server = current_app.server_registry.get(server_id)
    target = fs_utils.under(server.path, subpath)
    back_dir = os.path.dirname(subpath)
    back_url = url_for("files.server_files_to", server_id=server_id, subpath=back_dir)

    if request.method == "POST":
        content = request.form.get("content", "")
        try:
            fs_utils.write_text(server.path, target, content)
            flash("Сохранено")
        except (fs_utils.PathEscapeError, OSError, ValueError) as e:
            flash(f"Не удалось сохранить: {e}")
        return redirect(url_for("editor.edit_file", server_id=server_id, subpath=subpath))

    try:
        content = fs_utils.read_text(server.path, target)
    except FileNotFoundError:
        return render_template("error.html", error="Файл не найден"), 404
    except fs_utils.PathEscapeError:
        return render_template("error.html", error="Путь недопустим"), 400
    except ValueError as e:
        return render_template("error.html", error=str(e)), 400

    return render_template("file_editor.html", subpath=subpath, content=content, back_url=back_url)
