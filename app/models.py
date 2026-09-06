"""
SQLAlchemy-модели. Раньше это были сырые sqlite3-запросы в stmc.py с
адресацией полей по индексу тюпла (user[0], user[2]...) — теперь нормальные
модели с полями по имени, и роль пользователя — часть схемы, а не что-то
навешанное сбоку.
"""
import re
import secrets

from flask_login import UserMixin
from werkzeug.security import generate_password_hash

from app.extensions import db

ROLE_ADMIN = "admin"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_ADMIN, ROLE_VIEWER)


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_VIEWER)

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN


class Server(db.Model):
    """
    Один управляемый Minecraft-сервер. Несколько строк здесь == несколько
    независимых инстансов под одной панелью (см. app/server_registry.py) —
    каждому соответствует своя ServerManager и своя папка servers/<slug>/.
    """
    __tablename__ = "servers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False)  # имя папки на диске
    java_xmx = db.Column(db.String(10), nullable=False, default="2G")
    java_xms = db.Column(db.String(10), nullable=False, default="1G")
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    # Публичная страница статуса (/status, без логина) — что видят игроки.
    # Не выводится автоматически из реального состояния сервера: название/
    # версия/IP admin вписывает вручную на странице «Ядро» и они могут не
    # совпадать с внутренним `name`/фактическим адресом. По умолчанию сервер
    # скрыт (public_visible=False) — новый/недонастроенный сервер не должен
    # случайно всплыть на публичной странице раньше времени.
    public_visible = db.Column(db.Boolean, nullable=False, default=False)
    public_name = db.Column(db.String(80), nullable=True)
    public_version = db.Column(db.String(60), nullable=True)
    public_ip = db.Column(db.String(120), nullable=True)
    public_description = db.Column(db.Text, nullable=True)
    public_contact = db.Column(db.String(255), nullable=True)  # ссылка на Discord/сайт/т.п. или просто текст

    # "Возраст" сервера для /status — момент самого ПЕРВОГО успешного старта
    # (когда впервые матчится "Done (", см. ServerManager._DONE_RE), не
    # текущий аптайм: рестарты/переустановки его не сдвигают. Отдельно от
    # created_at (тот — момент создания строки в панели, сервер может
    # простоять незапущенным сколько угодно после этого).
    first_started_at = db.Column(db.DateTime, nullable=True)


class ConsoleLine(db.Model):
    __tablename__ = "console_output"

    id = db.Column(db.Integer, primary_key=True)
    server_id = db.Column(db.Integer, db.ForeignKey("servers.id"), nullable=False, index=True)
    line = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    server = db.relationship("Server", backref=db.backref("console_lines", cascade="all, delete-orphan"))


class PlayerEvent(db.Model):
    """
    История входов/выходов игроков — отдельно от ServerManager.online
    (тот — только текущее состояние в памяти, живёт, пока жив процесс, и
    обнуляется при рестарте/падении сервера). Пишется из
    ServerManager.console_event_check при матче join/leave-строки — см.
    app/server_manager.py.
    """
    __tablename__ = "player_events"

    id = db.Column(db.Integer, primary_key=True)
    server_id = db.Column(db.Integer, db.ForeignKey("servers.id"), nullable=False, index=True)
    username = db.Column(db.String(16), nullable=False)
    event_type = db.Column(db.String(10), nullable=False)  # "join" | "leave"
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    server = db.relationship("Server", backref=db.backref("player_events", cascade="all, delete-orphan"))


class CommandHistory(db.Model):
    """
    История команд, реально отправленных в консоль сервера (не команды
    планировщика/жизненного цикла start/stop/kill/restart — только то, что
    ServerManager.send_command_direct шлёт в stdin процесса), с указанием,
    кто отправил. Заменяет собой прежнюю панель "Быстрые команды" на
    странице "Консоль" — см. app/routes/console.py/control_panel.html.
    Пишется рядом с ConsoleLine (та же команда попадает и туда — этот текст
    просто структурирован отдельно и с привязкой к user_id для истории/
    кликабельного повтора, а не для замены общего лога консоли).
    """
    __tablename__ = "command_history"

    id = db.Column(db.Integer, primary_key=True)
    server_id = db.Column(db.Integer, db.ForeignKey("servers.id"), nullable=False, index=True)
    # Nullable — команда не всегда приходит из живого HTTP-запроса
    # залогиненного юзера (напр. позже могло бы дёргаться из планировщика).
    username = db.Column(db.String(80), nullable=True)
    command = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    server = db.relationship("Server", backref=db.backref("command_history", cascade="all, delete-orphan"))


TASK_TYPES = ("backup", "restart", "stop", "start", "command")
SCHEDULE_KINDS = ("interval", "daily", "cron")


class ScheduledTask(db.Model):
    """
    Задача планировщика (app/scheduler.py) — авто-бекап/рестарт/стоп/старт/
    произвольная команда по расписанию. Сама таблица — источник правды;
    APScheduler в рантайме держит только производные от неё джобы в памяти
    и перечитывает эту таблицу заново при каждом изменении (см.
    TaskScheduler.sync_from_db) — так что тут никогда не может накопиться
    расхождение между тем, что видит admin в UI, и тем, что реально
    выполняется.
    """
    __tablename__ = "scheduled_tasks"

    id = db.Column(db.Integer, primary_key=True)
    server_id = db.Column(db.Integer, db.ForeignKey("servers.id"), nullable=False, index=True)
    server = db.relationship("Server", backref=db.backref("scheduled_tasks", cascade="all, delete-orphan"))

    type = db.Column(db.String(20), nullable=False)  # см. TASK_TYPES
    # Для type="command" — сам текст команды. Для type="backup" — префикс
    # имени бекапа (по умолчанию "auto"), тот же, что get_backups_list()
    # потом матчит при отборе на удаление по retention.
    payload = db.Column(db.String(255), nullable=True)
    # Сколько последних бекапов с этим префиксом хранить, старше — удаляются
    # после каждого успешного авто-бекапа. Только для type="backup".
    retention = db.Column(db.Integer, nullable=True)

    schedule_kind = db.Column(db.String(20), nullable=False)  # см. SCHEDULE_KINDS
    # interval → число часов ("6"); daily → "HH:MM"; cron → сырое cron-выражение.
    schedule_value = db.Column(db.String(100), nullable=False)

    enabled = db.Column(db.Boolean, nullable=False, default=True)
    last_run_at = db.Column(db.DateTime, nullable=True)
    last_run_status = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


def ensure_schema_migrations() -> None:
    """
    Нет Alembic/Flask-Migrate — db.create_all() создаёт только отсутствующие
    ТАБЛИЦЫ, а не колонки в уже существующих. Поэтому новые поля модели
    (напр. Server.first_started_at) сами по себе не появятся в уже
    развёрнутой БД. Не миграционный фреймворк, а тот же pragmatic-паттерн,
    что и config._load_or_create_secret_key() — тихий самовосстанавливающийся
    startup-код: смотрим, каких колонок не хватает, докидываем их через
    ALTER TABLE (SQLite это умеет дёшево). Вызывается из create_app() сразу
    после db.create_all().
    """
    inspector = db.inspect(db.engine)
    if "servers" not in inspector.get_table_names():
        return  # таблицы ещё нет — её создаст db.create_all(), колонки будут сразу
    existing = {col["name"] for col in inspector.get_columns("servers")}
    wanted = {
        "first_started_at": "DATETIME",
    }
    missing = {name: ddl for name, ddl in wanted.items() if name not in existing}
    if not missing:
        return
    with db.engine.begin() as conn:
        for name, ddl in missing.items():
            conn.execute(db.text(f"ALTER TABLE servers ADD COLUMN {name} {ddl}"))


def ensure_first_admin(username: str, password: str | None) -> None:
    """
    Создаёт первого администратора, только если в базе вообще нет ни одного
    пользователя — не пересоздаёт admin/<дефолтный пароль> при каждом
    рестарте, если пользователя удалили осознанно.
    """
    if User.query.count() > 0:
        return
    generated = password is None
    if generated:
        password = secrets.token_urlsafe(12)
    admin = User(username=username, password=generate_password_hash(password), role=ROLE_ADMIN)
    db.session.add(admin)
    db.session.commit()
    if generated:
        print("=" * 60)
        print(f" Создан первый администратор: {username}")
        print(f" Пароль (сохрани, больше нигде не показывается): {password}")
        print(" Смени пароль после первого входа.")
        print("=" * 60)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "server"


def create_server(name: str, java_xmx: str = "2G", java_xms: str = "1G") -> Server:
    """Создаёт Server со сгенерированным уникальным slug (используется как имя папки)."""
    base_slug = _slugify(name)
    slug = base_slug
    n = 2
    while Server.query.filter_by(slug=slug).first() is not None:
        slug = f"{base_slug}-{n}"
        n += 1
    server = Server(name=name.strip() or slug, slug=slug, java_xmx=java_xmx, java_xms=java_xms)
    db.session.add(server)
    db.session.commit()
    return server
