from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
from flask_socketio import SocketIO, emit
import os
import sys
import subprocess
import threading
from werkzeug.security import generate_password_hash, check_password_hash

server_dir_path = r"C:\Users\riper\ToolsUsefull\MyProgramDev\CoreServer"
db_name = "DataBase.db"

def init_db():
    conn = sqlite3.connect(f"{db_name}")
    c = conn.cursor()
    
    c.execute("""CREATE TABLE IF NOT EXISTS servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    core TEXT NOT NULL,
    path TEXT NOT NULL
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    is_online BOOLEAN DEFAULT FALSE,
    is_op BOOLEAN DEFAULT FALSE,
    is_banned BOOLEAN DEFAULT FALSE,
    is_ip_banned BOOLEAN DEFAULT FALSE,
    is_vip BOOLEAN DEFAULT FALSE,
    is_whitelist BOOLEAN DEFAULT FALSE,
    is_blacklist BOOLEAN DEFAULT FALSE,
    server_id INTEGER NOT NULL,
    FOREIGN KEY (server_id) REFERENCES servers(id)
    )""")
    
    c.execute(""" CREATE TABLE IF NOT EXISTS console_output (
    line TEXT NOT NULL,
    server_id INTEGER NOT NULL,
    FOREIGN KEY (server_id) REFERENCES servers(id)
    )""")
    
    conn.commit()
    c.close()
    conn.close()

def create_server_folder(folder_name: str) -> bool:
    try:
        path = "servers/" + folder_name
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        print(f"Непредвиденная ошибка при создании папки: {e}")

def create_server(name, core):
    path = "servers/" + name
    conn = sqlite3.connect(f"{db_name}")
    c = conn.cursor()
    try:
        c.execute("INSERT INTO servers (name, core, path)", (name, core, path))
        c.execute("SELECT id FROM servers WHERE name = ?", (name,))
        id = c.fetchone()
    except:
        print("При создании сервера чтото пошло не так")
    conn.commit()
    c.close()
    conn.close()
    return id[0]
    
    

def get_server_data(id):
    conn = sqlite3.connect(f"{db_name}")
    c = conn.cursor()
    c.execute("SELECT * FROM servers WHERE id = ?", (id,))
    server_data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    return server_data
    

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
        print("ПИЗДАААААААААААААААА")
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

def get_console_output(server_id):
    try:
        conn = sqlite3.connect(f"{db_name}")
        c = conn.cursor()
        c.execute("SELECT * FROM console_output WHERE server_id = ?", (server_id))
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
        
def get_servers_data():
    try:
        conn = sqlite3.connect(f"{db_name}")
        c = conn.cursor()
        c.execute("SELECT * FROM servers")
        servers_data = c.fetchall()
        return servers_data
    except:
        print("При получении servers_data что-то пошло не так")
    finally:
        conn.commit()
        c.close()
        conn.close()


create_server_folder("loh_nah")