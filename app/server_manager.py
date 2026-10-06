"""
ServerManager — управление процессом ОДНОГО Minecraft-сервера (запуск/стоп/
kill, чтение консоли, отправка команд) и файлами внутри его рабочей папки
(server.properties, бекапы, whitelist/ops/bans, ядро). Ни один путь,
приходящий из HTTP-слоя, сюда не должен попадать без предварительной
проверки через fs_utils.safe_join — см. блюпринты в app/routes/.

Каждому Server (app/models.py) соответствует один инстанс ServerManager,
живущий в app/server_registry.py — так поддерживается несколько независимых
серверов под одной панелью.
"""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from werkzeug.utils import secure_filename

from app import fs_utils
from app.extensions import db, socketio
from app.models import ConsoleLine, PlayerEvent, Server


class ServerManager:
    # Стандартный ванильный формат строки лога: "<имя> joined the game" /
    # "<имя> left the game". Матчим именно эти паттерны, а не подстроки
    # "join"/"left" где угодно в строке (это ловило чат, логи плагинов и т.п.).
    _JOIN_RE = re.compile(r"(\S+) joined the game")
    _LEFT_RE = re.compile(r"(\S+) left the game")
    # "Done (12.345s)! For help, type "help"" — печатает vanilla/Paper/Purpur/
    # Spigot/Fabric, когда мир загружен и сервер готов принимать игроков.
    # До этой строки процесс уже жив (is_server_running()==True), но это ещё
    # не "работает" с точки зрения игрока — отсюда отдельный статус "starting".
    _DONE_RE = re.compile(r"Done \(")

    MAX_CORE_BYTES = 1024 * 1024 * 1024  # 1 GB — щедро, но не безгранично
    # Лимит на суммарный размер распакованной сборки — защита от zip-бомбы
    # (сам архив ограничен MAX_CORE_BYTES при скачивании).
    MAX_MODPACK_UNPACKED_BYTES = 8 * 1024 * 1024 * 1024

    def __init__(self, app, server_row):
        self.app = app  # нужен для app_context() при обращениях к БД из фонового потока
        self.id = server_row.id
        self.name = server_row.name
        self.slug = server_row.slug
        self.java_xmx = server_row.java_xmx
        self.java_xms = server_row.java_xms
        self.core = None
        self.start_file = None
        self.online = []
        self.online_lock = threading.Lock()  # self.online читается/пишется из разных потоков
        self.process = None
        self.ready = False  # True после строки "Done (...)" — сервер реально принимает игроков
        self._restarting = False  # см. restart_server()/status
        self.path = os.path.join(fs_utils.return_main_dir(), "servers", self.slug)
        os.makedirs(self.path, exist_ok=True)

    @property
    def status(self) -> str:
        """offline / starting / running / restarting — единый статус для
        админ-панели и публичной страницы (/status)."""
        if self._restarting:
            return "restarting"
        if not self.is_server_running():
            return "offline"
        return "running" if self.ready else "starting"

    # ---- лог консоли (БД) --------------------------------------------------

    def _log(self, line: str) -> int:
        """Возвращает id созданной строки — нужен, чтобы прокинуть его вместе
        со строкой в live-обновление по сокету (см. get_console_output),
        иначе фронту нечем сопоставлять живые строки с пагинацией истории
        (/servers/<id>/console/history?before_id=...)."""
        print(f"[{self.slug}] {line}")
        with self.app.app_context():
            entry = ConsoleLine(server_id=self.id, line=line)
            db.session.add(entry)
            db.session.commit()
            return entry.id

    # ---- управление процессом -----------------------------------------------

    def _detect_core(self):
        """Самый свежий (по mtime) .jar в папке сервера — на случай, если там
        накопилось несколько версий ядра после переустановки."""
        jars = [f for f in os.listdir(self.path) if f.lower().endswith(".jar")]
        if not jars:
            return None
        jars.sort(key=lambda f: os.path.getmtime(os.path.join(self.path, f)), reverse=True)
        return jars[0]

    def start_server(self):
        self.core = self._detect_core()
        if self.core:
            print(f"{self.core} обнаружено")
        else:
            # Только .sh — запускаем всегда через bash (см. arg ниже), .bat
            # им в принципе не исполнить (это баг, а не кроссплатформенность:
            # ветки для cmd/.bat здесь никогда не было). os.listdir() не
            # гарантирует порядок — sorted() для детерминизма, если вдруг
            # окажется несколько .sh-файлов сразу.
            scripts = sorted(f for f in os.listdir(self.path) if f.lower().endswith(".sh"))
            if scripts:
                self.start_file = scripts[0]
                print(f"Обнаружен файл запуска: {self.start_file}")
                self._log(f"Обнаружен файл запуска: {self.start_file}")

        arg = ["java", "-Dsun.stdout.encoding=UTF-8", f"-Xmx{self.java_xmx}",
               f"-Xms{self.java_xms}", "-jar", self.core, "nogui"]
        if self.start_file:
            arg = ["bash", self.start_file]

        with self.online_lock:
            self.online = []
        self.ready = False

        self.process = subprocess.Popen(  # Xmx - максимальный, Xms - стартовый
            args=arg,
            cwd=self.path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=0,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace",
        )
        self.reader_thread = threading.Thread(target=self.get_console_output, daemon=True)
        self.reader_thread.start()

    def get_console_output(self):
        while True:
            line = self.process.stdout.readline()
            if not line and self.process.poll() is not None:
                break
            if line:
                line_id = self._log(line)
                self.console_event_check(line)
                socketio.start_background_task(
                    socketio.emit, 'console_update', {'id': line_id, 'line': line.strip()},
                    namespace='/server', room=f"server-{self.id}",
                )

    def send_command_direct(self, command: str) -> str:
        if not self.process or self.process.poll() is not None:
            return "Сервер не запущен"
        try:
            self._log(f"[{time.ctime()} USER]> {command}")
            self.process.stdin.write(command + '\n')
            self.process.stdin.flush()
            time.sleep(0.1)
        except Exception as e:
            self._log(f"Ошибка отправки команды: {e}")
            return f"Ошибка отправки команды: {e}"

    def console_event_check(self, line: str):
        if "You need to agree to the EULA in order to run the server" in line:
            self._restarting = True
            fs_utils.agree_eula(self.path)
            self.kill_server()
            time.sleep(3)
            self.start_server()
            return
        if self._DONE_RE.search(line):
            self.ready = True
            self._restarting = False
            self._record_first_start()
            return
        join_match = self._JOIN_RE.search(line)
        left_match = self._LEFT_RE.search(line)
        if join_match:
            name = join_match.group(1)
            with self.online_lock:
                if name not in self.online:
                    self.online.append(name)
            self._log_player_event(name, "join")
        elif left_match:
            name = left_match.group(1)
            with self.online_lock:
                if name in self.online:
                    self.online.remove(name)
            self._log_player_event(name, "leave")

    def _log_player_event(self, username: str, event_type: str) -> None:
        """Персистентная история входов/выходов — в отличие от self.online
        (только текущее состояние в памяти, сбрасывается при рестарте/
        падении), переживает и рестарт сервера, и офлайн-полностью. Видна
        на странице «Игроки» вне зависимости от того, жив ли сейчас
        процесс — см. app/routes/players.py."""
        with self.app.app_context():
            db.session.add(PlayerEvent(server_id=self.id, username=username, event_type=event_type))
            db.session.commit()

    def _record_first_start(self) -> None:
        """Пишет Server.first_started_at один раз — при самом первом
        успешном старте за всю историю сервера (первый матч "Done (", см.
        _DONE_RE). Дальше не трогается: рестарты/переустановки ядра не
        сдвигают эту дату — это "возраст" сервера для /status, а не
        текущий аптайм сессии."""
        with self.app.app_context():
            row = db.session.get(Server, self.id)
            if row is not None and row.first_started_at is None:
                row.first_started_at = dt.datetime.utcnow()
                db.session.commit()

    def is_server_running(self) -> bool:
        # Проверяем именно наш управляемый субпроцесс, а не любой java-процесс
        # в системе (иначе панель врёт о статусе рядом с другими Java-приложениями).
        return self.process is not None and self.process.poll() is None

    def kill_server(self):
        self.process.terminate()
        time.sleep(1)
        if self.process.poll() is None:
            self.process.kill()

    def restart_server(self):
        """Мягкий стоп (с ожиданием, иначе kill) + повторный старт, в фоновом
        потоке — чтобы не держать HTTP-запрос открытым, пока JVM гасится и
        поднимается заново. Статус всё это время — "restarting" (см. status)."""
        if self._restarting:
            return  # уже перезапускается, повторный клик — no-op
        self._restarting = True
        threading.Thread(target=self._do_restart, daemon=True).start()

    def _do_restart(self):
        try:
            if self.is_server_running():
                self.send_command_direct("stop")
                deadline = time.time() + 30
                while self.is_server_running() and time.time() < deadline:
                    time.sleep(0.5)
                if self.is_server_running():
                    self.kill_server()
            self.start_server()  # сам не блокирует — только поднимает процесс и поток чтения
        except Exception as e:
            self._log(f"Ошибка при рестарте: {e}")
            self._restarting = False

    # ---- ядро сервера (.jar) — загрузка файлом или по ссылке -----------------

    def list_core_files(self):
        if not os.path.isdir(self.path):
            return []
        jars = [f for f in os.listdir(self.path) if f.lower().endswith(".jar")]
        jars.sort(key=lambda f: os.path.getmtime(os.path.join(self.path, f)), reverse=True)
        return jars

    def save_uploaded_core(self, file_storage) -> str:
        """file_storage — werkzeug FileStorage из request.files."""
        filename = secure_filename(file_storage.filename or "")
        if not filename or not filename.lower().endswith(".jar"):
            raise ValueError("Ожидается файл с расширением .jar")
        os.makedirs(self.path, exist_ok=True)
        target = fs_utils.safe_join(self.path, os.path.join(self.path, filename))
        file_storage.save(target)
        return filename

    def fetch_core_from_url(self, url: str, filename: str | None = None) -> str:
        """
        Качает ядро по прямой ссылке (сборка Paper/Purpur/Fabric и т.п.) и
        сохраняет .jar в папку сервера. Доступно только admin — ссылка
        считается доверенным вводом (полноценной защиты от SSRF здесь нет:
        тот, кто может сюда написать, и так может исполнять произвольные
        команды в консоли — см. REVIEW.md).
        """
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("Разрешены только http/https ссылки")
        name = secure_filename(filename or os.path.basename(parsed.path) or "server.jar")
        if not name.lower().endswith(".jar"):
            name += ".jar"
        os.makedirs(self.path, exist_ok=True)
        target = fs_utils.safe_join(self.path, os.path.join(self.path, name))
        tmp_target = target + ".part"
        self._download(url, tmp_target)
        os.replace(tmp_target, target)
        return name

    def _download(self, url: str, target: str) -> None:
        """Потоково качает url в target с лимитом MAX_CORE_BYTES. При ошибке
        недокачанный файл удаляется. Схему (http/https) проверяет вызывающий."""
        req = urllib.request.Request(url, headers={"User-Agent": "MCServerCore/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                content_length = resp.headers.get("Content-Length")
                if content_length and int(content_length) > self.MAX_CORE_BYTES:
                    raise ValueError("Файл слишком большой (>1 GB)")
                written = 0
                with open(target, "wb") as f:
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > self.MAX_CORE_BYTES:
                            raise ValueError("Файл слишком большой (>1 GB)")
                        f.write(chunk)
        except (urllib.error.URLError, TimeoutError, ValueError):
            if os.path.exists(target):
                os.remove(target)
            raise

    # ---- сборка модов (серверный .zip-пак) -----------------------------------

    def install_modpack(self, url: str, clean_mods: bool = True) -> int:
        """
        Качает серверную сборку (.zip — «Server Pack» с CurseForge и т.п.:
        mods/, config/, скрипт запуска/ядро) и распаковывает её поверх папки
        сервера. Возвращает число распакованных файлов. Мир, бекапы и прочие
        файлы, которых нет в архиве, не трогаются; с clean_mods=True старая
        папка mods/ удаляется перед распаковкой, если в архиве есть своя —
        иначе при обновлении сборки остаются моды старых версий и сервер
        падает на дубликатах. Тот же уровень доверия к ссылке, что и у
        fetch_core_from_url (admin-only, без защиты от SSRF).
        """
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("Разрешены только http/https ссылки")
        if self.is_server_running():
            raise ValueError("Сначала останови сервер")
        os.makedirs(self.path, exist_ok=True)
        tmp_zip = os.path.join(self.path, ".modpack-download.part")
        self._download(url, tmp_zip)
        try:
            if not zipfile.is_zipfile(tmp_zip):
                raise ValueError("По ссылке не .zip-архив — нужна серверная сборка (Server Pack)")
            with zipfile.ZipFile(tmp_zip) as zf:
                return self._extract_modpack(zf, clean_mods)
        finally:
            if os.path.exists(tmp_zip):
                os.remove(tmp_zip)

    def _extract_modpack(self, zf: zipfile.ZipFile, clean_mods: bool) -> int:
        names = zf.namelist()
        if "modrinth.index.json" in names:
            # .mrpack — тоже zip, но внутри не файлы сервера, а манифест со
            # ссылками на моды; распаковать его как есть — получить мусор.
            raise ValueError(".mrpack (Modrinth) не поддерживается — нужен серверный .zip-пак")

        members = [i for i in zf.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX/")]
        if not members:
            raise ValueError("Архив пустой")
        if sum(i.file_size for i in members) > self.MAX_MODPACK_UNPACKED_BYTES:
            raise ValueError("Распакованная сборка слишком большая (>8 GB)")

        # Многие паки завёрнуты в одну папку верхнего уровня
        # ("MyPack-Server-1.2/mods/...") — снимаем её, чтобы mods/ и ядро
        # оказались прямо в папке сервера, где их ищет start_server().
        prefix = ""
        tops = {i.filename.split("/", 1)[0] for i in members}
        if len(tops) == 1 and all("/" in i.filename for i in members):
            prefix = tops.pop() + "/"

        # Сначала проверяем ВСЕ пути (zip-slip: "../", абсолютные пути), и
        # только потом пишем — чтобы битый архив не оставил полураспакованную
        # сборку. backups/ панели архиву не перезаписать.
        plan = []
        for info in members:
            rel = info.filename[len(prefix):]
            if not rel or rel.split("/", 1)[0] == "backups":
                continue
            plan.append((info, fs_utils.safe_join(self.path, os.path.join(self.path, rel))))

        if clean_mods and any(info.filename[len(prefix):].startswith("mods/") for info, _ in plan):
            mods_dir = os.path.join(self.path, "mods")
            if os.path.isdir(mods_dir):
                shutil.rmtree(mods_dir)

        for info, dest in plan:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
        return len(plan)

    def delete_core_file(self, filename: str):
        fs_utils.delete(self.path, os.path.join(self.path, os.path.basename(filename)))

    # ---- server.properties ---------------------------------------------------

    def get_properties_data(self):
        result = []
        properties_path = os.path.join(self.path, "server.properties")
        try:
            with open(properties_path, 'r', encoding='utf-8') as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped or stripped[0] in ('#', '!'):
                        continue
                    if '=' in stripped:
                        key, value = stripped.split('=', 1)
                        result.append([key.strip(), value.strip()])
        except OSError:
            result = None
        return result

    def update_properties(self, key, value):
        updated = False
        new_lines = []
        properties_path = os.path.join(self.path, "server.properties")
        with open(properties_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip().startswith(('#', '!')) or len(line.strip()) == 0:
                    new_lines.append(line)
                    continue
                if '=' in line:
                    key_part, value_part = line.split('=', 1)
                    if key_part.strip() == key:
                        new_lines.append(f"{key}={value}\n")
                        updated = True
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)
        if not updated:
            raise ValueError(f"Ключ '{key}' не найден в файле")
        with open(properties_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        return True

    def get_properties_value(self, key):
        properties_path = os.path.join(self.path, "server.properties")
        try:
            with open(properties_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if '=' in line:
                        current_key, value = line.split('=', 1)
                        if current_key.strip() == key:
                            return value
        except OSError:
            return None

    def get_properties_bool(self, key: str) -> bool | None:
        """True/False по строковому значению свойства ("true"/"false",
        как обычно пишет сама Minecraft) — None, если свойства нет вовсе
        или server.properties ещё не создан (сервер ни разу не стартовал)."""
        raw = self.get_properties_value(key)
        if raw is None:
            return None
        value = raw.strip().lower()
        if value == "true":
            return True
        if value == "false":
            return False
        return None

    # ---- команды над конкретным игроком (op/deop/kick/ban/pardon/...) --------

    # Что проверять после каждой команды, чтобы понять — правда применилась
    # или нет — вместо того чтобы слепо ждать фиксированное время и сразу
    # показывать (возможно ещё не обновившиеся) данные. Ключ — ровно то, что
    # приходит в поле "command" из формы (см. server_players.html).
    _PLAYER_COMMANDS = {
        "op": lambda self, u: u in [x["name"] for x in self.get_json("ops.json")],
        "deop": lambda self, u: u not in [x["name"] for x in self.get_json("ops.json")],
        "ban": lambda self, u: u in [x["name"] for x in self.get_json("banned-players.json")],
        "pardon": lambda self, u: u not in [x["name"] for x in self.get_json("banned-players.json")],
        "whitelist remove": lambda self, u: u not in [x["name"] for x in self.get_json("whitelist.json")],
        "kick": lambda self, u: u not in self.online,
    }

    def run_player_command(self, command: str, username: str, timeout: float = 1.5) -> tuple[bool, str]:
        """
        Отправляет "<command> <username>" в консоль и по возможности реально
        дожидается подтверждения (перечитывая ops.json/banned-players.json/
        whitelist.json или self.online — смотря что команда должна поменять),
        а не спит вслепую 0.1с, как раньше. Возвращает (confirmed, message)
        для flash-сообщения — раньше результат вообще никак не показывался.

        Вызывающий код (app/routes/players.py) обязан сам проверить, что
        command — из разрешённого списка, а username — похож на настоящий
        ник Minecraft, ДО вызова этого метода: здесь предполагается, что оба
        уже безопасны для подстановки в команду консоли.
        """
        if not self.is_server_running():
            return False, "сервер не запущен"

        check = self._PLAYER_COMMANDS.get(command)
        self.send_command_direct(f"{command} {username}")

        if check is None:
            return True, "команда отправлена"

        deadline = time.time() + timeout
        while time.time() < deadline:
            if check(self, username):
                return True, "готово"
            time.sleep(0.1)
        return False, "команда отправлена, но подтверждение не пришло вовремя — обнови страницу"

    # ---- игроки (whitelist/ops/bans/usercache) --------------------------------

    def get_json(self, json_file, default=None):
        # banned-ips.json / banned-players.json / ops.json / usercache.json /
        # whitelist.json — ядро сервера создаёт их лениво (например,
        # usercache.json — только после первого захода игрока), так что их
        # отсутствие на свежем сервере — нормальная ситуация, а не ошибка.
        if default is None:
            default = []
        path = os.path.join(self.path, json_file)
        try:
            with open(path, 'r', encoding='utf-8') as file:
                return json.load(file)
        except FileNotFoundError:
            return default
        except (json.JSONDecodeError, OSError) as e:
            print(f"Ошибка при чтении {json_file}: {e}")
            return default

    def update_players_data(self):
        return {
            "usercaсhe": list(self.get_json("usercache.json")),
            "whitelist": [x["name"] for x in self.get_json("whitelist.json")],
            "oplist": [x["name"] for x in self.get_json("ops.json")],
            "banlist": [x["name"] for x in self.get_json("banned-players.json")],
            "online": self.online,
        }

    # ---- бекапы --------------------------------------------------------------

    def get_backups_list(self):
        backups_dir = os.path.join(self.path, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        return fs_utils.get_dir(backups_dir, backups_dir)

    def create_backup(self, name):
        # name приходит из формы — не доверяем ему как части пути, только как
        # имени файла: убираем разделители пути, чтобы нельзя было выйти за
        # пределы backups/ через "../".
        safe_name = os.path.basename(name).strip() or "backup"
        date = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backups_dir = os.path.join(self.path, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        target = fs_utils.safe_join(backups_dir, os.path.join(backups_dir, f"{safe_name}-{date}"))
        # backups_dir лежит внутри self.path — если не исключить его явно,
        # copytree попытается скопировать создаваемую папку бэкапа саму в
        # себя (рекурсивно) и упадёт с shutil.Error.
        fs_utils.clone_dir(self.path, target, ignore=shutil.ignore_patterns("backups"))

    def delete_backup(self, name):
        backups_dir = os.path.join(self.path, "backups")
        fs_utils.delete(backups_dir, os.path.join(backups_dir, os.path.basename(name)))

    def rename_backup(self, name, new_name):
        backups_dir = os.path.join(self.path, "backups")
        fs_utils.rename(backups_dir, os.path.join(backups_dir, os.path.basename(name)), os.path.basename(new_name))
