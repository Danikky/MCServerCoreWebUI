from flask import Blueprint, current_app, render_template, request

from app.decorators import admin_write_required, with_server

bp = Blueprint("settings", __name__, url_prefix="/servers/<int:server_id>")


# server.properties. GET — viewer видит настройки, сохранение — только admin.
@bp.route("/settings", methods=['GET', 'POST'])
@admin_write_required
@with_server
def server_settings(server_id):
    server = current_app.server_registry.get(server_id)
    properties_data = server.get_properties_data()
    if not properties_data:
        return render_template("error.html", error="Файл с настройками сервера не обнаружен (ядро ещё не запускалось?)")

    if request.method == "POST":
        for key, _ in properties_data:
            new_value = request.form.get(key)
            if new_value not in [None, "null", ""]:
                server.update_properties(key, new_value)
        properties_data = server.get_properties_data()

    return render_template("server_settings.html", properties_data=properties_data)
