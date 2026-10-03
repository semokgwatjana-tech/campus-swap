"""
Campus Swap - Development entry point.

    python run.py

For production, use a WSGI server instead, e.g.:
    gunicorn "run:app"
"""

import os
from app import create_app
from app.extensions import db

app = create_app(os.environ.get("FLASK_ENV", "development"))


@app.shell_context_processor
def make_shell_context():
    """Enables `flask shell` to have models pre-imported."""
    from app import models
    return {"db": db, "models": models}


if __name__ == "__main__":
    with app.app_context():
        db.create_all()  # convenient for first run; use `flask init-db` in normal workflow
    app.run(debug=True, host="0.0.0.0", port=5000)
