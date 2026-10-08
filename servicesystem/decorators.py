from functools import wraps

from flask import abort, flash, jsonify, redirect, request, url_for
from flask_login import current_user


def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))
            if current_user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def staff_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_staff:
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def content_cms_required(fn):
    """Admin, auditor, or executor: tutorials and video CMS (not plugins/contracts/users)."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not (current_user.is_admin or current_user.is_auditor or current_user.is_executor):
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def contract_access_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if current_user.is_staff:
            return fn(*args, **kwargs)
        contract = current_user.contract
        if not contract or contract.is_blocked:
            flash("Доступ заблокирован. Обратитесь к администратору.", "danger")
            return redirect(url_for("auth.login"))
        return fn(*args, **kwargs)
    return wrapper


def write_access_required(fn):
    """Block write operations for suspended contracts."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_staff and current_user.contract and current_user.contract.is_readonly:
            flash("Договор приостановлен. Доступ только для чтения.", "warning")
            return redirect(url_for("cabinet.dashboard"))
        return fn(*args, **kwargs)
    return wrapper


def upload_access_required(fn):
    """Customers need write access; staff may upload response files."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if current_user.is_staff:
            return fn(*args, **kwargs)
        if current_user.is_customer and current_user.contract and current_user.contract.is_readonly:
            if request.is_json or request.path.startswith("/uploads/"):
                return jsonify({"error": "readonly contract"}), 403
            flash("Договор приостановлен. Доступ только для чтения.", "warning")
            return redirect(url_for("cabinet.dashboard"))
        return fn(*args, **kwargs)
    return wrapper
