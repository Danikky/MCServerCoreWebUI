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
import json
import telebot

# Задачи:
# - сделать и поставить иконки для страниц
# - Сделать интерфейс красивым
# - Сделать страницу 'выбора' ядра:
# - Сделать чистую переустановку ядра
# - Сделать автоотчистку БД + отдельный интерфейс с кнопкой 'сброс'
# - Сделать возможность работать с несколькими ядрами одновременно
# - Выводить на панель управления информанци об онлайне, ОЗУ, RAM, сети, IP, статусы РЕАЛ ТАЙМ
# - Сделать логирование и архивирование консольного вывода, по циклам работы ядра
# - Сдедать консоль-ввод по вебсокету

stmc.init_db()
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

class server_manager(): # КЛАСС ДОЛЖЕН БЫТЬ ТУТ!!!
    def __init__(self):
        self.path = os.path.join(stmc.return_main_dir(), "server") # путь к папке сервера
        for i in os.listdir(self.path):
            if ".jar" in i:
                self.core = i
        self.online = []
        
    def start_server(self):
        self.proccess = subprocess.Popen(
            # Xmx - максиммальный, Xms - стартовый
            ["java", "-Xmx16256M", "-Xms8256M", "-jar", self.core, "nogui"], # аргументы запуска сервера
            cwd=self.path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=0,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace"
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
                )
                print(line)
    
    def send_command_direct(self, command: str) -> str: # Отправка команды напрямую через stdin
        if not self.proccess or self.proccess.poll() is not None:
            return "Сервер не запущен"
        try:
            self.proccess.stdin.write(command + '\n')
            self.proccess.stdin.flush()
            time.sleep(0.1)
            output_lines = []
            while True:
                line = self.proccess.stdout.readline()
                if not line:
                    break
                output_lines.append(line)
                if len(output_lines) > 20:
                    output_lines.pop(0)
            return ''.join(output_lines[-5:]) # Возвращается последние 5 строк!!!
        except Exception as e:
            stmc.add_line(f"Ошибка отправки команды: {str(e)}")
            print(f"[DEBUG: <time>] - {e}")
            return f"Ошибка отправки команды: {str(e)}"
    
    def system_monitoring(self):
        self.cpu = psutil.cpu_percent(interval=1)
        self.cpu_cores = psutil.cpu_count(logical=True)
        self.memory = psutil.virtual_memory()
        self.disk = psutil.disk_usage('/')
        return {
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
        }
    
    def console_event_check(self, line: str):
        if "You need to agree to the EULA in order to run the server" in line:
            stmc.agree_eula()
            self.kill_server()
            time.sleep(3)
            self.start_server()
        if "join" in line or "left" in line:
            for i in self.get_json("usercache.json"):
                if i["name"] in line:
                    if "join" in line:
                        self.online.append(i["name"])
                    if "left" in line:
                        self.online.remove(i["name"])
            
    def is_server_running(self):
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
        path = self.path + "\\" + json_file
        try:
            with open(path, 'r', encoding='utf-8') as file:
                data = json.load(file)
            return data
        except:
            print(f"ошибка при извлечении словаря из {json_file}")

    def update_players_data(self):
        usercaсhe = []
        for i in self.get_json("usercache.json"):
            usercaсhe.append(i)
        whitelist = []
        for i in self.get_json("whitelist.json"):
            whitelist.append(i["name"])
        oplist = []
        for i in self.get_json("ops.json"):
            oplist.append(i["name"])
        banlist = []
        for i in self.get_json("ops.json"):
            banlist.append(i["name"])
        return { # ЭТО СПИСКИ С ИМЕНАМИ!!!!!! ЧИТАЙ ФРОНТЕНДЕР!!!
            "usercaсhe": usercaсhe, # usercahe[i]["name"] = <имя типа> , usercahe[i]["uuid"] = <uuid>
            "whitelist": whitelist, # whitelist[i] = <имя типа>
            "oplist": oplist, # oplist[i] = <имя типа>
            "banlist": banlist, # banlist[i] = <имя типа>
            "online": self.online # online[i] = <имя типа>
        }
        
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
    
    def log_error(self, error):
        stmc.add_line(error)
        print(error)

# Инициализация сервера
server = server_manager()
# Важны момент!

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
            server.send_command_direct(console_input)
        if command not in [None, "null", ""]:
            if command == "start":
                if server.is_server_running() == False:
                    server.start_server()
            elif command == "stop":
                if server.is_server_running() == True:
                    server.send_command_direct("stop")
            elif command == "kill":
                try:
                    server.kill_server()
                except:
                    print("Ошибка при убийстве сервера")
                    stmc.add_line("Ошибка при убийстве сервера")
            else:
                server.send_command_direct(command)
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
    
# Настройка сервера
@app.route("/server/settings", methods=['GET', 'POST'])
@login_required
def server_settings():
    properties_data = server.get_properties_data()
    if request.method == "POST":
        for i in range(len(properties_data)):
            new_value = request.form.get(properties_data[i][0])
            if new_value not in [None, "null", ""]:
                server.update_properties(properties_data[i][0], new_value)
        properties_data = server.get_properties_data()
        return render_template("server_settings.html", properties_data=properties_data)
    else:
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
        online = [len(server.online), server.get_properties_value("max-players")]
        players_data = server.update_players_data()
        return render_template("server_players.html", players_data=players_data, online=online)
    else:
        online = [len(server.online), server.get_properties_value("max-players")]
        players_data = server.update_players_data()
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
    socketio.run(app, host='0.0.0.0', port=5245, debug=True)
    # app.run(host='0.0.0.0', port=5000, debug=True) # НЕ ТРОГАТЬ ПОКА РАБОТАЕТ!!!
    