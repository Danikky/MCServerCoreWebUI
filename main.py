from flask import Flask, render_template

app = Flask("__main__")


# Главная страница (Вход, Оперативные операции, info)
@app.route("/")
def index():
    return render_template("index.html")

# Страница авторизации
@app.route("/auth")
def auth():
    return "/auth"

# Управление (Консоль, Данные, Производительность, Игроки) (Fast data)
@app.route("/server")
def server():
    return "/server"

# Настройка сервера
@app.route("/server/settings")
def server_settings():
    return "/server/settings"

# Управление файлами серрвера (редактирование/создание/удаление файлов, директорий)
@app.route("/server/files")
def server_files():
    return "/server/files"

# Управление игроками (Кто играет realtime, Кто заходил, Права, Баны, Вишлист)
@app.route("/server/players")
def server_players():
    return "/server/players"

# Управление базами данных (Вывод/редактирование таблиц)
@app.route("/server/sqltables")
def server_sql_tables():
    return "/server/sqltables"

# Карта сервера (Интеграция плагина, Вывод/редактирование)
@app.route("/server/map")
def server_map():
    return "/server/map"

# Для безопастного импорта файла(как библиотека) + run
if __name__ == "__main__":
    app.run(debug=True)