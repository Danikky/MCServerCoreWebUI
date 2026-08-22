"""
Вся конфигурация приложения — в одном месте, читается из окружения (.env
подхватывается автоматически, если установлен python-dotenv). Раньше эти
настройки были раскиданы константами по main.py.
"""
import os
import secrets

from app.fs_utils import return_main_dir


def _load_or_create_secret_key() -> str:
    """
    SECRET_KEY: из окружения, если задан; иначе генерируется один раз и
    сохраняется в .flask_secret_key (в .gitignore) — чтобы не хардкодить
    секрет в исходниках и не терять сессии при каждом рестарте.
    """
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    key_file = os.path.join(return_main_dir(), ".flask_secret_key")
    if os.path.exists(key_file):
        with open(key_file, "r") as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(key_file, "w") as f:
        f.write(key)
    return key


class Config:
    SECRET_KEY = _load_or_create_secret_key()
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(return_main_dir(), "DataBase.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    DEBUG = os.environ.get("MCSC_DEBUG", "0") == "1"
    HOST = os.environ.get("MCSC_HOST", "0.0.0.0")
    PORT = int(os.environ.get("MCSC_PORT", "5245"))

    # Публичная регистрация выключена по умолчанию — без неё все аккаунты
    # заводятся вручную (см. app.models.ensure_first_admin), что не даёт
    # анонимам самим себя зарегистрировать с полным доступом.
    ALLOW_REGISTRATION = os.environ.get("ALLOW_REGISTRATION", "0") == "1"

    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")  # None -> сгенерировать случайный

    CORS_ORIGINS = os.environ.get("MCSC_CORS_ORIGINS", "*")

    # Дефолты для памяти JVM у новых серверов (каждый Server хранит свои
    # java_xmx/java_xms в БД — эти значения используются только при создании).
    JAVA_XMX = os.environ.get("MCSC_JAVA_XMX", "2G")
    JAVA_XMS = os.environ.get("MCSC_JAVA_XMS", "1G")

    # Лимит на загрузку файлов (в первую очередь — ядро сервера через
    # /servers/<id>/core/upload). Werkzeug сам отдаёт 413, если превышено.
    MAX_CONTENT_LENGTH = int(os.environ.get("MCSC_MAX_UPLOAD_MB", "1024")) * 1024 * 1024
