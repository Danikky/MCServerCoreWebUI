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
    server_name your-domain.com;

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

### 2.6 Домен и HTTPS

1. У регистратора/DNS-провайдера домена создай A-запись `your-domain.com → IP сервера`.
2. Дождись распространения (обычно от пары минут до пары часов).
3. Получи сертификат через certbot:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

Certbot сам допишет `listen 443 ssl`, сертификаты и редирект с 80 на 443
в конфиг nginx, и настроит автопродление (проверить: `sudo certbot renew --dry-run`).

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
на сервере, ключ `server-port`).

### 2.8 Обновление после деплоя

```bash
cd /home/mcserver/MCServerCoreWebUI
git pull
./setup.sh                      # подтянет новые зависимости, если есть
sudo systemctl restart mcservercore
```

---

## Заметка про kitty при работе по SSH

Если управляешь сервером по SSH из терминала **kitty**, у него нестандартный
`TERM=xterm-kitty`. На сервере, где нет kitty-terminfo, это иногда даёт
`ssh: unknown terminal type`, ломает `clear`, `less`, редакторы в терминале и т.п.
Варианты:

- Подключаться через kitty-киттен, который сам довозит terminfo на сервер:
  ```bash
  kitten ssh mcserver@your-domain.com
  ```
- Либо один раз скопировать terminfo вручную на сервер обычным `ssh`:
  ```bash
  infocmp -x xterm-kitty | ssh mcserver@your-domain.com -- tic -x -o \~/.terminfo /dev/stdin
  ```

После этого `ssh` (в т.ч. обычный, не kitty-киттен) будет нормально работать
из-под kitty-терминала на этом сервере.
