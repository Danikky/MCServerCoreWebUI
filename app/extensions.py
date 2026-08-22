"""
Общие для всего приложения объекты расширений — создаются здесь без
привязки к конкретному Flask-приложению, инициализируются на нём в
create_app() (app/__init__.py). Так модели/блюпринты могут импортировать
`db`/`socketio` не боясь циклических импортов через сам create_app.
"""
from flask_login import LoginManager
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
socketio = SocketIO()
