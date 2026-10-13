"""
ClientPack — клиентская сборка сервера для автоустановщика под TLauncher
(.bat, см. app/installer_template.ps1 и app/routes/clientpack.py).

Admin загружает на странице «Ядро» три вещи: установщик загрузчика
(Forge/NeoForge installer .jar), моды (.jar по одному) и overrides.zip
(config/, resourcepacks/, shaderpacks/ и т.п.). Всё лежит в
client_packs/<slug>/ — НЕ внутри servers/<slug>/, чтобы гигабайт клиентских
модов не попадал в бекапы сервера и не мешался с его собственной mods/.

Панель ничего не пересобирает в общий архив: установщик у игрока качает
manifest.json и сам докачивает только те моды, которых у него нет (сверка по
sha1) — поэтому обновление сборки не заставляет всех перекачивать её целиком.
meta.json — кэш размеров/хэшей, чтобы не хэшировать гигабайт на каждый запрос
манифеста. Чистая файловая логика, без Flask/БД.
"""
import hashlib
import json
import os
import re
import shutil
import threading
import zipfile

from werkzeug.utils import secure_filename

from app import fs_utils

PACKS_DIR = "client_packs"

# Имя сборки становится именем папки versions/<имя>/ на Windows и попадает в
# JVM-аргумент NeoForge "-DignoreList=...,${version_name}.jar" (список через
# запятую) — поэтому кроме запрещённых в путях Windows символов режем запятую.
_BAD_NAME_CHARS = re.compile(r'[\\/:*?"<>|,\x00-\x1f]')
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
MAX_NAME_LEN = 60

# meta.json читается-меняется-пишется из параллельных запросов (моды грузятся
# по одному файлу на запрос) — один лок на все сборки, операции короткие.
_meta_lock = threading.Lock()


class ClientPackError(ValueError):
    """Ошибка с текстом для admin'а (некорректный файл/имя)."""


def clean_name(raw: str) -> str:
    name = _BAD_NAME_CHARS.sub("", raw or "").strip().rstrip(". ")
    name = re.sub(r"\s+", " ", name)[:MAX_NAME_LEN].rstrip(". ")
    if not name:
        raise ClientPackError("Название сборки пустое или состоит из недопустимых символов")
    if name.split(".")[0].upper() in _RESERVED_NAMES:
        raise ClientPackError(f"«{name}» — зарезервированное имя в Windows, выбери другое")
    return name


def _sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class ClientPack:
    def __init__(self, slug: str):
        self.root = os.path.join(fs_utils.return_main_dir(), PACKS_DIR, slug)
        self.mods_dir = os.path.join(self.root, "mods")
        self.installer_path = os.path.join(self.root, "installer.jar")
        self.overrides_path = os.path.join(self.root, "overrides.zip")
        self._version_json_path = os.path.join(self.root, "version.json")
        self._meta_path = os.path.join(self.root, "meta.json")

    # ---- meta.json -----------------------------------------------------------

    @property
    def meta(self) -> dict:
        meta = {"name": None, "loader": None, "installer": None, "mods": {}, "overrides": None,
                "show_on_status": False}
        try:
            with open(self._meta_path, "r", encoding="utf-8") as f:
                meta.update(json.load(f))
        except (OSError, ValueError):
            pass
        return meta

    def _update_meta(self, mutate) -> None:
        with _meta_lock:
            meta = self.meta
            mutate(meta)
            os.makedirs(self.root, exist_ok=True)
            tmp = self._meta_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self._meta_path)

    @property
    def ready(self) -> bool:
        """Установщик можно отдавать игрокам: есть имя и загрузчик. Моды и
        overrides необязательны (сборка может быть и из одних конфигов)."""
        meta = self.meta
        return bool(meta["name"] and meta["loader"] and os.path.isfile(self.installer_path))

    def set_show_on_status(self, show: bool) -> None:
        """Кнопка установщика на публичной /status. По умолчанию выключена,
        как и всё публичное в панели; сама ссылка на .bat работает и без неё."""
        self._update_meta(lambda m: m.update(show_on_status=bool(show)))

    def set_name(self, raw: str) -> str:
        name = clean_name(raw)
        self._update_meta(lambda m: m.update(name=name))
        return name

    # ---- установщик загрузчика (Forge/NeoForge installer .jar) ---------------

    def save_installer(self, file_storage) -> dict:
        """
        Из установщика берём две вещи: какой версии Minecraft и какой
        загрузчик он ставит (install_profile.json) и готовый JSON версии
        (version.json) — его же установщик кладёт в versions/<id>/ у игрока.
        Версия сборки для TLauncher — этот самый JSON с подменённым "id", так
        что структура ровно та, с которой лаунчер и так умеет работать.
        """
        os.makedirs(self.root, exist_ok=True)
        tmp = self.installer_path + ".part"
        file_storage.save(tmp)
        try:
            if not zipfile.is_zipfile(tmp):
                raise ClientPackError("Это не .jar — нужен установщик Forge или NeoForge (…-installer.jar)")
            with zipfile.ZipFile(tmp) as zf:
                try:
                    profile = json.loads(zf.read("install_profile.json"))
                except (KeyError, ValueError):
                    raise ClientPackError(
                        "В .jar нет install_profile.json — это не установщик Forge/NeoForge "
                        "(Fabric и Quilt пока не поддерживаются)")
                if "spec" not in profile or not profile.get("version") or not profile.get("json"):
                    raise ClientPackError(
                        "Слишком старый установщик Forge (без режима --installClient) — "
                        "поддерживаются установщики для Minecraft 1.13+ и поздние сборки для 1.12.2")
                try:
                    version_json = json.loads(zf.read(profile["json"].lstrip("/")))
                except (KeyError, ValueError):
                    raise ClientPackError("В установщике не найден JSON версии — файл повреждён?")
            loader = {
                "id": version_json.get("id") or profile["version"],
                "minecraft": profile.get("minecraft") or version_json.get("inheritsFrom"),
                "profile": profile.get("profile"),
            }
            with open(self._version_json_path, "w", encoding="utf-8") as f:
                json.dump(version_json, f, ensure_ascii=False)
            info = {"size": os.path.getsize(tmp), "sha1": _sha1(tmp)}
            os.replace(tmp, self.installer_path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        self._update_meta(lambda m: m.update(loader=loader, installer=info))
        return loader

    def delete_installer(self) -> None:
        for path in (self.installer_path, self._version_json_path):
            if os.path.exists(path):
                os.remove(path)
        self._update_meta(lambda m: m.update(loader=None, installer=None))

    def version_json_text(self) -> str:
        """JSON версии для versions/<имя сборки>/<имя сборки>.json у игрока."""
        with open(self._version_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["id"] = self.meta["name"]
        return json.dumps(data, ensure_ascii=False)

    # ---- моды ----------------------------------------------------------------

    def save_mod(self, file_storage) -> str:
        name = secure_filename(file_storage.filename or "")
        if not name.lower().endswith(".jar"):
            raise ClientPackError("Моды — только файлы .jar")
        os.makedirs(self.mods_dir, exist_ok=True)
        target = fs_utils.safe_join(self.mods_dir, os.path.join(self.mods_dir, name))
        tmp = target + ".part"
        file_storage.save(tmp)
        info = {"size": os.path.getsize(tmp), "sha1": _sha1(tmp)}
        os.replace(tmp, target)
        self._update_meta(lambda m: m["mods"].__setitem__(name, info))
        return name

    def delete_mod(self, name: str) -> None:
        name = os.path.basename(name)
        path = fs_utils.safe_join(self.mods_dir, os.path.join(self.mods_dir, name))
        if os.path.isfile(path):
            os.remove(path)
        self._update_meta(lambda m: m["mods"].pop(name, None))

    def clear_mods(self) -> None:
        if os.path.isdir(self.mods_dir):
            shutil.rmtree(self.mods_dir)
        self._update_meta(lambda m: m.update(mods={}))

    # ---- overrides.zip -------------------------------------------------------

    def save_overrides(self, file_storage) -> dict:
        """
        Архив хранится как есть и распаковывается уже у игрока — панели
        незачем держать у себя тысячи файлов шейдеров. Здесь только проверка,
        что это zip без путей наружу ("../", абсолютные), и определение
        обёртки overrides/ (так пакует CurseForge) — установщик её снимет.
        """
        os.makedirs(self.root, exist_ok=True)
        tmp = self.overrides_path + ".part"
        file_storage.save(tmp)
        try:
            if not zipfile.is_zipfile(tmp):
                raise ClientPackError("overrides — нужен .zip-архив")
            with zipfile.ZipFile(tmp) as zf:
                names = [n.replace("\\", "/") for n in zf.namelist()]
            files = [n for n in names if n and not n.endswith("/")]
            if not files:
                raise ClientPackError("Архив overrides пустой")
            for n in files:
                if n.startswith("/") or ".." in n.split("/") or re.match(r"^[A-Za-z]:", n):
                    raise ClientPackError(f"В архиве путь, ведущий наружу: {n}")
            # Есть папка overrides/ — берём только её содержимое. Это и архив
            # «папка overrides целиком», и сам zip сборки с CurseForge, где
            # рядом лежат manifest.json/modlist.html (их установщик пропустит).
            inside = [n for n in files if n.lower().startswith("overrides/")]
            info = {
                "size": os.path.getsize(tmp),
                "sha1": _sha1(tmp),
                "prefix": inside[0][:len("overrides/")] if inside else "",
                "files": len(inside) if inside else len(files),
            }
            os.replace(tmp, self.overrides_path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        self._update_meta(lambda m: m.update(overrides=info))
        return info

    def delete_overrides(self) -> None:
        if os.path.exists(self.overrides_path):
            os.remove(self.overrides_path)
        self._update_meta(lambda m: m.update(overrides=None))

    # ---- .bat ----------------------------------------------------------------

    def render_installer_bat(self, pack_url: str) -> bytes:
        """
        .bat-обёртка + PowerShell-скрипт одним файлом. В сам файл зашит только
        адрес сборки на панели — всё остальное (имя, загрузчик, список модов)
        скрипт каждый раз берёт из manifest.json, поэтому однажды скачанный
        .bat годится и для обновления сборки. Шапка — чистый ASCII (cmd читает
        её в OEM-кодировке), остальное PowerShell читает как UTF-8; переводы
        строк CRLF — с LF cmd может споткнуться.
        """
        template_path = os.path.join(os.path.dirname(__file__), "installer_template.ps1")
        with open(template_path, "r", encoding="utf-8") as f:
            script = f.read()
        script = script.replace("__PACK_URL__", pack_url.replace("'", "''"))
        header = (
            "@echo off\n"
            'set "MCSC_SELF=%~f0"\n'
            'set "MCSC_GAMEDIR=%~1"\n'
            "powershell -NoProfile -ExecutionPolicy Bypass -Command "
            '"$s=[IO.File]::ReadAllText($env:MCSC_SELF,[Text.Encoding]::UTF8); '
            "iex $s.Substring($s.IndexOf('#PS'+'BEGIN'))\"\n"
            "echo.\n"
            "pause\n"
            "exit /b\n"
        )
        return (header + script).replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
