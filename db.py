from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
from flask_socketio import SocketIO, emit
import os
from werkzeug.security import generate_password_hash, check_password_hash


db_name = "Server.db"

def init_db():
    conn = sqlite3.connect(f"{db_name}")
    c = conn.cursor()
    
    c.execute("""CREATE TABLE IF NOT EXISTS users
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
                )""")
    
    # Статусы игрока будут браться из файлов сервера, там списки забаненых и т.д,
    # Онлайн игрока будет ставиться так: Скрипт проверяет консоль- если есть сообщение о присоединении игрока
    # ставит ему is_online true, и регистрирует если он первый раз зашел,
    # которе нужен крутой мониторющий консоль и файлы скрипт. и пару моментов с несоответствиями проработать
    # Нужно это всё для вкладки players и отображения онлайна. я сам придумал, хз как ещё можно
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
                )""")
    
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
        print("пизда")
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
        
def update_properties(key, value):
    # Сюда путь к файлу с настройками (НЕ ЗАБЫТЬ \\ ВМЕСТО \)
    file_path = "C:\\Users\\riper\\ToolsUsefull\\MyProgramDev\\CoreServer\\server.properties"
    updated = False
    new_lines = []

    with open(file_path, 'r', encoding='utf-8') as f:
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
    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

    return True

def get_properties_data():
    file_path = "C:\\Users\\riper\\ToolsUsefull\\MyProgramDev\\CoreServer\\server.properties"
    result = []
    with open(file_path, 'r', encoding='utf-8') as f:
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