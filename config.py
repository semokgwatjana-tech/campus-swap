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
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_DURATION = timedelta(days=14)

    # How many proxy servers sit in front of the app (0 = none). It decides which
    # address counts as the visitor's, which the sign-in limits depend on. If it is
    # too high, visitors can fake their address. PythonAnywhere uses 1.
    TRUSTED_PROXIES = int(os.environ.get("TRUSTED_PROXIES", "0"))

    # Browser security policy: enforce | report-only | off
    CSP_MODE = os.environ.get("CSP_MODE", "enforce")

    # Administrators must have two-step verification on before using /admin.
    REQUIRE_ADMIN_2FA = True

    # Email confirmation and parent/guardian links
    EMAIL_VERIFY_HOURS = 24
    GUARDIAN_LINK_DAYS = 7
    GUARDIAN_SIGNIN_MINUTES = 30
    GUARDIAN_SESSION_HOURS = 2

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
    # Left empty ([]) disables the restriction (any email can register, and an
    # admin still verifies each student). Add real school domains if you want
    # to limit sign-ups, e.g. ["@uj.ac.za", "@wits.ac.za", "@up.ac.za"].
    # Set ALLOWED_SCHOOL_EMAIL_DOMAINS as a comma separated environment
    # variable, e.g. "@uj.ac.za,@wits.ac.za". Empty means any email can
    # register (admins still verify each student before they can trade).
    ALLOWED_SCHOOL_EMAIL_DOMAINS = [
        d.strip().lower()
        for d in os.environ.get("ALLOWED_SCHOOL_EMAIL_DOMAINS", "").split(",")
        if d.strip()
    ]

    SWAP_TOPUP_HOURS = 24  # how long both items are held while a swap top-up is paid
    RESERVATION_TIMEOUT_MINUTES = 15  # how long a listing stays reserved during checkout
    DEFAULT_SERVICE_FEE_PERCENT = 2.5  # configurable platform fee, admin can override
    DEFAULT_SERVICE_FEE_FIXED = 0.0
    CURRENCY_SYMBOL = "R"

    # --- Business details shown in the footer and legal pages ---------------
    # Set these as environment variables on the server. Until they are set,
    # the placeholders below stay visible so nobody mistakes them for real
    # details.
    BUSINESS_NAME = os.environ.get("BUSINESS_NAME", "semokholdings")
    BUSINESS_REG_NUMBER = os.environ.get("BUSINESS_REG_NUMBER", "[INSERT COMPANY REGISTRATION NUMBER]")
    BUSINESS_ADDRESS = os.environ.get("BUSINESS_ADDRESS", "16676 Malibongwe St")
    BUSINESS_PHONE = os.environ.get("BUSINESS_PHONE", "0817370210")
    SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "semokgwatjana@gmail.com")
    PRIVACY_EMAIL = os.environ.get("PRIVACY_EMAIL", os.environ.get("SUPPORT_EMAIL", "[INSERT PRIVACY CONTACT EMAIL]"))
    INFORMATION_OFFICER_EMAIL = os.environ.get(
        "INFORMATION_OFFICER_EMAIL", os.environ.get("SUPPORT_EMAIL", "[INSERT INFORMATION OFFICER EMAIL]")
    )
    LEGAL_LAST_UPDATED = os.environ.get("LEGAL_LAST_UPDATED", "[INSERT DATE]")

    # --- Email (password reset etc.) -----------------------------------------
    # MAIL_PROVIDER: "" (off), "smtp" (Gmail works on PythonAnywhere free),
    # or "sendgrid" (HTTPS API, also works on the free plan).
    MAIL_PROVIDER = os.environ.get("MAIL_PROVIDER", "").lower()
    MAIL_FROM = os.environ.get("MAIL_FROM", "")
    MAIL_SMTP_HOST = os.environ.get("MAIL_SMTP_HOST", "smtp.gmail.com")
    MAIL_SMTP_PORT = int(os.environ.get("MAIL_SMTP_PORT", "587"))
    MAIL_SMTP_USER = os.environ.get("MAIL_SMTP_USER", "")
    MAIL_SMTP_PASSWORD = os.environ.get("MAIL_SMTP_PASSWORD", "")  # Gmail app password
    SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")

    # --- Payments ---------------------------------------------------------------
    # "sandbox" = simulated payments, no real money moves. A real provider is
    # selected here once its gateway class exists in payment_gateway.py.
    PAYMENT_GATEWAY = os.environ.get("PAYMENT_GATEWAY", "sandbox").lower()

    # --- App version and update policy ---------------------------------------
    APP_VERSION = "2.0.0"
    UPDATE_GRACE_DAYS = 14

    # A chat offer, and an accepted offer, can be used for this many hours.
    OFFER_VALID_HOURS = 48

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
    REMEMBER_COOKIE_SECURE = True
    TRUSTED_PROXIES = int(os.environ.get("TRUSTED_PROXIES", "1"))


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    REQUIRE_ADMIN_2FA = False
    CSP_MODE = "off"
    SECRET_KEY = "testing-only-key-not-for-any-real-site-0123456789"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
