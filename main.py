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

# Направление сайта - 
# web-GUI для управлением сервером

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
    def __init__(self, id):
        # self._kill_processes_locking_file(os.path.join(path, "world", "session.lock"))
        stmc.set_all_offline()
        if id == None:
            self.id = None
            self.path = r"C:\Users\riper\ToolsUseFull\Projects\ServerSite"
        else:
            self.id = id
            server_data = stmc.get_server_data(self.id)
            self.name = server_data[1]
            self.path = "\\{self.name}"
            # self.core = ...
            # self.db = ...
    
    def get_folder(self):
        folder_path = self.path
        return [os.path.join(folder_path, item) for item in os.listdir(folder_path)]
    
    def get_cores(self):
        folder_path = self.path + r"/cores"
        return [os.path.join(folder_path, item) for item in os.listdir(folder_path)]
        
    def get_servers(self):
        folder_path = r"/servers"
        return [os.path.join(folder_path, item) for item in os.listdir(folder_path)]
    
    def start_server(self):
        self.proccess = subprocess.Popen(
            ['java', '-Xmx8024M', '-Xms1024M', '-jar', self.core],
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
    
    def get_properties_data(self):
        result = []
        properties_path = self.path + "server.properties"
        with open(properties_path, 'r', encoding='utf-8') as f:
            for line in f:
                # Убираем пробелы и пропускаем пустые строки/комментарии
                stripped = line.strip()
                if not stripped or stripped[0] in ('#', '!'):
                    continue
                # Разделяем ключ и значение
                if '=' in stripped:
                    key, value = stripped.split('=', 1)
                    result.append([
                        key.strip(),
                        value.strip()
                    ])
        return result
    
    def update_properties(self, key, value):
        # Сюда путь к файлу с настройками (НЕ ЗАБЫТЬ \\ ВМЕСТО \)
        updated = False
        new_lines = []
        properties_path = self.path + "server.properties"
        with open(properties_path, 'r', encoding='utf-8') as f:
            for line in f:
                # Сохраняем комментарии и пустые строки как есть
                if line.strip().startswith(('#', '!')) or len(line.strip()) == 0:
                    new_lines.append(line)
                    continue
                # Разделяем ключ и значение с сохранением разделителя
                if '=' in line:
                    key_part, value_part = line.split('=', 1)
                    current_key = key_part.strip()
                    if current_key == key:
                        # Сохраняем оригинальное форматирование
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
    
        # Перезаписываем файл
        with open(properties_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        return True
    
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

@socketio.on('connect', namespace='/server')
def handle_connect():
    print("Клиент подключился к WebSocket")

# Нужен скрипт - хранитель переменных !!!
db_name = stmc.db_name
global server
server = server_manager(None)

@app.route("/", methods=["POST", "GET"])
def index():
    if request.method == "POST":
        return render_template("index.html", id=server.id)
    else:
        return render_template("index.html", id=server.id)

# Страница о нас
@app.route("/about")
def about():
    return render_template("about.html")

# Выбор сервера + новый
@app.route("/servers", methods=["POST", "GET"])
def servers_list():
    servers_data = []
    for i in range(len(server.get_servers())):
        x = [stmc.get_id_by_name(server.get_servers()[i].replace("/servers\\", "")), server.get_servers()[i].replace("/servers\\", "")]
        servers_data.append(x)
    if request.method == "POST":
        id = request.form.get("id")
    else:
        return render_template("servers.html", servers_data=servers_data)

# Сервер (Консоль, Данные, Производительность, Игроки, управление) (Fast data)
@app.route("/server/<int:id>", methods=["POST", "GET"])
def server_console(id):
    if server == None:
        server = server_manager(id)
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
    console_data = stmc.get_console_output(0)
    history = [line[0] for line in console_data]
    return jsonify({'history': history})

# Настройка сервера
@app.route("/server/<int:id>/settings", methods=['GET', 'POST'])
def server_settings(id):
    properties_data = server.get_properties_data()
    for i in range(len(properties_data)):
        new_value = request.form.get(properties_data[i][0])
        if new_value not in [None, "null", ""]:
            server.update_properties(properties_data[i][0], new_value)
    else:
        properties_data = server.get_properties_data()
        return render_template("server_settings.html", properties_data=properties_data)

# Управление файлами сервера (редактирование/создание/удаление файлов, директорий)
@app.route("/server/<int:id>/files", methods=["POST", "GET"])
def server_files(id):
    dir_list = os.listdir(server.path)
    if request.method == "POST":
        return render_template("server_files.html", dir_list=dir_list)
    else:
        return render_template("server_files.html", dir_list=dir_list)

# Управление игроками (Кто играет realtime, Кто заходил, Права, Баны, Вишлист)
@app.route("/server/<int:id>/players", methods=["POST", "GET"])
def server_players(id):
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
@app.route("/server/<int:id>/sqltables")
def server_sql_tables(id):
    return render_template("server_sql.html")

# Карта сервера (Интеграция плагина, Вывод/редактирование)
@app.route("/server/<int:id>/map")
def server_map(id):
    return render_template("server_map.html")

# Для безопастного импорта файла(как библиотека) + run
if __name__ == "__main__":
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
    # app.run(host='0.0.0.0', port=5000, debug=True) # НЕ ТРОГАТЬ ПОКА РАБОТАЕТ!!!