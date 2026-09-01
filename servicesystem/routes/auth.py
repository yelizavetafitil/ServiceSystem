from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from servicesystem.extensions import db
from servicesystem.models import Contract, User, utcnow
from servicesystem.services.audit import log_audit

bp = Blueprint("auth", __name__)


@bp.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for("admin.dashboard"))
        if current_user.is_staff:
            return redirect(url_for("tickets.staff_queue"))
        return redirect(url_for("cabinet.dashboard"))
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.index"))

    if request.method == "POST":
        login_type = request.form.get("login_type", "personal")
        if login_type == "master":
            return _master_login()
        return _personal_login()

    return render_template("auth/login.html")


def _master_login():
    master_login = request.form.get("master_login", "").strip()
    master_password = request.form.get("master_password", "")
    contract = Contract.query.filter_by(master_login=master_login).first()
    if not contract or not contract.check_master_password(master_password):
        flash("Неверный мастер-ключ организации.", "danger")
        return redirect(url_for("auth.login"))
    if contract.is_blocked:
        flash("Договор расторгнут. Доступ заблокирован.", "danger")
        return redirect(url_for("auth.login"))
    session["master_contract_id"] = contract.id
    return redirect(url_for("auth.register"))


def _personal_login():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    user = User.query.filter_by(email=email, is_active=True).first()
    if not user or not user.check_password(password):
        flash("Неверный email или пароль.", "danger")
        return redirect(url_for("auth.login"))
    if user.is_customer and user.contract and user.contract.is_blocked:
        flash("Доступ организации заблокирован.", "danger")
        return redirect(url_for("auth.login"))
    login_user(user, remember=False)
    session.permanent = True
    user.last_login_at = utcnow()
    log_audit(user.id, "login")
    db.session.commit()
    return redirect(url_for("auth.index"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    contract_id = session.get("master_contract_id")
    if not contract_id:
        flash("Сначала войдите по мастер-ключу организации.", "warning")
        return redirect(url_for("auth.login"))
    contract = db.session.get(Contract, contract_id)
    if not contract or contract.is_blocked:
        flash("Договор недоступен для регистрации.", "danger")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if User.query.filter_by(email=email).first():
            flash("Пользователь с таким email уже зарегистрирован.", "danger")
            return redirect(url_for("auth.register"))
        if not request.form.get("pd_consent"):
            flash("Необходимо согласие на обработку персональных данных.", "danger")
            return redirect(url_for("auth.register"))

        user = User(
            email=email,
            full_name=request.form.get("full_name", "").strip(),
            position=request.form.get("position", "").strip(),
            phone=request.form.get("phone", "").strip(),
            role="customer",
            contract_id=contract.id,
            organization_id=contract.organization_id,
            pd_consent_at=utcnow(),
        )
        user.set_password(request.form.get("password", ""))
        db.session.add(user)
        log_audit(None, "register", "user", details=f"email={email}, contract={contract.number}")
        db.session.commit()
        session.pop("master_contract_id", None)
        flash("Регистрация успешна. Войдите по персональному логину.", "success")
        return redirect(url_for("auth.login"))

    return render_template(
        "auth/register.html",
        contract=contract,
        org_name=contract.organization.name,
    )


@bp.route("/logout")
@login_required
def logout():
    log_audit(current_user.id, "logout")
    db.session.commit()
    logout_user()
    return redirect(url_for("auth.login"))


@bp.route("/privacy")
def privacy():
    return render_template("auth/privacy.html")
