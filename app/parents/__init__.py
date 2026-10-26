from flask import Blueprint

parents_bp = Blueprint("parents", __name__)

from app.parents import routes  # noqa: E402,F401
