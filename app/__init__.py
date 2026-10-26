"""
Campus Swap - Application Factory
------------------------------------
`create_app()` wires together configuration, extensions, blueprints, and
shared template context so the project stays modular: models, routes,
templates, static files, utilities, and configuration are all separated
into their own files/folders per Python/Flask best practice.
"""

import os

from flask import Flask

from config import config_by_name
from app.extensions import db, login_manager, csrf


def create_app(config_name=None):
    # Safe by default: with no setting at all this is the LIVE configuration. Local work
    # must say so with FLASK_ENV=development.
    config_name = config_name or os.environ.get("FLASK_ENV") or "production"

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_by_name.get(config_name, config_by_name["production"]))

    if config_name == "production":
        key = app.config["SECRET_KEY"] or ""
        if key.startswith("dev-secret") or len(key) < 32:
            raise RuntimeError(
                "SECRET_KEY is missing or too weak. On a live site set a long random SECRET_KEY "
                "(at least 32 characters). For work on your own computer set FLASK_ENV=development.")

    if app.config["TRUSTED_PROXIES"]:
        from werkzeug.middleware.proxy_fix import ProxyFix
        n = app.config["TRUSTED_PROXIES"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n)

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # --- Extensions ---------------------------------------------------------
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        # The stored id looks like "12:3" (account number : session version). If the version
        # no longer matches, the person changed their password or signed out everywhere.
        try:
            uid, version = (int(part) for part in str(user_id).split(":"))
        except ValueError:
            return None
        user = db.session.get(User, uid)
        if user is None or (user.session_version or 0) != version or user.deleted_at:
            return None
        return user

    from app.security_headers import init_security_headers
    from app.gates import init_gates
    init_security_headers(app)
    init_gates(app)

    # --- Blueprints ----------------------------------------------------
    from app.main import main_bp
    from app.auth import auth_bp
    from app.marketplace import marketplace_bp
    from app.transactions import transactions_bp
    from app.messaging import messaging_bp
    from app.admin import admin_bp
    from app.settings import settings_bp
    from app.parents import parents_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(marketplace_bp, url_prefix="/marketplace")
    app.register_blueprint(transactions_bp, url_prefix="/transactions")
    app.register_blueprint(messaging_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(settings_bp)
    app.register_blueprint(parents_bp, url_prefix="/parent")

    # --- Shared template context -------------------------------------------
    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        from app.utils import unread_notification_count
        from app.models import UserSettings, THEMES
        theme_colors = {"light": "#157347", "dark": "#151a23", "blue": "#e6eefb", "velvet": "#2a0f1c"}
        unread = 0
        theme, contrast, animations = "light", False, True
        if current_user.is_authenticated:
            unread = unread_notification_count(current_user.id)
            row = UserSettings.query.filter_by(user_id=current_user.id).first()
            if row:
                theme = row.theme if row.theme in THEMES else "light"
                contrast, animations = row.increase_contrast, row.animations_enabled
        return {
            "ui_theme": theme,
            "ui_contrast": contrast and theme == "light",
            "ui_no_anim": not animations,
            "ui_theme_color": theme_colors[theme],
            "app_version": app.config["APP_VERSION"],
            "currency": app.config["CURRENCY_SYMBOL"],
            "unread_notification_count": unread,
            "site_name": "Campus Swap",
            "payment_mode": app.config["PAYMENT_GATEWAY"],
            "business": {
                "name": app.config["BUSINESS_NAME"],
                "reg_number": app.config["BUSINESS_REG_NUMBER"],
                "address": app.config["BUSINESS_ADDRESS"],
                "support_email": app.config["SUPPORT_EMAIL"],
                "privacy_email": app.config["PRIVACY_EMAIL"],
                "information_officer_email": app.config["INFORMATION_OFFICER_EMAIL"],
                "phone": app.config["BUSINESS_PHONE"],
                "last_updated": app.config["LEGAL_LAST_UPDATED"],
            },
        }

    # --- Error handlers -------------------------------------------------
    from flask import render_template

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        return render_template("errors/500.html"), 500

    # --- CLI commands -----------------------------------------------------
    from app.cli import register_cli_commands
    register_cli_commands(app)

    return app
