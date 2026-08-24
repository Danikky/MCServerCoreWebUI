"""
create_app() — фабрика приложения (вместо Flask(__name__) на уровне модуля,
как было раньше). Даёт нормальный путь для тестов: каждый тест может
поднять свежий app с чистой in-memory БД через create_app(TestConfig).
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()  # до импорта app.config, который читает os.environ при загрузке класса
except ImportError:
    pass  # python-dotenv не обязателен — переменные окружения можно задать и без него

from flask import Flask, g
from flask_login import current_user
from flask_socketio import join_room

from app.config import Config
from app.extensions import csrf, db, login_manager, socketio
from app.fs_utils import return_main_dir
from app.models import User, ensure_first_admin, ensure_schema_migrations
from app.routes import register_blueprints
from app.server_registry import ServerRegistry


def create_app(config_class=Config):
    root = return_main_dir()
    app = Flask(
        __name__,
        template_folder=os.path.join(root, "templates"),
        static_folder=os.path.join(root, "static"),
    )
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    csrf.init_app(app)
    socketio.init_app(app, cors_allowed_origins=app.config["CORS_ORIGINS"])

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    register_blueprints(app)

    # Реестр управляемых Minecraft-серверов — один ServerManager на каждую
    # строку Server в БД, создаются лениво (см. app/server_registry.py).
    # Несколько серверов под одной панелью — см. app/routes/servers.py.
    app.server_registry = ServerRegistry(app)

    with app.app_context():
        db.create_all()
        ensure_schema_migrations()
        ensure_first_admin(app.config["ADMIN_USERNAME"], app.config["ADMIN_PASSWORD"])

    @app.context_processor
    def inject_current_server():
        # g.server выставляется декоратором with_server (app/decorators.py) —
        # доступен в base.html для server-scoped навигации без того, чтобы
        # каждый роут явно прокидывал его в render_template.
        return {"current_server": getattr(g, "server", None)}

    @socketio.on('connect', namespace='/server')
    def handle_connect():
        print("Клиент подключился к WebSocket")

    @socketio.on('join', namespace='/server')
    def handle_join(data):
        # Живая консоль скоуплена по комнатам server-<id>, чтобы клиент видел
        # вывод только своего сервера, а не всех сразу (см. ServerManager.
        # get_console_output). Пускаем в комнату только залогиненных —
        # WebSocket-соединение несёт ту же Flask-сессию, что и обычные запросы.
        if not current_user.is_authenticated:
            return False
        server_id = data.get('server_id') if isinstance(data, dict) else None
        if server_id is None:
            return False
        join_room(f"server-{server_id}")

    return app
