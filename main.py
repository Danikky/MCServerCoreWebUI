from flask import Flask, render_template

app = Flask("__main__")


# Главная страница (Вход, Оперативные операции, info)
@app.route("/")
def index():
    return render_template("index.html")

# Управление (Консоль, Данные, Производительность, Игроки) (Fast data)
@app.route("/server")
def server():
    return render_template("server.html")

# Настройка сервера
@app.route("/server/settings")
def server_settings():
    return render_template("server_settings.html")

# Управление файлами серрвера (редактирование/создание/удаление файлов, директорий)
@app.route("/server/files")
def server_files():
    return render_template("server_files.html")

# Управление игроками (Кто играет realtime, Кто заходил, Права, Баны, Вишлист)
@app.route("/server/players")
def server_players():
    return render_template("server_players.html")

# Управление базами данных (Вывод/редактирование таблиц)
@app.route("/server/sqltables")
def server_sql_tables():
    return render_template("server_sql.html")

# Карта сервера (Интеграция плагина, Вывод/редактирование)
@app.route("/server/map")
def server_map():
    return render_template("server_map.html")

# Для безопастного импорта файла(как библиотека) + run
if __name__ == "__main__":
    app.run(debug=True)