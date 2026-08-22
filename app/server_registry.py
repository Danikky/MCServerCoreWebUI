"""
ServerRegistry — держит по одному ServerManager на каждую строку Server в
БД, создавая их лениво и кэшируя в памяти на всё время жизни процесса.
Один инстанс на приложение (app.server_registry, см. app/__init__.py).
"""
import threading

from app.models import Server
from app.server_manager import ServerManager


class ServerRegistry:
    def __init__(self, app):
        self.app = app
        self._managers: dict[int, ServerManager] = {}
        self._lock = threading.Lock()

    def get(self, server_id: int) -> ServerManager | None:
        """Возвращает ServerManager для server_id, создавая его при первом
        обращении. None, если такого Server нет в БД."""
        with self._lock:
            manager = self._managers.get(server_id)
            if manager is not None:
                return manager
            with self.app.app_context():
                row = Server.query.get(server_id)
                if row is None:
                    return None
                manager = ServerManager(self.app, row)
                self._managers[server_id] = manager
            return manager

    def peek(self, server_id: int) -> ServerManager | None:
        """Как get(), но не создаёт ServerManager, если его ещё нет в кэше —
        для мест вроде списка серверов, где не хочется мимоходом создавать
        папку на диске для каждого Server только ради отображения статуса."""
        with self._lock:
            return self._managers.get(server_id)

    def forget(self, server_id: int):
        """Убирает ServerManager из кэша (например, после удаления Server —
        не трогает уже запущенный процесс, если он есть, поэтому проверяй
        is_server_running() перед удалением на уровне роута)."""
        with self._lock:
            self._managers.pop(server_id, None)
