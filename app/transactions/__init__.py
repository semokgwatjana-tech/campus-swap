from flask import Blueprint

transactions_bp = Blueprint("transactions", __name__, template_folder="../templates/transactions")

from app.transactions import routes  # noqa: E402,F401
