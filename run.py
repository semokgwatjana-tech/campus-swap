"""
Campus Swap - Development entry point.

    python run.py

For production, use a WSGI server instead, e.g.:
    gunicorn "run:app"
"""

import os
from app import create_app
from app.extensions import db

# Running this file directly (python run.py) is local work. Anything else, such as a web
# server importing it, is treated as the live site unless FLASK_ENV says otherwise.
app = create_app(os.environ.get("FLASK_ENV") or ("development" if __name__ == "__main__" else "production"))


@app.shell_context_processor
def make_shell_context():
    """Enables `flask shell` to have models pre-imported."""
    from app import models
    return {"db": db, "models": models}


if __name__ == "__main__":
    with app.app_context():
        db.create_all()  # convenient for first run; use `flask init-db` in normal workflow
    # The interactive debugger lets anyone who can reach the page run code on this
    # computer, so it is only on for the local address 127.0.0.1.
    app.run(debug=app.config["DEBUG"], host="127.0.0.1", port=5000)
