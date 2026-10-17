"""
ClientPack — клиентская сборка сервера для автоустановщика под TLauncher
(.bat, см. app/installer_template.ps1 и app/routes/clientpack.py).

Admin загружает на странице «Ядро» три вещи: установщик загрузчика
(Forge/NeoForge installer .jar), моды (.jar по одному) и overrides.zip
(config/, resourcepacks/, shaderpacks/ и т.п.). Всё лежит в
client_packs/<slug>/ — НЕ внутри servers/<slug>/, чтобы гигабайт клиентских
модов не попадал в бекапы сервера и не мешался с его собственной mods/.

Моды в общий архив не пересобираются: установщик у игрока качает
manifest.json и сам докачивает только те моды, которых у него нет (сверка по
sha1) — поэтому обновление сборки не заставляет всех перекачивать её целиком.
overrides.zip при загрузке нормализуется (см. save_overrides), а из
установщика загрузчика в фоне собирается «толстый» офлайн-установщик (см.
start_fat_build) — с ним игрокам не нужен доступ к серверам Mojang/NeoForge.
meta.json — кэш размеров/хэшей, чтобы не хэшировать гигабайт на каждый запрос
манифеста. Без Flask/БД.
"""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import threading
import time
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

# Фоновые сборки офлайн-установщика, root сборки -> поток. Только чтобы
# отличить «собирается» от «панель перезапустили посреди сборки».
_fat_threads: dict = {}
FAT_TIMEOUT = 30 * 60

# Путь внутри версии длиннее этого у игрока почти наверняка упрётся в лимит
# Windows в 260 символов (C:\Users\<имя>\AppData\Roaming\.minecraft\versions\<сборка>\ — уже ~130).
LONG_REL_PATH = 120

_JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
# Папки, которые и есть содержимое overrides — архив, где всё лежит в одной
# такой папке, не «обёрнут», и снимать её нельзя.
_CONTENT_DIRS = {"config", "defaultconfigs", "kubejs", "resourcepacks", "shaderpacks", "scripts",
                 "mods", "saves", "schematics", "screenshots", "global_packs", "datapacks"}
# Конфиги, где шейдер выбран по имени папки в shaderpacks/.
_SHADER_SELECTION_FILES = {"config/iris.properties", "config/oculus.properties", "optionsshaders.txt"}
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


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
        self.fat_path = os.path.join(self.root, "installer-offline.jar")
        self.fat_log_path = os.path.join(self.root, "installer-offline.log")
        self._version_json_path = os.path.join(self.root, "version.json")
        self._overrides_files_path = os.path.join(self.root, "overrides_files.json")
        self._meta_path = os.path.join(self.root, "meta.json")

    # ---- meta.json -----------------------------------------------------------

    @property
    def meta(self) -> dict:
        meta = {"name": None, "loader": None, "installer": None, "mods": {}, "overrides": None,
                "show_on_status": False, "ram_gb": None, "fat": None}
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

    def set_ram(self, raw: str) -> int | None:
        """Сколько памяти советовать игроку (ГБ) — установщик напомнит выставить
        её в TLauncher и предупредит, если на компьютере её мало. Пусто — не
        советовать."""
        raw = (raw or "").strip()
        if not raw:
            ram = None
        else:
            try:
                ram = int(raw)
            except ValueError:
                raise ClientPackError("Память — целое число гигабайт, например 8")
            if not 1 <= ram <= 64:
                raise ClientPackError("Память — от 1 до 64 ГБ")
        self._update_meta(lambda m: m.update(ram_gb=ram))
        return ram

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
        if os.path.exists(self.fat_path):
            os.remove(self.fat_path)
        self._update_meta(lambda m: m.update(loader=loader, installer=info, fat=None))
        self.start_fat_build()
        return loader

    def delete_installer(self) -> None:
        for path in (self.installer_path, self._version_json_path, self.fat_path):
            if os.path.exists(path):
                os.remove(path)
        self._update_meta(lambda m: m.update(loader=None, installer=None, fat=None))

    # ---- офлайн-установщик ----------------------------------------------------

    def start_fat_build(self) -> None:
        """
        Обычный установщик NeoForge/Forge у игрока сам качает Minecraft и
        библиотеки с серверов Mojang/NeoForge — если они у игрока недоступны
        или медленные, установка падает. Его же режим --fat собирает «толстый»
        установщик со всем этим внутри (~170 МБ), который ставит загрузчик с
        --offline вообще без сети. Собираем его здесь, на панели, в фоне
        (качает те же ~170 МБ, пара минут); пока не готов или не собрался —
        игрокам отдаётся обычный установщик.
        """
        meta = self.meta
        if not meta["installer"]:
            return
        src_sha = meta["installer"]["sha1"]
        java = shutil.which("java")
        if not java:
            self._update_meta(lambda m: m.update(fat={"status": "no-java", "for": src_sha}))
            return
        self._update_meta(lambda m: m.update(fat={"status": "building", "for": src_sha}))
        thread = threading.Thread(target=self._build_fat, args=(java, src_sha), daemon=True)
        _fat_threads[self.root] = thread
        thread.start()

    def _build_fat(self, java: str, src_sha: str) -> None:
        work = os.path.join(self.root, "fat-build-" + src_sha[:8])
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work)
        out = os.path.join(work, "fat.jar")
        src = os.path.join(work, "installer.jar")

        def still_current(m):
            return (m.get("installer") or {}).get("sha1") == src_sha

        try:
            # Копия: admin может загрузить новый установщик посреди сборки.
            shutil.copy(self.installer_path, src)
            # Сборка качает ~170 МБ с серверов Mojang/NeoForge — разовый
            # сетевой сбой не повод сдаваться: до трёх попыток.
            for attempt in range(3):
                proc = subprocess.run(
                    [java, "-jar", src, "--fat", out, "--fat-include-minecraft", "--fat-include-minecraft-libs",
                     "--fat-include-installer-libs", "--fat-offline"],
                    cwd=work, capture_output=True, text=True, timeout=FAT_TIMEOUT,
                )
                if proc.returncode == 0 and os.path.isfile(out):
                    break
                if not still_current(self.meta):
                    return
                time.sleep(10 * (attempt + 1))
            if proc.returncode != 0 or not os.path.isfile(out):
                log = (proc.stdout + proc.stderr).strip()
                with open(self.fat_log_path, "w", encoding="utf-8") as f:
                    f.write(log)
                # В конце вывода — стек Java; полезна строка с самим исключением.
                lines = log.splitlines()
                reason = next((l for l in lines if "Exception" in l and not l.lstrip().startswith("at ")), None)
                raise RuntimeError((reason or (lines[-1] if lines else f"код {proc.returncode}")).strip())
            info = {"status": "ready", "for": src_sha, "size": os.path.getsize(out), "sha1": _sha1(out)}

            def apply(m):
                if still_current(m):
                    os.replace(out, self.fat_path)
                    m["fat"] = info
            self._update_meta(apply)
        except Exception as e:
            def fail(m):
                if still_current(m):
                    m["fat"] = {"status": "error", "for": src_sha, "error": str(e)[-300:]}
            self._update_meta(fail)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    @property
    def fat_status(self) -> str | None:
        """None / building / ready / error / no-java / interrupted (панель
        перезапустили посреди сборки — можно запустить заново)."""
        fat = self.meta["fat"]
        if not fat:
            return None
        if fat["status"] == "building":
            thread = _fat_threads.get(self.root)
            if not thread or not thread.is_alive():
                return "interrupted"
        return fat["status"]

    def installer_for_players(self) -> tuple[str, dict, bool]:
        """(путь, {size, sha1}, офлайн ли) — офлайн-установщик, если он собран
        из текущего установщика, иначе обычный."""
        meta = self.meta
        fat = meta["fat"] or {}
        if (fat.get("status") == "ready" and fat.get("for") == (meta["installer"] or {}).get("sha1")
                and os.path.isfile(self.fat_path)):
            return self.fat_path, {"size": fat["size"], "sha1": fat["sha1"]}, True
        return self.installer_path, meta["installer"], False

    def version_json_text(self) -> str:
        """JSON версии для versions/<имя сборки>/<имя сборки>.json у игрока."""
        with open(self._version_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["id"] = self.meta["name"]
        # Без этого флага TLauncher не показывает свои скины в «чужих» версиях.
        data["skinVersion"] = True
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
        Принимаем архив почти в любом виде (папка overrides целиком, сам zip
        сборки с CurseForge, архив с обёрткой «Имя сборки/overrides/...» или
        просто config/, resourcepacks/ в корне) и пересобираем нормализованный
        overrides.zip, где пути уже такие, какими лягут в папку версии:
          * снимается обёртка до overrides/ включительно (или одна общая
            папка верхнего уровня, если overrides/ нет), мусор (__MACOSX и т.п.)
            выкидывается;
          * распакованные шейдерпаки (shaderpacks/<Имя>/shaders/...) упаковываются
            в shaderpacks/<Имя>.zip — Iris/Oculus читают их из архива, а тысячи
            файлов с длинными путями у игрока упираются в лимит Windows в 260
            символов; выбор шейдера в iris.properties/oculus.properties/
            optionsshaders.txt и файл его настроек переименовываются следом;
          * для каждого файла считается sha1 (overrides_files.json) — по ним
            установщик обновляет у игрока только то, что admin реально изменил.
        """
        os.makedirs(self.root, exist_ok=True)
        tmp = self.overrides_path + ".part"
        out_tmp = self.overrides_path + ".new"
        file_storage.save(tmp)
        try:
            if not zipfile.is_zipfile(tmp):
                raise ClientPackError("overrides — нужен .zip-архив")
            with zipfile.ZipFile(tmp) as src:
                infos = [i for i in src.infolist() if not i.is_dir()]
                for info in infos:
                    n = info.filename.replace("\\", "/")
                    if n.startswith("/") or ".." in n.split("/") or re.match(r"^[A-Za-z]:", n):
                        raise ClientPackError(f"В архиве путь, ведущий наружу: {n}")
                infos = [i for i in infos if not i.filename.replace("\\", "/").startswith("__MACOSX/")]
                entries = self._select_overrides(infos)
                if not entries:
                    raise ClientPackError("Архив overrides пустой")
                files_map, shaders, long_paths = self._write_normalized(src, entries, out_tmp)
            info = {
                "size": os.path.getsize(out_tmp),
                "sha1": _sha1(out_tmp),
                "files": len(files_map),
                "shaders_packed": shaders,
                "long_paths": long_paths,
            }
            with open(self._overrides_files_path, "w", encoding="utf-8") as f:
                json.dump(files_map, f, ensure_ascii=False)
            os.replace(out_tmp, self.overrides_path)
        finally:
            for path in (tmp, out_tmp):
                if os.path.exists(path):
                    os.remove(path)
        self._update_meta(lambda m: m.update(overrides=info))
        return info

    @staticmethod
    def _select_overrides(infos) -> list:
        """[(ZipInfo, путь внутри версии)] — с уже снятой обёрткой."""
        names = [i.filename.replace("\\", "/") for i in infos]
        prefix = None
        for n in names:
            low = "/" + n.lower()
            pos = low.find("/overrides/")
            if pos != -1:
                candidate = n[:pos + len("overrides/")]
                # только «overrides/» или «Обёртка/overrides/» — не папка с
                # таким именем где-нибудь в config/<мод>/
                if candidate.count("/") > 2:
                    continue
                if prefix is None or len(candidate) < len(prefix):
                    prefix = candidate
        if prefix is None:
            tops = {n.split("/", 1)[0] for n in names}
            top = tops.pop() if len(tops) == 1 else None
            if top and all("/" in n for n in names) and top.lower() not in _CONTENT_DIRS:
                prefix = top + "/"
            else:
                prefix = ""
        result = []
        for info, n in zip(infos, names):
            if not n.startswith(prefix):
                continue  # manifest.json, modlist.html, mods/ рядом с overrides/ и т.п.
            rel = n[len(prefix):]
            parts = rel.split("/")
            if not rel or parts[0] == "__MACOSX" or parts[-1].lower() in _JUNK_NAMES:
                continue
            result.append((info, rel))
        return result

    @staticmethod
    def _write_normalized(src: zipfile.ZipFile, entries: list, out_path: str):
        shader_dirs: dict = {}
        regular = []
        for info, rel in entries:
            parts = rel.split("/")
            if len(parts) >= 3 and parts[0].lower() == "shaderpacks":
                shader_dirs.setdefault(parts[1], []).append((info, "/".join(parts[2:])))
            else:
                regular.append((info, rel))
        # Пакуем только настоящие шейдеры (с папкой shaders/) и только если
        # рядом уже нет .zip с тем же именем.
        regular_rels = {rel.lower() for _, rel in regular}
        packed = []
        for name, items in list(shader_dirs.items()):
            is_shader = any(inner.startswith("shaders/") for _, inner in items)
            if not is_shader or f"shaderpacks/{name}.zip".lower() in regular_rels:
                regular.extend((info, f"shaderpacks/{name}/{inner}") for info, inner in items)
                del shader_dirs[name]
            else:
                packed.append(name)

        def zinfo(name):
            zi = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            return zi

        files_map = {}
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as dst:
            for info, rel in regular:
                rel_out = rel
                low = rel.lower()
                # файл настроек шейдера (Iris): shaderpacks/<Имя>.txt -> <Имя>.zip.txt
                for name in packed:
                    if low == f"shaderpacks/{name}.txt".lower():
                        rel_out = f"shaderpacks/{name}.zip.txt"
                if low in _SHADER_SELECTION_FILES and packed:
                    text = src.read(info).decode("utf-8", "replace")
                    for name in packed:
                        text = re.sub(r"(?m)^(\s*shaderPack\s*=\s*)" + re.escape(name) + r"\s*$",
                                      lambda m: m.group(1) + name + ".zip", text)
                    data = text.encode("utf-8")
                    dst.writestr(zinfo(rel_out), data)
                    files_map[rel_out] = hashlib.sha1(data).hexdigest()
                    continue
                h = hashlib.sha1()
                with src.open(info) as fin, dst.open(zinfo(rel_out), "w") as fout:
                    for chunk in iter(lambda: fin.read(1024 * 1024), b""):
                        h.update(chunk)
                        fout.write(chunk)
                files_map[rel_out] = h.hexdigest()
            for name in packed:
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                    for info, inner in sorted(shader_dirs[name], key=lambda x: x[1]):
                        z.writestr(zinfo(inner), src.read(info))
                data = buf.getvalue()
                rel = f"shaderpacks/{name}.zip"
                dst.writestr(zinfo(rel), data)
                files_map[rel] = hashlib.sha1(data).hexdigest()
        long_paths = sum(1 for rel in files_map if len(rel) > LONG_REL_PATH)
        return files_map, packed, long_paths

    def overrides_files(self) -> dict:
        try:
            with open(self._overrides_files_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def delete_overrides(self) -> None:
        for path in (self.overrides_path, self._overrides_files_path):
            if os.path.exists(path):
                os.remove(path)
        self._update_meta(lambda m: m.update(overrides=None))

    # ---- .bat ----------------------------------------------------------------

    def render_installer_ps1(self, pack_url: str) -> bytes:
        """Сам скрипт установки. UTF-8 с BOM: без BOM Windows PowerShell 5.1
        читает .ps1 в ANSI-кодировке, и вся кириллица превращается в мусор."""
        template_path = os.path.join(os.path.dirname(__file__), "installer_template.ps1")
        with open(template_path, "r", encoding="utf-8") as f:
            script = f.read()
        script = script.replace("__PACK_URL__", pack_url.replace("'", "''"))
        return b"\xef\xbb\xbf" + script.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")

    @staticmethod
    def render_installer_bat(pack_url: str) -> bytes:
        """
        .bat — только загрузчик: скачивает свежий installer.ps1 с панели и
        запускает его. Поэтому исправления скрипта доходят до игроков без
        перекачивания .bat, а в самом файле нет кода, который выполняется
        через iex (антивирусы такое особенно не любят). Шапка — чистый ASCII
        (cmd читает её в OEM-кодировке), переводы строк CRLF.
        """
        url = pack_url.replace("%", "%%")  # в .bat «%» — начало переменной
        bat = (
            "@echo off\n"
            "rem MCServerCore: modpack installer for TLauncher\n"
            'set "MCSC_SELF=%~f0"\n'
            'set "MCSC_GAMEDIR=%~1"\n'
            f'set "MCSC_PACK_URL={url}"\n'
            'set "MCSC_PS1=%TEMP%\\mcsc-installer.ps1"\n'
            "powershell -NoProfile -ExecutionPolicy Bypass -Command "
            '"[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; '
            "try { (New-Object Net.WebClient).DownloadFile($env:MCSC_PACK_URL + '/installer.ps1', $env:MCSC_PS1) } "
            "catch { Write-Host ('Cannot reach ' + $env:MCSC_PACK_URL + ' : ' + $_.Exception.Message) -ForegroundColor Red; exit 1 }\"\n"
            "if errorlevel 1 goto end\n"
            'powershell -NoProfile -ExecutionPolicy Bypass -File "%MCSC_PS1%"\n'
            ":end\n"
            "echo.\n"
            "pause\n"
            "exit /b\n"
        )
        return bat.replace("\n", "\r\n").encode("ascii")
