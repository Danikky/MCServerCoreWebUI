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

    # Для лаунчера (app/routes/launcher.py) — машиночитаемые, в отличие от
    # public_*, которые человек может вписать в свободной форме. mc_version
    # пуст, пока admin не впишет явно — сервер без него не попадает в
    # /launcher/servers (см. launcher.py). modloader/modloader_version —
    # задел на будущее (синхронизация модов), пока не редактируются в UI и
    # нигде не используются, кроме как отдаются в манифесте как есть.
    mc_version = db.Column(db.String(20), nullable=True)
    modloader = db.Column(db.String(20), nullable=False, default="vanilla")
    modloader_version = db.Column(db.String(20), nullable=True)


class ConsoleLine(db.Model):
    __tablename__ = "console_output"

    id = db.Column(db.Integer, primary_key=True)
    server_id = db.Column(db.Integer, db.ForeignKey("servers.id"), nullable=False, index=True)
    line = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


def ensure_schema_migrations() -> None:
    """
    В проекте нет Alembic/Flask-Migrate — db.create_all() создаёт только
    отсутствующие ТАБЛИЦЫ, а не колонки в уже существующих. Поэтому новые
    поля модели (напр. mc_version/modloader/modloader_version у Server)
    сами по себе не появятся в уже развёрнутой БД. Это не миграционный
    фреймворк, а тот же pragmatic-паттерн, что и
    config._load_or_create_secret_key() — тихий самовосстанавливающийся
    startup-код: смотрим, каких колонок не хватает, докидываем их через
    ALTER TABLE (SQLite это умеет дёшево). Вызывается из create_app() сразу
    после db.create_all().
    """
    inspector = db.inspect(db.engine)
    if "servers" not in inspector.get_table_names():
        return  # таблицы ещё нет — её создаст db.create_all(), колонки будут сразу
    existing = {col["name"] for col in inspector.get_columns("servers")}
    wanted = {
        "mc_version": "VARCHAR(20)",
        "modloader": "VARCHAR(20) NOT NULL DEFAULT 'vanilla'",
        "modloader_version": "VARCHAR(20)",
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
