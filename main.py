from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
from flask_socketio import SocketIO, emit
import os
import sys
import psutil
from mcrcon import MCRcon
import subprocess
import threading
import time
from werkzeug.security import generate_password_hash, check_password_hash
import stmc

# Задачи:
# - Сделать код более читаемый
# - организовать работу с множеством ядер одновременно
# - сделать возможность компилировать и настраивать ядро + библиотека ядер
# - Доделать управление файлами сервера
# - Доделать *real-time* консоль

stmc.init_db()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")


class server_manager(): # КЛАСС ДОЛЖЕН БЫТЬ ТУТ!!!
    def __init__(self, path):
        # self._kill_processes_locking_file(os.path.join(path, "world", "session.lock"))
        stmc.set_all_offline()
        self.path = path 
    
    def start_server(self):
        
        self.proccess = subprocess.Popen(
            ['java', '-Xmx8024M', '-Xms1024M', '-jar', 'paper-1.21.4-227.jar'],
            cwd=self.path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=0,
            universal_newlines=True
        )

        self.reader_thread = threading.Thread(
            target=self.get_console_output,
            daemon=True
        )
        
        self.reader_thread.start()
    
    def get_console_output(self):
        while True:
            line = self.proccess.stdout.readline()
            if not line and self.proccess.poll() is not None:
                break
            if line:
                stmc.add_line(line)
                self.console_event_check(line)
                socketio.start_background_task(
                socketio.emit, 
                'console_update', 
                {'line': line.strip()}, 
                namespace='/server'
            )    # Отправка события
                print(line)  # Для отладки
    
    def send_rcon_command(self, command: str):
        try:
            with MCRcon("localhost", "111111", 25575) as mcr:
                response = mcr.command(command)
                stmc.add_line(command)
                stmc.add_line(response)
                print(f"Ответ сервера: {response}")
        except Exception as e:
            print(f"Ошибка: {str(e)}", file=sys.stderr)
    
    def console_event_check(self, line: str):
        if "joined the game" in line:
            line_data = line.split() # разделяет строку на список по пробелам
            name = line_data[2].replace("[38;2;255;255;85m", "")
            stmc.reg_player(name)
            stmc.set_status(name, "is_online", True)
            self.players = stmc.get_online()
            
        if "left the game" in line:
            line_data = line.split() # разделяет строку на список по пробелам
            name = line_data[2].replace("[38;2;255;255;85m", "")
            stmc.set_status(name, "is_online", False)
            self.players = stmc.get_online()
            
    
    def is_server_running(self):
        """Проверяет, работает ли процесс сервера"""
        for proc in psutil.process_iter():
            try:
                if "java" in proc.name().lower() and "paper" in " ".join(proc.cmdline()):
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False

server_dir_path = r"C:\Users\riper\ToolsUsefull\MyProgramDev\CoreServer"
server = server_manager(server_dir_path)

@socketio.on('connect', namespace='/server')
def handle_connect():
    print("Клиент подключился к WebSocket")

# Нужен скрипт - хранитель переменных !!!
db_name = stmc.db_name

# Настройка Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, user_id, username):
        self.id = user_id
        self.username = username

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

@app.route("/")
def index():
    return render_template("index.html")

# Страница о нас
@app.route("/about")
def about():
    return render_template("about.html")

# Сервер (Консоль, Данные, Производительность, Игроки, управление) (Fast data)
@app.route("/server", methods=["POST", "GET"])
@login_required
def server_console():
    console_output = []
    if request.method == "POST":
        console_input = request.form.get("console_input")
        command = request.form.get("command")
        
        if console_input not in [None, "null", ""]:
            server.send_rcon_command(console_input)
        
        if command not in [None, "null", ""]:
            if command == "start":
                if server.is_server_running() == False:
                    server.start_server()
            else:
                server.send_rcon_command(command)
            
        is_server_run = server.is_server_running()
        return render_template("server.html", is_server_run=is_server_run)
    else:
        is_server_run = server.is_server_running()
        return render_template("server.html", is_server_run=is_server_run)

# Новый маршрут для получения истории консоли
@app.route('/get_console_history')
def get_console_history():
    console_data = stmc.get_console_output()
    history = [line[0] for line in console_data]
    return jsonify({'history': history})

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

# Управление файлами сервера (редактирование/создание/удаление файлов, директорий)
@app.route("/server/files", methods=["POST", "GET"])
@login_required
def server_files():
    dir_list = os.listdir(server_dir_path)
    if request.method == "POST":
        return render_template("server_files.html", dir_list=dir_list)
    else:
        return render_template("server_files.html", dir_list=dir_list)

# Управление игроками (Кто играет realtime, Кто заходил, Права, Баны, Вишлист)
@app.route("/server/players", methods=["POST", "GET"])
@login_required
def server_players():
    if request.method == "POST":
        online_players = len(stmc.get_online())
        username = request.form.get("username")
        command = request.form.get("value")
        if command not in [None, "null", ""]:
            server.send_rcon_command(command+" "+username)
            command = stmc.command_to_param(command)
            if command:
                stmc.set_status(username, command[0], command[1])
                
        players_data = stmc.get_all_players_data()
        return render_template("server_players.html", players_data=players_data, online_players=online_players)
    else:
        online_players = len(stmc.get_online())
        players_data = stmc.get_all_players_data()
        return render_template("server_players.html", players_data=players_data, online_players=online_players)

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
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
    # app.run(host='0.0.0.0', port=5000, debug=True) # НЕ ТРОГАТЬ ПОКА РАБОТАЕТ!!!
    