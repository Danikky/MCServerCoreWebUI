from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
from flask_socketio import SocketIO, emit
import os
import sys
import subprocess
import threading
from werkzeug.security import generate_password_hash, check_password_hash
import stmc

# Нужен скрипт - хранитель переменных !!!
start_bat_path = "Путь к батнику, запускающему сервер"
server_dir = "Папка сервера #для управления файлами"
db_name = "Server.db" # или db.db_name


app = Flask("__main__")
app.secret_key = os.urandom(24)

socketio = SocketIO(app)

# Настройка Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, user_id, username):
        self.id = user_id
        self.username = username

stmc.init_db()

stmc.firts_time_admin()
        
@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(f"{db_name}")
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    user = c.fetchone()
    conn.close()
    if user:
        return User(user[0], user[1])
    return None

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        try:
            stmc.reg_user(username, password)
            flash('Регистрация прошла успешно!')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Пользователь с таким именем уже существует')
    return render_template('register.html')

# Маршруты аутентификации
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = stmc.login(username)
        if user and check_password_hash(user[2], password):
            user_obj = User(user[0], user[1])
            login_user(user_obj)
            return redirect(url_for('index'))
        flash('Неверное имя пользователя или пароль')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# Главная страница (Вход, Оперативные операции, info)
@app.route("/")
def index():
    return render_template("index.html")

# Страница о нас
@app.route("/about")
def about():
    return render_template("about.html")

# Управление (Консоль, Данные, Производительность, Игроки) (Fast data)
@app.route("/server", methods=["POST", "GET"])
@login_required
def server():
    if request.method == "POST":
        return render_template("server.html")
    else:
        return render_template("server.html")

# Настройка сервера
@app.route("/server/settings", methods=['GET', 'POST'])
@login_required
def server_settings():
    properties_data = stmc.get_properties_data()
    for i in range(len(properties_data)):
        new_value = request.form.get(properties_data[i][0])
        if new_value not in [None, "null", ""]:
            stmc.update_properties(properties_data[i][0], new_value)
    else:
        properties_data = stmc.get_properties_data()
        return render_template("server_settings.html", properties_data=properties_data)

# Управление файлами серрвера (редактирование/создание/удаление файлов, директорий)
@app.route("/server/files")
@login_required
def server_files():
    return render_template("server_files.html")

# Управление игроками (Кто играет realtime, Кто заходил, Права, Баны, Вишлист)
@app.route("/server/players", methods=["POST", "GET"])
@login_required
def server_players():
    if request.method == "POST":
        username = request.form.get("username")
        value = request.form.get("value")
        if "1" in value:
            stmc.set_status(username, value.replace("1", ""), 1)
        elif "0" in value:
            stmc.set_status(username, value.replace("0", ""), 0)
        players_data = stmc.get_all_players_data()
        return render_template("server_players.html", players_data=players_data)
    else:
        players_data = stmc.get_all_players_data()
        return render_template("server_players.html", players_data=players_data)

# Управление базами данных (Вывод/редактирование таблиц)
@app.route("/server/sqltables")
@login_required
def server_sql_tables():
    return render_template("server_sql.html")

# Карта сервера (Интеграция плагина, Вывод/редактирование)
@app.route("/server/map")
@login_required
def server_map():
    return render_template("server_map.html")

# Для безопастного импорта файла(как библиотека) + run
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True) # НЕ ТРОГАТЬ ПОКА РАБОТАЕТ!!!