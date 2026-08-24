"""
Планировщик задач — авто-бекапы/рестарты/стопы/старты/команды по
расписанию (ScheduledTask в app/models.py). APScheduler (BackgroundScheduler)
в том же процессе, без внешнего брокера — соответствует масштабу проекта
(self-hosted, один процесс), тот же принцип, что и весь остальной async-код
здесь (daemon-потоки, а не Celery).

Источник правды — таблица ScheduledTask; APScheduler в рантайме держит
только производные от неё джобы в памяти. sync_from_db() каждый раз
пересобирает джобы с нуля из БД — проще и надёжнее, чем аккуратно диффать
добавления/удаления/изменения по одной, а вызывается редко (при старте
приложения и после любого изменения задачи через UI).
"""
import datetime as dt

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.extensions import db
from app.models import ScheduledTask


class TaskScheduler:
    def __init__(self, app):
        self.app = app
        self._scheduler = BackgroundScheduler(daemon=True)

    def start(self):
        self._scheduler.start()
        self.sync_from_db()

    @staticmethod
    def _job_id(task_id: int) -> str:
        return f"scheduled-task-{task_id}"

    @staticmethod
    def build_trigger(schedule_kind: str, schedule_value: str):
        """Кидает ValueError с понятным сообщением при некорректном
        schedule_value — вызывающий код (routes/scheduler.py) обязан это
        ловить и показать admin'у, а не давать 500."""
        if schedule_kind == "interval":
            hours = float(schedule_value)
            if hours <= 0:
                raise ValueError("Интервал должен быть больше 0")
            return IntervalTrigger(hours=hours)
        if schedule_kind == "daily":
            hh, _, mm = schedule_value.partition(":")
            return CronTrigger(hour=int(hh), minute=int(mm))
        if schedule_kind == "cron":
            return CronTrigger.from_crontab(schedule_value)
        raise ValueError(f"Неизвестный тип расписания: {schedule_kind}")

    def sync_from_db(self):
        for job in self._scheduler.get_jobs():
            self._scheduler.remove_job(job.id)
        with self.app.app_context():
            for task in ScheduledTask.query.filter_by(enabled=True).all():
                self._add_job(task)

    def _add_job(self, task: ScheduledTask):
        try:
            trigger = self.build_trigger(task.schedule_kind, task.schedule_value)
        except (ValueError, KeyError):
            # Битое расписание (не должно случиться, если UI валидирует
            # перед сохранением, но лучше молча пропустить джобу, чем
            # уронить весь sync_from_db на старте приложения).
            return
        self._scheduler.add_job(
            _run_task,
            trigger=trigger,
            id=self._job_id(task.id),
            args=[self.app, task.id],
            replace_existing=True,
            # Если панель была выключена дольше интервала — не пытаться
            # разом отыграть все пропущенные срабатывания при старте.
            misfire_grace_time=3600,
        )

    def run_now(self, task_id: int):
        """Выполняет задачу немедленно, вне расписания — чтобы проверить,
        что она настроена правильно, не дожидаясь реального времени."""
        _run_task(self.app, task_id)

    def unschedule_for_server(self, server_id: int):
        """Вызывается перед удалением Server — снимает с рантайм-расписания
        все его задачи (сами строки ScheduledTask падают каскадом в БД,
        см. Server.scheduled_tasks, но джобы APScheduler в памяти — отдельно)."""
        with self.app.app_context():
            task_ids = [t.id for t in ScheduledTask.query.filter_by(server_id=server_id).all()]
        for task_id in task_ids:
            job_id = self._job_id(task_id)
            if self._scheduler.get_job(job_id):
                self._scheduler.remove_job(job_id)


def _prune_backups(server, prefix: str, keep: int | None):
    if not keep or keep <= 0:
        return
    matching = sorted(n for n in server.get_backups_list() if n.startswith(f"{prefix}-"))
    for name in matching[:-keep] if keep < len(matching) else []:
        server.delete_backup(name)


def _run_task(app, task_id: int):
    with app.app_context():
        task = db.session.get(ScheduledTask, task_id)
        if task is None or not task.enabled:
            return
        server = app.server_registry.get(task.server_id)
        status = "выполнено"
        try:
            if task.type == "backup":
                prefix = (task.payload or "auto").strip() or "auto"
                server.create_backup(prefix)
                _prune_backups(server, prefix, task.retention)
            elif task.type == "restart":
                # restart_server() сам разбирается, запущен ли сервер —
                # если нет, просто стартует (см. _do_restart).
                server.restart_server()
            elif task.type == "command":
                if server.is_server_running():
                    server.send_command_direct(task.payload or "")
                else:
                    status = "пропущено — сервер offline"
            elif task.type == "stop":
                if server.is_server_running():
                    server.send_command_direct("stop")
                else:
                    status = "пропущено — уже offline"
            elif task.type == "start":
                if not server.is_server_running():
                    server.start_server()
                else:
                    status = "пропущено — уже запущен"
            else:
                status = f"неизвестный тип задачи: {task.type}"
        except Exception as e:
            status = f"ошибка: {e}"
        task.last_run_at = dt.datetime.utcnow()
        task.last_run_status = status
        db.session.commit()
