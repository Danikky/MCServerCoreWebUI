"""
Чистые файловые хелперы без зависимости от Flask/БД. Раньше жили в stmc.py
вперемешку с sqlite-кодом; здесь — только то, что трогает диск.
"""
import os
import shutil
import sys


def return_main_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    # .../MCServerCoreWebUI/app/fs_utils.py -> .../MCServerCoreWebUI
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PathEscapeError(Exception):
    """Запрошенный путь выходит за пределы разрешённой директории."""


def safe_join(allowed_root: str, path_or_relative: str) -> str:
    """
    Резолвит path_or_relative (относительный — джойнится с return_main_dir(),
    либо уже абсолютный) и гарантирует, что результат лежит внутри
    allowed_root (включительно). Иначе кидает PathEscapeError — используется,
    чтобы файловый менеджер и бекапы не могли уйти через "../.." за пределы
    своей папки.
    """
    if os.path.isabs(path_or_relative):
        candidate = os.path.realpath(path_or_relative)
    else:
        candidate = os.path.realpath(os.path.join(return_main_dir(), path_or_relative))
    allowed_root_real = os.path.realpath(allowed_root)
    if candidate != allowed_root_real and not candidate.startswith(allowed_root_real + os.sep):
        raise PathEscapeError(f"Путь вне разрешённой директории: {path_or_relative}")
    return candidate


def rename(allowed_root: str, folder_path: str, new_name: str) -> bool:
    try:
        path = safe_join(allowed_root, folder_path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Объект не найден: {path}")
        parent_dir = os.path.dirname(path)
        new_path = safe_join(allowed_root, os.path.join(parent_dir, new_name))
        if os.path.exists(new_path):
            raise FileExistsError(f"Имя уже занято: {new_name}")
        os.rename(path, new_path)
        return True
    except Exception as e:
        print(f"Ошибка переименования: {e}")
        return False


def delete(allowed_root: str, folder_path: str) -> bool:
    try:
        path = safe_join(allowed_root, folder_path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Объект не найден: {path}")
        if os.path.isfile(path):
            os.remove(path)
            return True
        if os.path.isdir(path):
            shutil.rmtree(path)
            return True
    except Exception as e:
        print(f"Ошибка удаления: {e}")
        return False


def get_dir(allowed_root: str, folder_path: str) -> list:
    dir_path = safe_join(allowed_root, folder_path)
    return os.listdir(dir_path)


def under(root: str, subpath: str, *extra: str) -> str:
    """
    Абсолютный путь под root, построенный из subpath (относительно root) и
    опциональных доп.сегментов — то, что нужно передавать в safe_join/rename/
    delete/make/get_dir/read_text/write_text как уже-абсолютный path, а не
    как "путь относительно корня всего проекта" (см. safe_join). subpath
    может быть пустой строкой (означает сам root).
    """
    return os.path.join(root, subpath, *extra) if subpath else os.path.join(root, *extra)


MAX_TEXT_EDIT_BYTES = 2 * 1024 * 1024  # 2 MB — редактор не для гигабайтных файлов


def read_text(allowed_root: str, path: str, max_bytes: int = MAX_TEXT_EDIT_BYTES) -> str:
    """Читает текстовый файл для редактора. Кидает FileNotFoundError,
    PathEscapeError или ValueError (слишком большой / не текстовый файл)."""
    target = safe_join(allowed_root, path)
    if not os.path.isfile(target):
        raise FileNotFoundError(f"Файл не найден: {path}")
    size = os.path.getsize(target)
    if size > max_bytes:
        raise ValueError(f"Файл слишком большой для редактора ({size // 1024} KB, лимит {max_bytes // 1024} KB)")
    try:
        with open(target, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        raise ValueError("Файл не похож на текстовый (не UTF-8) — редактор его не откроет")


def write_text(allowed_root: str, path: str, content: str, max_bytes: int = MAX_TEXT_EDIT_BYTES) -> None:
    if len(content.encode('utf-8')) > max_bytes:
        raise ValueError(f"Содержимое слишком большое (лимит {max_bytes // 1024} KB)")
    target = safe_join(allowed_root, path)
    with open(target, 'w', encoding='utf-8') as f:
        f.write(content)


def make(allowed_root: str, folder_path: str, is_directory: bool) -> bool:
    try:
        path = safe_join(allowed_root, folder_path)
        if os.path.exists(path):
            raise FileExistsError(f"Объект уже существует: {path}")
        if is_directory:
            os.makedirs(path, exist_ok=True)
            return True
        parent_dir = os.path.dirname(path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
        with open(path, 'w'):
            pass
        return True
    except Exception as e:
        print(f"Ошибка при создании файла/директории: {e}")
        return False


def clone_dir(path: str, to_path: str, overwrite: bool = False, ignore=None):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Исходная директория не найдена: {path}")
    if not os.path.isdir(path):
        raise NotADirectoryError(f"Указанный путь не является директорией: {path}")
    if os.path.exists(to_path):
        if not overwrite:
            raise FileExistsError(f"Целевая директория уже существует: {to_path}")
        shutil.rmtree(to_path)
    shutil.copytree(path, to_path, ignore=ignore)


def sort_dir(dir_list: list) -> list:
    """Сортирует директории по типу — папки раньше файлов."""
    dirs = [i for i in dir_list if "." not in i]
    files = [i for i in dir_list if "." in i]
    return dirs + files


def agree_eula(server_path: str):
    eula_path = os.path.join(server_path, "eula.txt")
    with open(eula_path, 'r', encoding='utf-8') as f:
        new_lines = ["eula=true" if "eula=false" in line else line for line in f]
    with open(eula_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
