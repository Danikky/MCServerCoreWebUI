from io import BytesIO

from flask import Blueprint, abort, flash, jsonify, redirect, request, send_file, send_from_directory, url_for

from app.client_pack import ClientPack, ClientPackError
from app.decorators import admin_required, with_server
from app.models import Server

# Клиентская сборка для автоустановщика под TLauncher (app/client_pack.py).
# Два блюпринта: admin_bp — загрузка файлов сборки, форма живёт на странице
# «Ядро»; public_bp — то, что качает установщик у игрока, БЕЗ логина.
admin_bp = Blueprint("clientpack", __name__, url_prefix="/servers/<int:server_id>/clientpack")
public_bp = Blueprint("pack", __name__, url_prefix="/pack/<int:server_id>")


def _pack(server_id: int) -> ClientPack:
    return ClientPack(Server.query.get_or_404(server_id).slug)


def _back(server_id):
    return redirect(url_for("core.core_page", server_id=server_id) + "#clientpack")


# ---- admin: загрузки идут XHR'ом по одному файлу на запрос (сотни модов,
# прогресс-бар, и каждый запрос укладывается в MAX_CONTENT_LENGTH) — поэтому
# отвечают JSON'ом, а не redirect+flash, как обычные формы.

def _upload(server_id, save):
    file_storage = request.files.get("file")
    if not file_storage or not file_storage.filename:
        return jsonify(ok=False, error="Файл не выбран"), 400
    try:
        save(_pack(server_id), file_storage)
    except ClientPackError as e:
        return jsonify(ok=False, error=str(e)), 400
    return jsonify(ok=True)


@admin_bp.route("/installer", methods=["POST"])
@admin_required
@with_server
def upload_installer(server_id):
    return _upload(server_id, lambda pack, f: pack.save_installer(f))


@admin_bp.route("/mods", methods=["POST"])
@admin_required
@with_server
def upload_mod(server_id):
    return _upload(server_id, lambda pack, f: pack.save_mod(f))


@admin_bp.route("/overrides", methods=["POST"])
@admin_required
@with_server
def upload_overrides(server_id):
    return _upload(server_id, lambda pack, f: pack.save_overrides(f))


@admin_bp.route("/name", methods=["POST"])
@admin_required
@with_server
def set_name(server_id):
    try:
        name = _pack(server_id).set_name(request.form.get("name", ""))
        flash(f"Название сборки: {name}")
    except ClientPackError as e:
        flash(f"Ошибка: {e}")
    return _back(server_id)


@admin_bp.route("/status-button", methods=["POST"])
@admin_required
@with_server
def set_status_button(server_id):
    show = request.form.get("show_on_status") == "on"
    _pack(server_id).set_show_on_status(show)
    flash("Кнопка установщика на странице статуса " + ("включена" if show else "выключена"))
    return _back(server_id)


@admin_bp.route("/installer/delete", methods=["POST"])
@admin_required
@with_server
def delete_installer(server_id):
    _pack(server_id).delete_installer()
    flash("Установщик загрузчика удалён")
    return _back(server_id)


@admin_bp.route("/overrides/delete", methods=["POST"])
@admin_required
@with_server
def delete_overrides(server_id):
    _pack(server_id).delete_overrides()
    flash("overrides удалены")
    return _back(server_id)


@admin_bp.route("/mods/clear", methods=["POST"])
@admin_required
@with_server
def clear_mods(server_id):
    _pack(server_id).clear_mods()
    flash("Все моды сборки удалены")
    return _back(server_id)


@admin_bp.route("/mods/<string:filename>/delete", methods=["POST"])
@admin_required
@with_server
def delete_mod(server_id, filename):
    _pack(server_id).delete_mod(filename)
    flash(f"Удалено: {filename}")
    return _back(server_id)


# ---- public: без логина — это качает .bat на компьютере игрока. Отдаётся
# только готовая сборка (есть имя и загрузчик); ни public_visible, ни
# переключатель кнопки на /status тут не проверяются намеренно — сборку
# приватного сервера раздают друзьям прямой ссылкой.

def _ready_pack(server_id: int) -> ClientPack:
    pack = _pack(server_id)
    if not pack.ready:
        abort(404)
    return pack


def _external(endpoint: str, **values) -> str:
    """Абсолютный URL для игрока. За nginx (см. DEPLOY.md) Flask видит http —
    настоящую схему берём из X-Forwarded-Proto. Заголовок можно подделать,
    но он влияет только на ссылки в ответе самому же запросившему."""
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme).split(",")[0].strip()
    if scheme not in ("http", "https"):
        scheme = request.scheme
    return f"{scheme}://{request.host}{url_for(endpoint, **values)}"


@public_bp.route("/install.bat")
def installer_bat(server_id):
    pack = _ready_pack(server_id)
    # Адрес сборки без хвоста — скрипт сам дописывает /manifest.json.
    pack_url = _external("pack.manifest", server_id=server_id).rsplit("/", 1)[0]
    return send_file(
        BytesIO(pack.render_installer_bat(pack_url)),
        mimetype="application/x-bat",
        as_attachment=True,
        download_name=f"{pack.meta['name']} - установщик.bat",
    )


@public_bp.route("/manifest.json")
def manifest(server_id):
    pack = _ready_pack(server_id)
    meta = pack.meta
    overrides = None
    if meta["overrides"]:
        overrides = dict(meta["overrides"], url=_external("pack.overrides", server_id=server_id))
    return jsonify(
        format=1,
        name=meta["name"],
        loader=meta["loader"],
        version_json=pack.version_json_text(),
        installer=dict(meta["installer"], url=_external("pack.installer", server_id=server_id)),
        mods=[
            dict(info, name=name, url=_external("pack.mod", server_id=server_id, filename=name))
            for name, info in sorted(meta["mods"].items())
        ],
        overrides=overrides,
    )


@public_bp.route("/installer.jar")
def installer(server_id):
    pack = _ready_pack(server_id)
    return send_file(pack.installer_path, mimetype="application/java-archive")


@public_bp.route("/overrides.zip")
def overrides(server_id):
    pack = _ready_pack(server_id)
    if not pack.meta["overrides"]:
        abort(404)
    return send_file(pack.overrides_path, mimetype="application/zip")


@public_bp.route("/mods/<string:filename>")
def mod(server_id, filename):
    # send_from_directory сам не выпускает за пределы mods_dir.
    return send_from_directory(_ready_pack(server_id).mods_dir, filename)
