from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
from flask_socketio import SocketIO, emit
import asyncio
import os
import sys
import psutil
from mcrcon import MCRcon
import subprocess
import threading
import time
from werkzeug.security import generate_password_hash, check_password_hash
import stmc
import datetime as dt

# Направление сайта - 
# web-GUI для управлением сервером

# Задачи:
# - Сделать код более читаемый 
# - Сделать интерфейс красивым
# - Автоматизировать активацию rcon (теперь добавить кнопку на странице настроек)
# - Сделать страницу 'выбора' ядра:
# - Сделать чистую переустановку ядра
# - Прописать DEBUG-log  "[DEBUG: *time*] : 'что-то случилось'
# - Сделать автоотчистку БД + отдельный интерфейс с кнопкой 'сброс'
# - Сделать возможность работать с несколькими ядрами одновременно
# - Выводить на панель управления информанци об онлайне, ОЗУ, RAM, сети, IP, статусы РЕАЛ ТАЙМ
# - Сделать логирование и архивирование консольного вывода, по циклам работы ядра
# - Переписать страницу управления игроками под работу с json а не с БД

stmc.init_db()
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

class server_manager(): # КЛАСС ДОЛЖЕН БЫТЬ ТУТ!!!
    def __init__(self):
        # self._kill_processes_locking_file(os.path.join(path, "world", "session.lock"))
        stmc.set_all_offline()
        self.path = os.path.join(stmc.return_main_dir(), "server") # путь к папке сервера
        for i in os.listdir(self.path):
            if ".jar" in i:
                self.core = i
        
    def start_server(self):
        self.proccess = subprocess.Popen(
            ['java', '-Xmx8024M', '-Xms1024M', '-jar', self.core, "nogui"], # аргументы запуска сервера
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
            if "INFO]: Thread RCON Client" in line:
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
    
    def system_monitoring(self):
        self.cpu = psutil.cpu_percent(interval=1)
        self.cpu_cores = psutil.cpu_count(logical=True)
        self.memory = psutil.virtual_memory()
        self.disk = psutil.disk_usage('/')
        return ({
            "cpu_percent": f"{server.cpu}%",
            "cpu_cores": server.cpu_cores,
            "ram_total": f"{round(server.memory.total / (1024 ** 3), 1)} GB",
            "ram_used": f"{round(server.memory.used / (1024 ** 3), 1)} GB",
            "ram_available": f"{round(server.memory.available / (1024 ** 3), 1)} GB",
            "ram_percent": f"{server.memory.percent}%",
            "disk_total": f"{round(server.disk.total / (1024 ** 3), 1)} GB",
            "disk_used": f"{round(server.disk.used / (1024 ** 3), 1)} GB",
            "disk_free": f"{round(server.disk.free / (1024 ** 3), 1)} GB",
            "disk_percent": f"{server.disk.percent}%"
        })
        
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
        if "You need to agree to the EULA in order to run the server" in line:
            stmc.agree_eula()
            self.kill_server()
            time.sleep(3)
            self.start_server()
        if "This is the first time you're starting this server" in line:
            self.enable_rcon()
            
    def is_server_running(self):
        """Проверяет, работает ли процесс сервера"""
        for proc in psutil.process_iter():
            try:
                if "java" in proc.name().lower():
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False
    
    def get_properties_data(self):
        result = []
        properties_path = self.path + "\server.properties"
        with open(properties_path, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped[0] in ('#', '!'):
                    continue
                if '=' in stripped:
                    key, value = stripped.split('=', 1)
                    result.append([
                        key.strip(),
                        value.strip()
                    ])
        return result
        
    def update_properties(self, key, value):
        updated = False
        new_lines = []
        properties_path = self.path + "\server.properties"
        with open(properties_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip().startswith(('#', '!')) or len(line.strip()) == 0:
                    new_lines.append(line)
                    continue
                if '=' in line:
                    key_part, value_part = line.split('=', 1)
                    current_key = key_part.strip()
                    if current_key == key:
                        separator = line[len(key_part.rstrip()):].split('=', 1)[0]
                        new_line = f"{key}={value}\n"
                        new_lines.append(new_line)
                        updated = True
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)
        if not updated:
            raise ValueError(f"Ключ '{key}' не найден в файле")
        with open(properties_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        return True
    
    def get_json(self, json_file):
        # banned-ips.json
        # banned-players.json
        # ops.json
        # usercache.json
        # whitelist.json
        # version_history.json
        json_file = self.path + "\\" + json_file
        f = open(json_file, "r", encoding="utf-8")
    
    def update_json(self, json_file, key, value):
        pass

    def kill_server(self):
        self.proccess.terminate()
        time.sleep(1)
        if self.proccess.poll() is None:
            self.proccess.kill()

    def get_backups_list(self):
        if "backups" not in stmc.get_dir(self.path):
            stmc.make(self.path + "\\backups", True)
        return stmc.get_dir(self.path + "\\backups")

    def create_backup(self, name):
        date = dt.datetime.now()
        stmc.clone_dir(self.path, self.path + f"\\backups\\{name}-{date}")
        stmc.delete(self.path + f"\\backups\\{name}-{date}\\backups")

    def delete_backup(self, name):
        stmc.delete(self.path + f"\\backups\\{name}")

    def rename_backup(self, name, new_name):
        stmc.rename(self.path + f"\\backups\\{name}", new_name)
        
    def get_properties_value(self, key):
        properties_path = self.path + "\server.properties"
        with open(properties_path, 'r', encoding='utf-8') as f:
            for line in f:
                if '=' in line:
                    current_key, value = line.split('=', 1)
                    current_key = current_key.strip()
                    if current_key == key:
                        return value
                    
    def enable_rcon(self):
        self.update_properties("rcon.password", 111111)
        self.update_properties("enable-rcon=true", True)

# Инициализация сервера
server = server_manager()

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
    system_data = None # server.system_monitoring() #
    online_players = len(stmc.get_online())
    if request.method == "POST":
        console_input = request.form.get("console_input")
        command = request.form.get("command")
        if console_input not in [None, "null", ""]:
            server.send_rcon_command(console_input)
        if command not in [None, "null", ""]:
            if command == "start":
                if server.is_server_running() == False:
                    server.start_server()
            elif command == "enable_rcon":
                server.enable_rcon()
            else:
                server.send_rcon_command(command)
        is_server_run = server.is_server_running()
        return render_template("control_panel.html", is_server_run=is_server_run, system_data=system_data, online_players=online_players)
    else:
        is_server_run = server.is_server_running()
        return render_template("control_panel.html", is_server_run=is_server_run, system_data=system_data, online_players=online_players)

# Маршрут для получения истории консоли
@app.route("/get_console_history")
def get_console_history():
    console_data = stmc.get_console_output()
    history = [line[0] for line in console_data]
    return jsonify({'history': history})

@app.route("/get_system")
def get_system():
    return jsonify({
        "cpu_percent": f"{server.cpu}%",
        "cpu_cores": server.cpu_cores,
        "ram_total": f"{round(server.memory.total / (1024 ** 3), 1)} GB",
        "ram_used": f"{round(server.memory.used / (1024 ** 3), 1)} GB",
        "ram_available": f"{round(server.memory.available / (1024 ** 3), 1)} GB",
        "ram_percent": f"{server.memory.percent}%",
        "disk_total": f"{round(server.disk.total / (1024 ** 3), 1)} GB",
        "disk_used": f"{round(server.disk.used / (1024 ** 3), 1)} GB",
        "disk_free": f"{round(server.disk.free / (1024 ** 3), 1)} GB",
        "disk_percent": f"{server.disk.percent}%"
    })
    
# Настройка сервера
@app.route("/server/settings", methods=['GET', 'POST'])
@login_required
def server_settings():
    if request.method == "POST":
        for i in range(len(properties_data)):
            new_value = request.form.get(properties_data[i][0])
            if new_value not in [None, "null", ""]:
                server.update_properties(properties_data[i][0], new_value)
        properties_data = server.get_properties_data()
        return render_template("server_settings.html", properties_data=properties_data)
    else:
        properties_data = server.get_properties_data()
        return render_template("server_settings.html", properties_data=properties_data)

# Управление файлами сервера (редактирование/создание/удаление файлов, директорий)
@app.route("/server/files/<string:path>", methods=["POST", "GET"])
@login_required
def server_files_to(path):
    dir_list = os.listdir(stmc.return_main_dir() + "\\" + str(path).replace("-", "\\"))
    dir_list = stmc.sort_dir(dir_list)
    is_renaming = [None, False]
    if request.method == "POST":
        command = request.form.get("command")
        item = request.form.get("item")
        text = request.form.get("text")
        new_name = request.form.get("new_name")
        if command not in [None, "null", ""]:
            if command == "open":
                pass
            if command == "rename":
                is_renaming = [item, True]
                if new_name != "":
                    stmc.rename(str(path.replace("-", "\\"))+"\\"+item, new_name)
            if command == "delete":
                stmc.delete(str(path.replace("-", "\\"))+"\\"+item)
            if command == "make":
                if "." in item:
                    stmc.make(str(path.replace("-", "\\"))+"\\"+item, False)
                else:
                    stmc.make(str(path.replace("-", "\\"))+"\\"+item, True)
            dir_list = os.listdir(stmc.return_main_dir() + "\\" + str(path).replace("-", "\\"))
            dir_list = stmc.sort_dir(dir_list)
        return render_template("server_files.html", dir_list=dir_list, path=path, is_renaming=is_renaming)
    else:
        return render_template("server_files.html", dir_list=dir_list, path=path, is_renaming=is_renaming)

# Управление игроками (Кто играет realtime, Кто заходил, Права, Баны, Вишлист)
@app.route("/server/players", methods=["POST", "GET"])
@login_required
def server_players():
    if request.method == "POST":
        online = [len(stmc.get_online()), server.get_properties_value("max-players")]
        username = request.form.get("username")
        command = request.form.get("value")
        if command not in [None, "null", ""]:
            server.send_rcon_command(command+" "+username)
            command = stmc.command_to_param(command)
            if command:
                stmc.set_status(username, command[0], command[1])
        players_data = stmc.get_all_players_data()
        return render_template("server_players.html", players_data=players_data, online=online)
    else:
        online = [len(stmc.get_online()), server.get_properties_value("max-players")]
        players_data = stmc.get_all_players_data()
        return render_template("server_players.html", players_data=players_data, online=online)

# Страница со списком бекапов и возможностью их создавать
@app.route("/server/backups")
@login_required
def backups_page():
    backups_list = server.get_backups_list()
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
    else:
        return render_template("backups_page.html", backups_list=backups_list, is_renaming=is_renaming)

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
    