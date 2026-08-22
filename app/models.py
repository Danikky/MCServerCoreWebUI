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


class ConsoleLine(db.Model):
    __tablename__ = "console_output"

    id = db.Column(db.Integer, primary_key=True)
    server_id = db.Column(db.Integer, db.ForeignKey("servers.id"), nullable=False, index=True)
    line = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


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
