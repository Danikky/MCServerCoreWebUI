from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models import ROLE_VIEWER, User

bp = Blueprint("auth", __name__)


@bp.route('/register', methods=['GET', 'POST'])
def register():
    # Без проверки все залогиненные пользователи имели бы шанс получить
    # полный доступ к панели — открытая регистрация была анонимным путём к
    # контролю над сервером. Включается явно через ALLOW_REGISTRATION=1.
    # Новые аккаунты всегда создаются с ролью viewer — до admin повышает
    # только другой admin (сейчас — руками в БД, см. REVIEW.md).
    if not current_app.config["ALLOW_REGISTRATION"]:
        abort(404)
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        try:
            db.session.add(User(username=username, password=password, role=ROLE_VIEWER))
            db.session.commit()
            flash('Регистрация прошла успешно!')
            return redirect(url_for('auth.login'))
        except IntegrityError:
            db.session.rollback()
            flash('Пользователь с таким именем уже существует')
    return render_template('register.html')


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('misc.index'))
        flash('Неверное имя пользователя или пароль')
    return render_template('login.html')


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('misc.index'))
