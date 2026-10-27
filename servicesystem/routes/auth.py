from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from servicesystem.extensions import db
from servicesystem.models import Contract, User, utcnow
from servicesystem.services.audit import log_audit

bp = Blueprint("auth", __name__)


@bp.after_request
def auth_no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


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
        flash("Договор расторгнут или срок обслуживания истёк. Обратитесь к администратору.", "danger")
        return redirect(url_for("auth.login"))
    if contract.is_master_key_expired:
        flash("Срок действия мастер-ключа истёк. Обратитесь к администратору.", "danger")
        return redirect(url_for("auth.login"))
    session["master_contract_id"] = contract.id
    log_audit(None, "master_login", "contract", contract.id, f"org={contract.organization.name}")
    db.session.commit()
    return redirect(url_for("auth.register"))


def _personal_login():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        flash("Неверный email или пароль.", "danger")
        return redirect(url_for("auth.login"))
    if user.is_customer and user.contract:
        if user.is_customer_curator and user.contract.is_access_disabled:
            from servicesystem.project_management.services import (
                ensure_customer_curator_contract_access,
            )

            ensure_customer_curator_contract_access(user)
            db.session.commit()
        if user.contract.is_access_disabled:
            if user.is_active:
                user.is_active = False
                db.session.commit()
            when = user.contract.access_disabled_at
            when_txt = when.strftime("%d.%m.%Y") if when else "—"
            if user.contract.is_master_key_expired:
                flash(
                    f"Мастер-ключ организации истёк ({when_txt}). Доступ отключён. "
                    "Обратитесь к администратору.",
                    "danger",
                )
            else:
                flash(
                    f"Доступ организации заблокирован или срок обслуживания истёк "
                    f"(до {when_txt}). Обратитесь к администратору.",
                    "danger",
                )
            return redirect(url_for("auth.login"))
    if not user.is_active:
        flash("Учётная запись отключена. Обратитесь к администратору.", "danger")
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
    if not contract or contract.is_blocked or contract.is_master_key_expired:
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
        phone_mobile = request.form.get("phone_mobile", "").strip() or request.form.get("phone", "").strip()
        if not phone_mobile:
            flash("Укажите мобильный телефон.", "danger")
            return redirect(url_for("auth.register"))

        user = User(
            email=email,
            full_name=request.form.get("full_name", "").strip(),
            position=request.form.get("position", "").strip(),
            phone=phone_mobile,
            phone_work=(request.form.get("phone_work") or "").strip() or None,
            phone_extension=(request.form.get("phone_extension") or "").strip() or None,
            role="customer",
            contract_id=contract.id,
            organization_id=contract.organization_id,
            pd_consent_at=utcnow(),
        )
        user.set_password(request.form.get("password", ""))
        db.session.add(user)
        db.session.flush()
        from servicesystem.services.directory_sync import create_contact_from_user

        create_contact_from_user(user, author_id=user.id)
        log_audit(
            user.id,
            "register",
            "user",
            user.id,
            f"contract={contract.number}, org={contract.organization.name}, email={email}",
        )
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
