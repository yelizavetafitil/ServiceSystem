import os
from datetime import datetime, timezone

from flask import Flask, render_template, request
from flask_login import current_user

from sqlalchemy import text

from servicesystem.config import Config
from servicesystem.extensions import db, login_manager, csrf
from servicesystem.models import User
from flask_wtf.csrf import CSRFError


def create_app(config_class=Config):
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_object(config_class)

    if app.config.get("SESSION_COOKIE_SECURE") == "auto":
        app.config["SESSION_COOKIE_SECURE"] = app.config.get("FORCE_HTTPS", False)
    elif app.config.get("SESSION_COOKIE_SECURE") == "1":
        app.config["SESSION_COOKIE_SECURE"] = True

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from servicesystem.routes.auth import bp as auth_bp
    from servicesystem.routes.cabinet import bp as cabinet_bp
    from servicesystem.routes.tickets import bp as tickets_bp
    from servicesystem.routes.admin import bp as admin_bp
    from servicesystem.routes.api import bp as api_bp
    from servicesystem.routes.uploads import bp as uploads_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(cabinet_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/api/v1")
    app.register_blueprint(uploads_bp)

    import bleach
    import markdown as md_lib

    allowed_tags = bleach.sanitizer.ALLOWED_TAGS.union({
        "p", "h1", "h2", "h3", "h4", "pre", "code", "ul", "ol", "li", "strong", "em",
        "br", "hr", "table", "thead", "tbody", "tr", "th", "td", "img", "blockquote",
    })
    allowed_attrs = {
        "a": ["href", "title", "rel"],
        "code": ["class"],
        "img": ["src", "alt", "title", "width", "height"],
    }

    @app.template_filter("markdown")
    def markdown_filter(text):
        if not text:
            return ""
        html = md_lib.markdown(text, extensions=["fenced_code", "tables", "nl2br"])
        return bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs)

    @app.before_request
    def force_https():
        if app.config.get("FORCE_HTTPS") and not request.is_secure:
            if request.headers.get("X-Forwarded-Proto", "http") != "https":
                url = request.url.replace("http://", "https://", 1)
                from flask import redirect
                return redirect(url, code=301)

    @app.before_request
    def session_idle_timeout():
        """Server-side 60 min inactivity lock (TZ 5.1.3)."""
        from flask import flash, redirect, session, url_for
        from flask_login import current_user, logout_user

        if not current_user.is_authenticated:
            return
        if request.endpoint and request.endpoint.startswith("static"):
            return
        now = datetime.now(timezone.utc)
        raw = session.get("_last_activity")
        if raw:
            try:
                last = datetime.fromisoformat(raw)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                idle_sec = (now - last).total_seconds()
                if idle_sec > app.config["PERMANENT_SESSION_LIFETIME"].total_seconds():
                    logout_user()
                    session.clear()
                    flash("Сессия завершена после 60 минут неактивности. Войдите снова.", "warning")
                    return redirect(url_for("auth.login"))
            except ValueError:
                pass
        session["_last_activity"] = now.isoformat()
        session.modified = True

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if app.config.get("FORCE_HTTPS"):
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response

    @app.context_processor
    def inject_globals():
        banner = None
        auditor_alerts = []
        maintenance_banner = app.config.get("MAINTENANCE_MESSAGE") or None
        if current_user.is_authenticated and current_user.is_customer and current_user.contract:
            days = current_user.contract.days_until_expiry
            if days is not None and days <= 30:
                banner = (
                    f"Внимание: срок обслуживания по договору {current_user.contract.number} "
                    f"истекает {current_user.contract.service_end_date.strftime('%d.%m.%Y')}. "
                    "Для сохранения доступа к обновлениям плагинов необходимо продление договора."
                )
        if current_user.is_authenticated and current_user.is_auditor:
            from servicesystem.models import Contract
            expiring = Contract.query.filter(
                Contract.service_end_date.isnot(None),
                Contract.status.in_(["active_warranty", "active_post_warranty"]),
            ).all()
            for c in expiring:
                if c.days_until_expiry is not None and c.days_until_expiry <= 60:
                    auditor_alerts.append(
                        f"Договор {c.number} ({c.organization.name}) — осталось {c.days_until_expiry} дн. "
                        f"(рекомендуется инициировать переговоры о пролонгации техподдержки)"
                    )
        from servicesystem.services.sla import format_duration, sla_status
        return {
            "APP_NAME": app.config["APP_NAME"],
            "ORG_NAME": app.config["ORG_NAME"],
            "SLA_PRIORITIES": app.config["SLA_PRIORITIES"],
            "CONTRACT_STATUSES": app.config["CONTRACT_STATUSES"],
            "TICKET_STATUSES": app.config["TICKET_STATUSES"],
            "ROLES": app.config["ROLES"],
            "HISTORY_ACTION_LABELS": app.config.get("HISTORY_ACTION_LABELS", {}),
            "expiry_banner": banner,
            "auditor_alerts": auditor_alerts,
            "maintenance_banner": maintenance_banner,
            "MAINTENANCE_AT": app.config.get("MAINTENANCE_AT", ""),
            "MAX_UPLOAD_MB": app.config.get("MAX_UPLOAD_MB", 100),
            "sla_status": sla_status,
            "format_duration": format_duration,
        }

    @app.route("/health")
    def health():
        return {"status": "ok", "service": "servicesystem"}

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(CSRFError)
    def handle_csrf(e):
        from flask import flash, redirect, request, url_for
        flash("Сессия устарела. Обновите страницу (Ctrl+F5) и повторите действие.", "warning")
        return redirect(request.referrer or url_for("auth.login"))

    with app.app_context():
        try:
            db.create_all()
            _apply_schema_patches()
            _setup_audit_triggers()
        except Exception as exc:
            app.logger.warning("Database init deferred: %s", exc)

    return app


def _apply_schema_patches():
    """Add columns/tables on existing deployments without Alembic."""
    patches = [
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS master_key_expires_at DATE",
        "ALTER TABLE video_tutorials ADD COLUMN IF NOT EXISTS video_file VARCHAR(512)",
    ]
    for sql in patches:
        try:
            db.session.execute(text(sql))
        except Exception:
            db.session.rollback()
    db.session.commit()


def _setup_audit_triggers():
    """Prevent UPDATE/DELETE on immutable audit tables via DB triggers."""
    try:
        db.session.execute(text("""
            CREATE OR REPLACE FUNCTION prevent_audit_modification()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'Audit records are immutable';
            END;
            $$ LANGUAGE plpgsql;
        """))
        for table in ("audit_logs", "ticket_history"):
            db.session.execute(text(f"""
                DROP TRIGGER IF EXISTS trg_immutable_{table} ON {table};
                CREATE TRIGGER trg_immutable_{table}
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION prevent_audit_modification();
            """))
        db.session.commit()
    except Exception:
        db.session.rollback()
