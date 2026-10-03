"""
Campus Swap - Configuration
----------------------------
Central configuration for the Flask application. Values are read from
environment variables where possible so the same codebase can move from a
local SQLite dev database to a production PostgreSQL database without any
code changes.
"""

import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Base configuration shared by every environment."""

    # --- Core / security -------------------------------------------------
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me-in-production")
    WTF_CSRF_ENABLED = True
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # --- Database ----------------------------------------------------------
    # SQLite for local development. Swap DATABASE_URL for a PostgreSQL DSN in
    # production, e.g. postgresql://user:pass@host:5432/campus_swap
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "instance", "campus_swap.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- Uploads -------------------------------------------------------
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "uploads")
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8 MB max upload
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

    # --- Campus Swap business rules ----------------------------------------
    # Only students with an email ending in one of these domains can register.
    # Left empty ([]) disables the restriction (accepts any email) which is
    # useful for the demo/prototype. Add real campus domains for production,
    # e.g. ["@uj.ac.za", "@wits.ac.za", "@up.ac.za"].
    ALLOWED_SCHOOL_EMAIL_DOMAINS = []

    RESERVATION_TIMEOUT_MINUTES = 15  # how long a listing stays reserved during checkout
    DEFAULT_SERVICE_FEE_PERCENT = 2.5  # configurable platform fee, admin can override
    DEFAULT_SERVICE_FEE_FIXED = 0.0
    CURRENCY_SYMBOL = "R"

    SAFE_PICKUP_POINTS = [
        "Campus Library",
        "Student Centre",
        "Campus Security Office",
        "Residence Reception",
        "Designated Campus Pickup Point",
    ]


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
