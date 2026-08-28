# Деплой MCServerCore

Этот гайд про серверную часть (веб-панель из этого репозитория). Клиентская
часть (лаунчер, клиент Minecraft) — отдельная тема, сюда не входит.

Два сценария:

1. **Локальный тест** — гоняешь панель у себя на машине, `debug=True`, без домена.
2. **Прод** — панель на сервере (VPS/хостинг), за доменом, за HTTPS.

---

## 1. Локальный тест

```bash
git clone <repo-url> MCServerCoreWebUI
cd MCServerCoreWebUI
./setup.sh     # venv + зависимости + папка servers/
./launch.sh    # запуск на 0.0.0.0:5245
```

При первом старте панель сама создаёт админа со случайным паролем и печатает
его в консоль (см. `app/models.py:ensure_first_admin`) — сохрани его оттуда,
второй раз он не покажется. Логин — `admin`, если не переопределён через
`ADMIN_USERNAME` (см. `.env.example`).

Панель поддерживает несколько серверов одновременно — создаются прямо в UI
(«Серверы» → «+ Новый сервер»). Ядро (`.jar`) для каждого — там же, на
странице «Ядро» конкретного сервера: либо обычная загрузка файла, либо
вставить прямую ссылку на сборку (Paper/Purpur/Fabric/...), панель сама
скачает. Можно и вручную — положить `.jar` в `servers/<slug>/` (папка
создаётся автоматически при первом обращении к серверу), панель подхватит
его так же, автодетектом.

Тестируй так, пока не готов домен/сервер. Дальше — уже прод.

---

## 2. Прод-деплой

### 2.1 Перед тем как выставлять наружу

`SECRET_KEY`, дефолтный пароль админа и `debug=True` — то, что раньше было
здесь захардкожено — уже вынесено в конфиг (см. `app/config.py` и
`.env.example`, подробности в REVIEW.md, раздел 🔴). На проде реально важно
только не забыть:

- **Не выставлять `MCSC_DEBUG=1`** на публичном сервере — debug-режим
  Flask даёт Werkzeug-дебаггер с исполнением произвольного Python-кода
  через браузер. По умолчанию он и так выключен, просто не включай его сам.
- **Задать `SECRET_KEY` явно через systemd** (см. юнит ниже), а не
  полагаться на автогенерацию в `.flask_secret_key` — если этот файл
  случайно попадёт не в тот бэкап или потеряется при переезде на другую
  машину, все сессии слетят разом.
- **Не включать `ALLOW_REGISTRATION`**, если панель не рассчитана на
  самостоятельную регистрацию всех, кто найдёт домен — новые аккаунты
  создаются с ролью `viewer` (только просмотр), но всё равно решай
  осознанно.
- Роли: `admin` — полный доступ, `viewer` — только просмотр консоли/
  статуса/игроков/настроек, без выполнения команд и без доступа к
  файловому менеджеру/бекапам вовсе. Повысить пользователя до `admin`
  сейчас можно только вручную в БД — UI для этого ещё нет (см. REVIEW.md,
  🟢 «Роли и права»):
  ```bash
  sqlite3 DataBase.db "UPDATE users SET role='admin' WHERE username='кто-то';"
  ```

### 2.2 Подготовка сервера (Ubuntu/Debian VPS)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git default-jre-headless

sudo useradd -r -m -s /bin/bash mcserver   # отдельный непривилегированный юзер
sudo su - mcserver
```

`default-jre-headless` (или конкретная версия JDK под твоё ядро сервера) нужен,
чтобы сам Minecraft-сервер вообще мог запуститься — панель просто дергает `java -jar ...`.

### 2.3 Установка приложения

```bash
git clone <repo-url> /home/mcserver/MCServerCoreWebUI
cd /home/mcserver/MCServerCoreWebUI
./setup.sh
```

Ядра серверов заводятся уже из самого UI (см. выше) — на этом шаге просто
подними приложение; `SECRET_KEY` через окружение настроим ниже через systemd,
а не вручную.

### 2.4 Запуск как systemd-сервис

Дев-сервер Flask-SocketIO не рассчитан на то, чтобы падать и не
перезапускаться — на проде процесс держит systemd.

`/etc/systemd/system/mcservercore.service`:

```ini
[Unit]
Description=MCServerCore Web UI
After=network.target

[Service]
Type=simple
User=mcserver
Group=mcserver
WorkingDirectory=/home/mcserver/MCServerCoreWebUI
Environment=SECRET_KEY=<сгенерированный случайный ключ>
ExecStart=/home/mcserver/MCServerCoreWebUI/launch.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Случайный ключ можно сгенерировать так: `python3 -c "import secrets; print(secrets.token_hex(32))"`.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mcservercore
sudo systemctl status mcservercore     # проверить, что поднялся
journalctl -u mcservercore -f          # живые логи
```

Панель слушает `127.0.0.1:5245` для внешнего мира — наружу её напрямую
пускать не нужно, для этого следующий шаг.

### 2.5 Nginx как reverse proxy + WebSocket

Панель использует Flask-SocketIO (WebSocket для живой консоли), поэтому в
конфиге nginx обязательны заголовки `Upgrade`/`Connection`, иначе консоль
не будет обновляться в реальном времени.

Загрузка ядра сервера (`/servers/<id>/core/upload`) — это обычный HTTP-
аплоад файла, а у nginx лимит на размер тела запроса по умолчанию всего
1 МБ — любой jar крупнее сразу получит `413`. Добавь `client_max_body_size`
в конфиг (значение — не меньше `MCSC_MAX_UPLOAD_MB` из `.env`, дефолт которого
1024 МБ):

```bash
sudo apt install -y nginx
```

`/etc/nginx/sites-available/mcservercore`:

```nginx
server {
    listen 80;
    server_name admin.dan1kkystudio.ru;

    client_max_body_size 1024m;

    location / {
        proxy_pass http://127.0.0.1:5245;
        proxy_http_version 1.1;

        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/mcservercore /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 2.6 Домены и HTTPS

Два домена под две разные вещи — не смешивать:

- **`admin.dan1kkystudio.ru`** — веб-панель, обычный HTTP(S) через nginx
  из шага выше.
- **`play.dan1kkystudio.ru`** — подключение к самому Minecraft-серверу,
  сырой TCP (плюс отдельно UDP для войсчата, см. §2.9) — nginx и HTTPS
  тут вообще ни при чём, это не HTTP-трафик.

**Панель (`admin.`):**

1. A-запись `admin.dan1kkystudio.ru → IP сервера` у регистратора/DNS-провайдера.
2. Дождись распространения (обычно от пары минут до пары часов).
3. Получи сертификат через certbot:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d admin.dan1kkystudio.ru
```

Certbot сам допишет `listen 443 ssl`, сертификаты и редирект с 80 на 443
в конфиг nginx, и настроит автопродление (проверить: `sudo certbot renew --dry-run`).

**Игра (`play.`):**

1. A-запись `play.dan1kkystudio.ru → IP машины, где реально слушает
   игровой порт` — не обязательно та же машина, что и панель.
2. Если игровой порт нестандартный (не `25565`, смотри `server-port` в
   `server.properties` конкретного сервера в панели) — добавь ещё и
   **SRV-запись**: `_minecraft._tcp.play.dan1kkystudio.ru` → приоритет/
   вес/порт/хост. Тогда игрок всё равно вводит просто
   `play.dan1kkystudio.ru`, без порта — Java-клиент сам делает SRV-lookup.
   Без SRV пришлось бы диктовать `play.dan1kkystudio.ru:<порт>` руками, и
   адрес ломался бы при каждой смене порта. SRV работает только для
   **Java Edition** — Bedrock его не поддерживает.
3. Если IP не статический (сервер за домашним интернетом, провайдер меняет
   адрес) — нужен DDNS вместо обычной A-записи, иначе адрес протухнет.

### 2.7 Файрвол

Наружу открыт только веб-трафик и SSH — сам порт 5245 наружу торчать не должен
(панель слушает `127.0.0.1`, так что технически уже не достижима извне, но
файрвол — вторая линия защиты):

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'   # 80 + 443
sudo ufw enable
```

Если игроки должны заходить на сам Minecraft-сервер снаружи — дополнительно
открой его игровой порт (обычно `25565/tcp`, значение — из `server.properties`
на сервере, ключ `server-port`), а если подключаешь войсчат — ещё и его UDP-
порт (см. §2.9):

```bash
sudo ufw allow 25565/tcp     # игровой порт play.dan1kkystudio.ru
sudo ufw allow 24454/udp     # Simple Voice Chat, если подключаешь
```

### 2.8 Обновление после деплоя

```bash
cd /home/mcserver/MCServerCoreWebUI
git pull
./setup.sh                      # подтянет новые зависимости, если есть
sudo systemctl restart mcservercore
```

### 2.9 Голосовой чат (Simple Voice Chat)

[Simple Voice Chat](https://modrinth.com/plugin/simple-voice-chat) —
официально поддерживает Folia/Paper/Spigot (не только Fabric/Forge как
мод). Идёт отдельным плагином + свой **UDP**-порт (по умолчанию `24454`) —
голосовой трафик не имеет отношения ни к игровому TCP-порту, ни тем более
к панели/nginx, это отдельный поток данных напрямую по UDP.

1. Скачай `bukkit`-сборку (она одна работает и на Paper, и на Folia, и на
   Spigot) под версию сервера — версии и билды:
   https://modrinth.com/plugin/simple-voice-chat/versions?l=bukkit
2. Положи `.jar` в `plugins/` нужного сервера через файловый менеджер
   панели (`/servers/<id>/files/plugins`) — как обычный плагин.
3. Перезапусти сервер (кнопка Restart на странице «Консоль» — можно и
   через планировщик, если хочешь по расписанию). При первом старте
   плагин сам создаст `plugins/voicechat/voicechat-server.properties`.
4. Проверь/поправь `voice_chat_port` в этом конфиге и открой ровно этот
   порт в файрволе (см. §2.7 — по умолчанию `24454/udp`).
5. Игроку нужен клиентский мод/аддон Simple Voice Chat — ставится на его
   стороне (тоже с Modrinth, под его лаунчер и версию), панели и сервера
   это не касается.

Несколько серверов с войсчатом одновременно — каждому свой UDP-порт (при
конфликте плагин сам предложит свободный, либо пропиши явно в конфиге
каждого сервера).

---

## Заметка про kitty при работе по SSH

Если управляешь сервером по SSH из терминала **kitty**, у него нестандартный
`TERM=xterm-kitty`. На сервере, где нет kitty-terminfo, это иногда даёт
`ssh: unknown terminal type`, ломает `clear`, `less`, редакторы в терминале и т.п.
Варианты:

- Подключаться через kitty-киттен, который сам довозит terminfo на сервер:
  ```bash
  kitten ssh mcserver@admin.dan1kkystudio.ru
  ```
- Либо один раз скопировать terminfo вручную на сервер обычным `ssh`:
  ```bash
  infocmp -x xterm-kitty | ssh mcserver@admin.dan1kkystudio.ru -- tic -x -o \~/.terminfo /dev/stdin
  ```

После этого `ssh` (в т.ч. обычный, не kitty-киттен) будет нормально работать
из-под kitty-терминала на этом сервере.
