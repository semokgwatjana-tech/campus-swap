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
    config_name = config_name or os.environ.get("FLASK_ENV", "development")

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_by_name.get(config_name, config_by_name["development"]))

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # --- Extensions ---------------------------------------------------------
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # --- Blueprints ----------------------------------------------------
    from app.main import main_bp
    from app.auth import auth_bp
    from app.marketplace import marketplace_bp
    from app.transactions import transactions_bp
    from app.messaging import messaging_bp
    from app.admin import admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(marketplace_bp, url_prefix="/marketplace")
    app.register_blueprint(transactions_bp, url_prefix="/transactions")
    app.register_blueprint(messaging_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    # --- Shared template context -------------------------------------------
    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        from app.utils import unread_notification_count
        unread = 0
        if current_user.is_authenticated:
            unread = unread_notification_count(current_user.id)
        return {
            "currency": app.config["CURRENCY_SYMBOL"],
            "unread_notification_count": unread,
            "site_name": "Campus Swap",
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
        return render_template("errors/500.html"), 500

    # --- CLI commands -----------------------------------------------------
    from app.cli import register_cli_commands
    register_cli_commands(app)

    return app
