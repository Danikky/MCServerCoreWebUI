from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
from flask_socketio import SocketIO, emit
import os
import sys
import subprocess
import threading
import shutil
from werkzeug.security import generate_password_hash, check_password_hash

server_dir_path = r"C:\Users\riper\ToolsUsefull\MyProgramDev\CoreServer"
db_name = "DataBase.db"

def init_db():
    conn = sqlite3.connect(f"{db_name}")
    c = conn.cursor()
    
    c.execute("""CREATE TABLE IF NOT EXISTS users
    (id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL
    )
    """)
    
    c.execute("""CREATE TABLE IF NOT EXISTS players
    (id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    is_online BOOLEAN DEFAULT FALSE,
    is_op BOOLEAN DEFAULT FALSE,
    is_banned BOOLEAN DEFAULT FALSE,
    is_ip_banned BOOLEAN DEFAULT FALSE,
    is_vip BOOLEAN DEFAULT FALSE,        
    is_whitelist BOOLEAN DEFAULT FALSE,
    is_blacklist BOOLEAN DEFAULT FALSE
    )
    """)
    
    c.execute(""" CREATE TABLE IF NOT EXISTS console_output (
    line TEXT NOT NULL
    )
    """)
    
    conn.commit()
    c.close()
    conn.close()

# Временный скрипт для создания администратора    
def firts_time_admin():
    conn = sqlite3.connect(f"{db_name}")
    c = conn.cursor()
    admin_password = generate_password_hash('123') # пароль админа
    c.execute("INSERT OR IGNORE INTO users (username, password) VALUES (?, ?)", ("admin", admin_password))
    conn.commit()
    c.close()
    conn.close()
    
def register(username, password):
    conn = sqlite3.connect(f"{db_name}")
    c = conn.cursor()
    c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
    conn.commit()
    c.close()
    conn.close()

def login(username):
    try:
        conn = sqlite3.connect(f"{db_name}")
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        return user
    except:
        return None
    finally:
        conn.commit()
        c.close()
        conn.close()

# Зашёл первый раз (скрипт проверил)
def reg_player(username):
    try:
        conn = sqlite3.connect(f"{db_name}")
        c = conn.cursor()
        c.execute("INSERT INTO players (username) VALUES (?)", (username,))
    except:
        return None
    finally:
        conn.commit()
        c.close()
        conn.close()
        
def set_status(username, status, value):
    """Параметры:
    Args:
        status: is_online, is_op, is_banned, is_ip_banned, is_vip, is_whitelist, is_blacklist
    """
    try:
        conn = sqlite3.connect(f"{db_name}")
        c = conn.cursor()
        c.execute(f"UPDATE players SET {status} = ? WHERE username = ?", (value, username))
    except:
        print("ошибка при обновлении статуса")
    finally:
        conn.commit()
        c.close()
        conn.close()
        
def get_online():
    try:
        conn = sqlite3.connect(f"{db_name}")
        c = conn.cursor()
        c.execute("SELECT * FROM players WHERE is_online = 1")
        online = c.fetchall()
        if online != None:
            return online
        else:
            return 0
    except:
        print("Не удалось получить список онлайн игрков")
    finally:
        conn.commit()
        c.close()
        conn.close()
        
def get_all_players_data():
    try:
        conn = sqlite3.connect(f"{db_name}")
        c = conn.cursor()
        c.execute("SELECT * FROM players")
        players_data = c.fetchall()
        return players_data
    except:
        return None
    finally:
        conn.commit()
        c.close()
        conn.close()
        
def add_line(line):
    try:
        conn = sqlite3.connect(f"{db_name}")
        c = conn.cursor()
        c.execute("INSERT INTO console_output (line) VALUES (?)", (line,))
    except:
        print("При добавлении линии чтото наебнулось")
    finally:
        conn.commit()
        c.close()
        conn.close()

def get_console_output():
    try:
        conn = sqlite3.connect(f"{db_name}")
        c = conn.cursor()
        c.execute("SELECT * FROM console_output")
        output = c.fetchall()
        return output
    except:
        print("При получении вывода консоли чтото наебнулось")
    finally:
        conn.commit()
        c.close()
        conn.close()

def set_all_offline():
    for i in get_all_players_data():
        try:
            conn = sqlite3.connect(f"{db_name}")
            c = conn.cursor()
            c.execute(f"UPDATE players SET is_online = False WHERE username = ?", (i[1],))
        except:
            print("ошибка при обновлении статуса")
        finally:
            conn.commit()
            c.close()
            conn.close()
            
def return_main_dir():
    if getattr(sys, 'frozen', False):
        script_path = os.path.dirname(sys.executable)
    else:
        script_path = os.path.dirname(os.path.abspath(__file__))
    return script_path

def rename(folder_path, new_name):  # Указать пусть, относительно self.path
    path = os.path.join(return_main_dir() + "\server", folder_path)
    try:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Объект не найден: {path}")
        parent_dir = os.path.dirname(path)
        new_path = os.path.join(parent_dir, new_name)
        if os.path.exists(new_path):
            raise FileExistsError(f"Имя уже занято: {new_name}")
        os.rename(path, new_path)
        return True
    except Exception as e:
        print(f"Ошибка переименования: {str(e)}")
        return False
    
def delete(folder_path): # Указать пусть, относительно self.path
    path = os.path.join(return_main_dir() + "\server", folder_path)
    try:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Объект не найден: {path}")
        if os.path.isfile(path):
            os.remove(path)
            return True
        if os.path.isdir(path):
            shutil.rmtree(path)
            return True
    except Exception as e:
        print(f"Ошибка удаления: {str(e)}")
        return False

    
def get_dir(folder_path): # Указать пусть, относительно self.path
    dir_path = os.path.join(return_main_dir() + "\server", folder_path)
    dir_list = os.listdir(dir_path)
    return dir_list
    
def make(folder_path, is_directory): # Указать пусть, относительно self.path
    path = os.path.join(return_main_dir() + "\server", folder_path)
    try:
        if os.path.exists(path):
            raise FileExistsError(f"Объект уже существует: {path}")
        if is_directory:
            os.makedirs(path, exist_ok=True)
            return True
        parent_dir = os.path.dirname(path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
        with open(path, 'w') as f:
            pass
        return True
    except:
        print("Ошибка при создании файла/директории")

def sort_dir(dir_list): # Сортирует директории по типу - папки>файлы
    new_list = []
    for i in dir_list:
        if "." not in i:
            new_list.append(i)
    for i in dir_list:
        if "." in i:
            new_list.append(i)
    if len(dir_list) != len(new_list):
        print("При сортировке были потеряны файлы")
    return new_list

def command_to_param(command):
    if command == "op":
        return ["is_op", True]
    elif command == "deop":
        return ["is_op", False]
    elif command == "ban":
        return ["is_banned", True]
    elif command == "pardon":
        return ["is_banned", False]
    elif command == "whitelist add":
        return ["is_whitelist", True]
    elif command == "whitelist remove":
        return ["is_whitelist", False]
    elif command == "blacklist add":
        return ["is_blacklist", True]
    elif command == "blacklist remove":
        return ["is_blacklist", False]
    else:
        return False