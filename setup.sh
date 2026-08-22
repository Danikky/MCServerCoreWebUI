#!/usr/bin/env bash
# setup.sh — первичная настройка серверной части MCServerCore:
# создаёт виртуальное окружение, ставит зависимости, готовит нужные папки.
#
# Скрипт запускается через шебанг под bash независимо от того, какой у тебя
# логин-шелл (bash, fish и т.д.) и в каком терминале ты его вызываешь
# (обычный терминал, kitty, что угодно) — просто:
#   ./setup.sh
# Если шелл не bash (например fish), НЕ используй `source setup.sh` —
# запускай именно как исполняемый файл, иначе шелл попытается разобрать
# bash-синтаксис как свой собственный и упадёт с ошибкой парсинга.

# Если скрипт случайно засорсили в bash — прервёмся, не убивая шелл юзера.
if [ "${BASH_SOURCE[0]}" != "${0}" ]; then
    echo "Не сорси этот скрипт — запускай его напрямую: ./setup.sh" >&2
    return 1 2>/dev/null || exit 1
fi

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"

echo "==> Проверка Python..."
if ! command -v python3 &>/dev/null; then
    echo "Ошибка: python3 не найден. Установите Python 3 и повторите попытку." >&2
    exit 1
fi
python3 --version

echo "==> Создание виртуального окружения ($VENV_DIR)..."
if [ -d "$VENV_DIR" ]; then
    echo "Виртуальное окружение уже существует, пропускаю."
else
    if ! python3 -m venv "$VENV_DIR" 2>/tmp/mcsc_venv_err.$$; then
        cat /tmp/mcsc_venv_err.$$ >&2
        rm -f /tmp/mcsc_venv_err.$$
        echo >&2
        echo "Не удалось создать venv. На Debian/Ubuntu это обычно значит," >&2
        echo "что не установлен пакет python3-venv:" >&2
        echo "    sudo apt install python3-venv" >&2
        exit 1
    fi
    rm -f /tmp/mcsc_venv_err.$$
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "==> Обновление pip..."
pip install --upgrade pip

echo "==> Установка зависимостей из requirements.txt..."
pip install -r requirements.txt

echo "==> Подготовка папки серверов (servers/)..."
mkdir -p servers

echo
echo "Готово! Окружение настроено."
echo "Серверы создаются и настраиваются прямо из веб-панели (раздел «Серверы»)"
echo "— туда же можно загрузить ядро (.jar) файлом или по ссылке."
echo "Запустить приложение можно командой: ./launch.sh"
