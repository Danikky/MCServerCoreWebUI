from flask import Blueprint, current_app, render_template, request

from app.decorators import admin_write_required, with_server

bp = Blueprint("settings", __name__, url_prefix="/servers/<int:server_id>")

# Ключи server.properties с фиксированным набором значений — на странице
# вместо текстового поля выпадающий список. Булевы ключи сюда не входят:
# они определяются по самому значению (true/false), так что работают и для
# ключей новых версий/форков, которых тут нет.
_ENUM_OPTIONS = {
    "difficulty": ["peaceful", "easy", "normal", "hard"],
    "gamemode": ["survival", "creative", "adventure", "spectator"],
    "level-type": ["minecraft:normal", "minecraft:flat", "minecraft:large_biomes",
                   "minecraft:amplified", "minecraft:single_biome_surface"],
    "region-file-compression": ["deflate", "lz4", "none"],
    "op-permission-level": ["1", "2", "3", "4"],
    "function-permission-level": ["1", "2", "3", "4"],
}
# Старые версии пишут то же самое иначе: difficulty/gamemode числом (до 1.13),
# level-type без "minecraft:" (до 1.19). Предлагаем варианты в том же формате,
# что уже в файле, — иначе старое ядро не поймёт новое значение.
_LEGACY_OPTIONS = {
    "difficulty": [("0", "0 — peaceful"), ("1", "1 — easy"), ("2", "2 — normal"), ("3", "3 — hard")],
    "gamemode": [("0", "0 — survival"), ("1", "1 — creative"), ("2", "2 — adventure"), ("3", "3 — spectator")],
    "level-type": [(v, v) for v in ("default", "flat", "largeBiomes", "amplified", "buffet")],
}


def _is_legacy(key: str, value: str) -> bool:
    if key == "level-type":
        return ":" not in value
    return value.isdigit()


def _select_options(key: str, raw: str):
    """Варианты для <select> — список (value, label, selected) или None, если
    ключ свободного ввода. Текущее значение всегда среди вариантов: если его
    нет в списке, оно добавляется первым, чтобы сохранение страницы молча
    не поменяло то, что admin не трогал."""
    # В .properties двоеточие экранируется ("minecraft\:normal") — сравниваем
    # без экранирования, но выбранный вариант отправляем как есть, чтобы
    # файл не менялся без нужды.
    value = raw.replace("\\:", ":")
    if value in ("true", "false"):
        choices = [("true", "true"), ("false", "false")]
    elif key in _LEGACY_OPTIONS and _is_legacy(key, value):
        choices = _LEGACY_OPTIONS[key]
    elif key in _ENUM_OPTIONS:
        choices = [(v, v) for v in _ENUM_OPTIONS[key]]
    else:
        return None
    if value not in (v for v, _ in choices):
        choices = [(value, value)] + choices
    return [(raw if v == value else v, label, v == value) for v, label in choices]


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

    properties = [(key, value, _select_options(key, value)) for key, value in properties_data]
    return render_template("server_settings.html", properties=properties)
