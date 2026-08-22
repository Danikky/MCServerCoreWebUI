from flask import Blueprint, current_app, render_template, request

from app.decorators import admin_required, with_server

bp = Blueprint("backups", __name__, url_prefix="/servers/<int:server_id>")


@bp.route("/backups", methods=["GET", "POST"])
@admin_required
@with_server
def backups_page(server_id):
    server = current_app.server_registry.get(server_id)
    is_renaming = [None, False]
    if request.method == "POST":
        command = request.form.get("command")
        name = request.form.get("name")
        if command == "create":
            server.create_backup(name)
        if command == "delete":
            server.delete_backup(name)
        if command == "rename":
            is_renaming = [name, True]
            new_name = request.form.get("new_name")
            server.rename_backup(name, new_name)
    backups_list = server.get_backups_list()
    return render_template("backups_page.html", backups_list=backups_list, is_renaming=is_renaming)
