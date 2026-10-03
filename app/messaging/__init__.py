from flask import Blueprint

messaging_bp = Blueprint("messaging", __name__, template_folder="../templates/messaging")

from app.messaging import routes  # noqa: E402,F401
