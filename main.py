"""
Точка входа. Вся логика — в пакете app/ (фабрика create_app(), блюпринты,
модели, ServerManager). main.py оставлен на верхнем уровне ради обратной
совместимости с setup.sh/launch.sh/DEPLOY.md (python3 main.py).
"""
from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == "__main__":
    # allow_unsafe_werkzeug: без async_mode eventlet/gevent, Flask-SocketIO
    # отказывается стартовать вне tty (например под systemd) — а мы
    # осознанно остаёмся на threading-режиме (реальные потоки), потому что
    # ServerManager гоняет блокирующий subprocess.stdout.readline() в фоновом
    # потоке; под gevent/eventlet это надо аккуратно делать зелёным, иначе
    # рискуем подвесить весь event loop на чтении консоли. Для масштаба этой
    # панели (несколько админов, один управляемый сервер) — нормальный
    # компромисс при условии, что снаружи она всегда за nginx (см. DEPLOY.md).
    socketio.run(
        app,
        host=app.config["HOST"],
        port=app.config["PORT"],
        debug=app.config["DEBUG"],
        allow_unsafe_werkzeug=True,
    )
