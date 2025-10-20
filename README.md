# MCServerCore Web UI

[![English](https://img.shields.io/badge/Language-English-blue?style=flat-square)](README.md)
[![Russian](https://img.shields.io/badge/Language-Русский-green?style=flat-square)](README.ru.md)

Веб-интерфейс для простого и удобного управления Minecraft-сервером, работающим на базе [MCServerCore](https://github.com/Danikky/MCServerCore).

Этот проект предоставляет современный и интуитивно понятный веб-сайт, который позволяет администраторам и игрокам взаимодействовать с сервером без необходимости использования консоли или прямого доступа к файловой системе.

---

### 🌐 English Version

This is a modern web interface for easy management of a Minecraft server running on [MCServerCore](https://github.com/Danikky/MCServerCore). It allows server admins and players to interact with the server seamlessly through a browser, without the need for a console or direct file access.

---

## ✨ Возможности / Features

*   **📊 Мониторинг в реальном времени:** Отслеживайте состояние сервера, TPS, онлайн игроков и использование памяти.
    *   **Real-time Monitoring:** Keep an eye on server status, TPS, online players, and memory usage.
*   **👥 Управление игроками:** Легко просматривайте список онлайн игроков, отправляйте сообщения и выполняйте команды.
    *   **Player Management:** Easily view the list of online players, send messages, and execute commands.
*   **⚙️ Управление сервером:** Запускайте, останавливайте и перезагружайте сервер прямо из браузера.
    *   **Server Management:** Start, stop, and restart the server directly from your browser.
*   **📁 Файловый менеджер:** Просматривайте и управляйте файлами сервера (миры, плагины, конфиги) через удобный интерфейс.
    *   **File Manager:** Browse and manage server files (worlds, plugins, configs) through a user-friendly interface.
*   **📰 Просмотр логов:** Читайте логи сервера в удобном формате с возможностью фильтрации.
    *   **Log Viewing:** Read server logs in a convenient format with filtering capabilities.
*   **🎛️ Консоль сервера:** Отправляйте команды на сервер и просматривайте вывод в реальном времени в интегрированной веб-консоли.
    *   **Server Console:** Send commands to the server and view the output in real-time in an integrated web console.
*   **📱 Адаптивный дизайн:** Веб-интерфейс корректно отображается на компьютерах, планшетах и смартфонах.
    *   **Responsive Design:** The web interface looks great on desktops, tablets, and smartphones.

## 🖼️ Скриншоты / Screenshots

<details>
<summary><b>Посмотреть скриншоты / Click to view screenshots</b></summary>

| Панель управления / Dashboard | Управление игроками / Player Management |
| :---: | :---: |
| ![Dashboard](screenshots/dashboard.png) | ![Players](screenshots/players.png) |
| Файловый менеджер / File Manager | Консоль / Console |
| ![File Manager](screenshots/files.png) | ![Console](screenshots/console.png) |

</details>

## 🚀 Быстрый старт / Quick Start

### Предварительные требования / Prerequisites

1.  **Python 3.8+**
2.  **MCServerCore** (основной серверный проект)
3.  Установленные пакеты из `requirements.txt`

### Установка и запуск / Installation & Run

1.  **Клонируйте репозиторий:**
    ```bash
    git clone https://github.com/Danikky/MCServerCoreWebUI.git
    cd MCServerCoreWebUI
    ```

2.  **Установите зависимости Python:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Настройте конфигурацию:**
    *   Отредактируйте файл `config.json`, указав правильные пути и настройки для вашего экземпляра MCServerCore.
    *   Пример конфигурации:
    ```json
    {
      "server_root_path": "/path/to/your/MCServerCore",
      "host": "0.0.0.0",
      "port": 5000,
      "debug": false,
      "secret_key": "your-secret-key-here"
    }
    ```

4.  **Запустите веб-приложение:**
    ```bash
    python app.py
    ```

5.  **Откройте браузер:**
    *   Перейдите по адресу `http://localhost:5000` (или по другому адресу/порту, указанному в вашем `config.json`).

## ⚙️ Конфигурация / Configuration

Все основные настройки производятся в файле `config.json`:

| Ключ / Key | Описание / Description |
| :--- | :--- |
| `server_root_path` | **Абсолютный путь** к корневой директории MCServerCore. |
| `host` | Хост для запуска веб-сервера (например, `0.0.0.0` для доступа извне). |
| `port` | Порт для запуска веб-сервера. |
| `debug` | Режим отладки Flask (не используйте `True` в продакшене). |
| `secret_key` | Секретный ключ для сессий Flask. |

## 🛠️ Разработка / Development

Мы рады вашим вкладам! Если вы хотите помочь с развитием проекта:

1.  Сделайте форк репозитория.
2.  Создайте ветку для вашей функциональности (`git checkout -b feature/AmazingFeature`).
3.  Зафиксируйте изменения (`git commit -m 'Add some AmazingFeature'`).
4.  Отправьте в ветку (`git push origin feature/AmazingFeature`).
5.  Откройте Pull Request.

## 📜 Лицензия / License

Этот проект распространяется под лицензией MIT. Подробнее см. в файле [LICENSE](LICENSE).

## 🤝 Благодарности / Acknowledgments

*   Основано на проекте [MCServerCore](https://github.com/Danikky/MCServerCore).
*   Построено с использованием [Flask](https://flask.palletsprojects.com/), микрофреймворка для Python.

README.md СГЕНЕРИРОВАНО ИИ И СОДЕРЖИТ ОШИБКИ.