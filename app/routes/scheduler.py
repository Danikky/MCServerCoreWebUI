from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from app.decorators import admin_required, with_server
from app.extensions import db
from app.models import SCHEDULE_KINDS, TASK_TYPES, ScheduledTask
from app.scheduler import TaskScheduler

bp = Blueprint("scheduler", __name__, url_prefix="/servers/<int:server_id>/scheduler")


# Планировщик — тот же уровень доступа, что у Файлов/Бекапов/Ядра
# (admin_required целиком): задачи по расписанию могут останавливать
# сервер, слать произвольные команды в консоль и т.п. — не то, что стоит
# доверять viewer'у.
@bp.route("", methods=["GET"])
@admin_required
@with_server
def scheduler_page(server_id):
    server = current_app.server_registry.get(server_id)
    tasks = ScheduledTask.query.filter_by(server_id=server_id).order_by(ScheduledTask.created_at).all()
    return render_template("scheduler_page.html", tasks=tasks, task_types=TASK_TYPES, backups=server.get_backups_list())


@bp.route("/create", methods=["POST"])
@admin_required
@with_server
def create_task(server_id):
    task_type = request.form.get("type", "")
    schedule_kind = request.form.get("schedule_kind", "")
    # Отдельное поле-значение под каждый вид расписания (число часов /
    # HH:MM из <input type=time> / сырой cron) — проще и надёжнее на
    # бэкенде, чем один общий текстовый инпут, который JS переписывает
    # перед отправкой.
    schedule_value = {
        "interval": request.form.get("value_interval", ""),
        "daily": request.form.get("value_daily", ""),
        "cron": request.form.get("value_cron", ""),
    }.get(schedule_kind, "").strip()
    # payload означает разное в зависимости от типа задачи — command и
    # backup держат его в разных полях формы (см. scheduler_page.html),
    # чтобы два одноимённых инпута в одной форме не путали друг друга.
    if task_type == "command":
        payload = request.form.get("payload", "").strip() or None
    elif task_type == "backup":
        payload = request.form.get("backup_prefix", "").strip() or "auto"
    else:
        payload = None
    retention_raw = request.form.get("retention", "").strip()

    if task_type not in TASK_TYPES:
        flash("Неизвестный тип задачи")
        return redirect(url_for("scheduler.scheduler_page", server_id=server_id))
    if schedule_kind not in SCHEDULE_KINDS:
        flash("Неизвестный тип расписания")
        return redirect(url_for("scheduler.scheduler_page", server_id=server_id))
    if task_type == "command" and not payload:
        flash("Для команды нужен её текст")
        return redirect(url_for("scheduler.scheduler_page", server_id=server_id))

    try:
        TaskScheduler.build_trigger(schedule_kind, schedule_value)
    except (ValueError, KeyError) as e:
        flash(f"Некорректное расписание: {e}")
        return redirect(url_for("scheduler.scheduler_page", server_id=server_id))

    retention = None
    if task_type == "backup" and retention_raw:
        try:
            retention = max(1, int(retention_raw))
        except ValueError:
            flash("«Хранить бекапов» — должно быть числом")
            return redirect(url_for("scheduler.scheduler_page", server_id=server_id))

    task = ScheduledTask(
        server_id=server_id,
        type=task_type,
        payload=payload,
        retention=retention,
        schedule_kind=schedule_kind,
        schedule_value=schedule_value,
    )
    db.session.add(task)
    db.session.commit()
    current_app.task_scheduler.sync_from_db()
    flash("Задача создана")
    return redirect(url_for("scheduler.scheduler_page", server_id=server_id))


@bp.route("/<int:task_id>/toggle", methods=["POST"])
@admin_required
@with_server
def toggle_task(server_id, task_id):
    task = ScheduledTask.query.filter_by(id=task_id, server_id=server_id).first_or_404()
    task.enabled = not task.enabled
    db.session.commit()
    current_app.task_scheduler.sync_from_db()
    return redirect(url_for("scheduler.scheduler_page", server_id=server_id))


@bp.route("/<int:task_id>/delete", methods=["POST"])
@admin_required
@with_server
def delete_task(server_id, task_id):
    task = ScheduledTask.query.filter_by(id=task_id, server_id=server_id).first_or_404()
    db.session.delete(task)
    db.session.commit()
    current_app.task_scheduler.sync_from_db()
    flash("Задача удалена")
    return redirect(url_for("scheduler.scheduler_page", server_id=server_id))


@bp.route("/<int:task_id>/run", methods=["POST"])
@admin_required
@with_server
def run_task(server_id, task_id):
    task = ScheduledTask.query.filter_by(id=task_id, server_id=server_id).first_or_404()
    current_app.task_scheduler.run_now(task.id)
    flash("Задача выполнена — смотри «Последний запуск»")
    return redirect(url_for("scheduler.scheduler_page", server_id=server_id))
