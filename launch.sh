#!/usr/bin/env bash
# launch.sh — запуск серверной части MCServerCore (веб-интерфейс + управление сервером).
#
# Работает одинаково из-под любого логин-шелла (bash, fish...) и любого
# терминала (в т.ч. kitty) — шебанг сам поднимает bash. Запускай как
# исполняемый файл (./launch.sh), не сорси.

if [ "${BASH_SOURCE[0]}" != "${0}" ]; then
    echo "Не сорси этот скрипт — запускай его напрямую: ./launch.sh" >&2
    return 1 2>/dev/null || exit 1
fi

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Виртуальное окружение не найдено. Сначала выполните: ./setup.sh" >&2
    exit 1
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

exec python3 main.py
