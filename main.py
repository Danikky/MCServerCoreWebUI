from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
from flask_socketio import SocketIO, emit
import os
import sys
import subprocess
import threading
from werkzeug.security import generate_password_hash, check_password_hash
import db

app = Flask("__main__")
app.secret_key = os.urandom(24)

db_name = db.db_name

socketio = SocketIO(app)

# Настройка Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, user_id, username):
        self.id = user_id
        self.username = username

db.init_db()

db.firts_time_admin()

console_manager = db.BatProcessManager(
        bat_path="C:\\Users\\riper\\ToolsUsefull\\MyProgramDev\\CoreServer\\start.bat",
        working_dir="C:\\Users\\riper\\ToolsUsefull\\MyProgramDev\\CoreServer\\"
    )

        
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
            db.reg_user(username, password)
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
        user = db.login(username)
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
        console_input_msg = request.form.get("console_input")
        console_manager._write_input(console_input_msg)
        console_data = console_manager.output_data
        return render_template("server.html", console_data=console_data)
    else:
        console_data = console_manager.output_data
        return render_template("server.html", console_data=console_data)

# Настройка сервера
@app.route("/server/settings", methods=['GET', 'POST'])
@login_required
def server_settings():
    properties_data = db.get_properties_data()
    new_values = []
    for i in range(len(properties_data)):
        new_value = request.form.get(properties_data[i][0])
        if new_value not in [None, "null", ""]:
            db.update_properties(properties_data[i][0], new_value)
    else:
        properties_data = db.get_properties_data()
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
            db.set_status(username, value.replace("1", ""), 1)
        elif "0" in value:
            db.set_status(username, value.replace("0", ""), 0)
        players_data = db.get_all_players_data()
        return render_template("server_players.html", players_data=players_data)
    else:
        players_data = db.get_all_players_data()
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
    console_manager.start()
    app.run(host='0.0.0.0', port=5000, debug=True) # ДЕБАГ ФАЛС ПОМЕЯТЬ НА TRUE!!!! При тестах