"""
Shared Flask extension instances.

Kept in their own module (rather than created inside app/__init__.py) so
blueprints, models, and utility modules can import `db`, `login_manager`,
etc. without triggering circular imports.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to access Campus Swap."
login_manager.login_message_category = "info"
